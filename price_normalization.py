"""
price_normalization.py — Normaliser les champs prix
====================================================
Mardi 26/05/2026 — S2 ETL consolidé

Standardise les champs de prix issus des catalogues fournisseurs.
Tout est converti en EUR par kilogramme, hors taxe.

Stratégie :
  - Extraction du montant numérique par regex (formats FR et EN)
  - Conversion de devise par taux fixes au 01/05/2026
  - Conversion d'unité (litre → kilo via densité si disponible)
  - Flag price_includes_vat pour déduire la TVA
"""

import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Taux de change fixes au 01/05/2026 (vers EUR)
EXCHANGE_RATES: dict[str, float] = {
    "EUR": 1.0,
    "USD": 0.922,
    "GBP": 1.168,
    "CHF": 1.013,
}

# TVA standard par pays (taux décimal)
VAT_RATES: dict[str, float] = {
    "FR": 0.20,
    "DE": 0.19,
    "GB": 0.20,
    "US": 0.0,
}


# ---------------------------------------------------------------------------
# Extraction du montant numérique
# ---------------------------------------------------------------------------

def extract_amount(price_str: str) -> float | None:
    """Extrait le montant numérique d'une chaîne de prix brute.

    Gère les formats français (1.234,56) et anglais (1,234.56).

    Args:
        price_str: Chaîne brute contenant un prix (ex. "1.234,56 €/kg").

    Returns:
        Le montant en float, ou None si non parseable.

    Example:
        >>> extract_amount("1.234,56 €/kg")
        1234.56
        >>> extract_amount("12.50/L")
        12.5
    """
    if not isinstance(price_str, str):
        return None
    # Nettoie les symboles de devise avant parsing
    cleaned = re.sub(r"[$€£¥]", "", price_str).strip()
    # Format français : 1.234,56 (point séparateur de milliers, virgule décimale)
    match_fr = re.search(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", cleaned)
    if match_fr:
        return float(match_fr.group(0).replace(".", "").replace(",", "."))
    # Format anglais : 1,234.56 (virgule séparateur de milliers, point décimal)
    match_en = re.search(r"\d{1,3}(?:,\d{3})+\.\d{1,2}", cleaned)
    if match_en:
        return float(match_en.group(0).replace(",", ""))
    # Nombre simple : 12,50 ou 12.50
    match_simple = re.search(r"\d+[.,]\d+", cleaned)
    if match_simple:
        return float(match_simple.group(0).replace(",", "."))
    # Entier pur
    match_int = re.search(r"\d+", cleaned)
    if match_int:
        return float(match_int.group(0))
    return None


# ---------------------------------------------------------------------------
# Détection de devise et d'unité
# ---------------------------------------------------------------------------

def detect_currency(price_str: str) -> str:
    """Détecte la devise dans une chaîne de prix.

    Args:
        price_str: Chaîne brute contenant un prix.

    Returns:
        Code devise (EUR, USD, GBP, CHF) ou 'EUR' par défaut.
    """
    if not isinstance(price_str, str):
        return "EUR"
    s = price_str.upper()
    if "$" in s or "USD" in s:
        return "USD"
    if "£" in s or "GBP" in s:
        return "GBP"
    if "CHF" in s:
        return "CHF"
    return "EUR"


def detect_unit(price_str: str) -> str:
    """Détecte l'unité dans une chaîne de prix.

    Args:
        price_str: Chaîne brute contenant un prix.

    Returns:
        'kg', 'l', 'g', 'ml', ou 'kg' par défaut.
    """
    if not isinstance(price_str, str):
        return "kg"
    s = price_str.lower()
    if "/l" in s or "per l" in s or "/litre" in s or "/liter" in s:
        return "l"
    if "/g" in s or "per g" in s or "/gram" in s:
        return "g"
    if "/ml" in s or "per ml" in s:
        return "ml"
    return "kg"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert_to_eur_per_kg(
    amount: float,
    currency: str,
    unit: str,
    density: float | None = None,
    includes_vat: bool = False,
    country: str = "FR",
) -> float | None:
    """Convertit un prix en EUR/kg HT.

    Args:
        amount:       Montant brut extrait.
        currency:     Code devise (EUR, USD, GBP, CHF).
        unit:         Unité source (kg, l, g, ml).
        density:      Densité en kg/L pour conversion litre→kilo (optionnel).
        includes_vat: True si le prix inclut la TVA.
        country:      Code pays pour le taux de TVA (défaut : FR).

    Returns:
        Prix en EUR/kg HT, ou None si conversion impossible.
    """
    if amount is None:
        return None

    # 1. Conversion de devise → EUR
    rate = EXCHANGE_RATES.get(currency, 1.0)
    amount_eur = amount * rate

    # 2. Déduction TVA si nécessaire
    if includes_vat:
        vat = VAT_RATES.get(country, 0.20)
        amount_eur = amount_eur / (1 + vat)

    # 3. Conversion d'unité → kg
    if unit == "kg":
        return round(amount_eur, 4)
    elif unit == "g":
        return round(amount_eur * 1000, 4)
    elif unit == "l":
        if density is not None:
            return round(amount_eur / density, 4)
        logger.warning("Conversion litre→kg impossible : densité manquante")
        return None
    elif unit == "ml":
        if density is not None:
            return round(amount_eur / (density / 1000), 4)
        return None
    return None


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise la colonne 'price_raw' du DataFrame en EUR/kg HT.

    Args:
        df: DataFrame avec colonnes 'price_raw', 'currency' (optionnel),
            'unit' (optionnel), 'density' (optionnel),
            'price_includes_vat' (optionnel), 'country' (optionnel).

    Returns:
        DataFrame avec la colonne 'price_eur_per_kg' ajoutée.
    """
    logger.info("Normalisation des prix — %d entrées en entrée", len(df))
    results = []

    for _, row in df.iterrows():
        price_raw = row.get("price_raw", "")
        amount    = extract_amount(str(price_raw))
        currency  = row.get("currency") or detect_currency(str(price_raw))
        unit      = row.get("unit")     or detect_unit(str(price_raw))
        density   = row.get("density",  None)
        includes_vat = bool(row.get("price_includes_vat", False))
        country   = row.get("country",  "FR")

        price_eur = convert_to_eur_per_kg(amount, currency, unit, density, includes_vat, country)
        results.append(price_eur)

    df = df.copy()
    df["price_eur_per_kg"] = results

    converted = df["price_eur_per_kg"].notna().sum()
    logger.info(
        "Normalisation des prix terminée : %d/%d prix convertis en EUR/kg",
        converted, len(df),
    )
    return df
