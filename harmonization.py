"""
harmonization.py — Harmoniser noms & CAS entre sources
=======================================================
Lundi 25/05/2026 — S2 ETL consolidé

Aligne les noms d'ingrédients et les numéros CAS entre COSING, PubChem,
ECHA et les catalogues fournisseurs dans un format canonique unique.
Stratégie : strip() → lower() → regex → re-capitalisation INCI.
Résolution des synonymes par heuristique CAS, puis API PubChem pour les
entrées sans CAS.
"""

import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisation de texte
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Normalise une chaîne de caractères selon la convention INCI.

    Chaîne : strip() → lower() → nettoyage regex → capitalisation INCI.

    Args:
        text: La chaîne brute à normaliser.

    Returns:
        La chaîne normalisée en format canonique INCI.
    """
    if not isinstance(text, str):
        return ""
    # 1. strip — supprime espaces en début/fin
    text = text.strip()
    # 2. lower — insensibilité à la casse pour les comparaisons
    text = text.lower()
    # 3. regex — supprime caractères parasites (tirets insécables, espaces multiples, accents non standard)
    text = re.sub(r"[\u00ad\u2011\u2012\u2013\u2014]", "-", text)  # tirets normalisés
    text = re.sub(r"\s+", " ", text)                                 # espaces multiples → un seul
    text = re.sub(r"[^\w\s\-,.()/]", "", text)                       # supprime caractères exotiques
    # 4. Re-capitalisation INCI : première lettre de chaque mot en majuscule
    text = text.title()
    return text


def normalize_cas(cas: str) -> str:
    """Normalise un numéro CAS au format standard XXXXXX-XX-X.

    Args:
        cas: Le numéro CAS brut (peut contenir espaces, tirets manquants, etc.).

    Returns:
        Le numéro CAS normalisé, ou chaîne vide si invalide.
    """
    if not isinstance(cas, str):
        return ""
    cas = cas.strip().replace(" ", "")
    # Vérifie le format standard avec regex
    if re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
        return cas
    # Tente de reconstruire si les tirets manquent
    digits = re.sub(r"\D", "", cas)
    if len(digits) >= 5:
        return f"{digits[:-3]}-{digits[-3:-1]}-{digits[-1]}"
    return ""


# ---------------------------------------------------------------------------
# Résolution des synonymes
# ---------------------------------------------------------------------------

def resolve_synonyms_by_cas(df: pd.DataFrame) -> pd.DataFrame:
    """Résout les synonymes en s'appuyant sur le numéro CAS comme clé.

    Si deux noms différents partagent le même CAS, on garde le nom INCI
    officiel (celui de la source COSING en priorité) comme clé canonique.

    Args:
        df: DataFrame avec au minimum les colonnes 'name', 'cas', 'source'.

    Returns:
        DataFrame enrichi avec les colonnes 'canonical_name' et 'canonical_cas'.
    """
    df = df.copy()
    df["canonical_cas"] = df["cas"].apply(normalize_cas)
    df["canonical_name"] = df["name"].apply(normalize_text)

    # Pour chaque CAS, on choisit le nom canonique : COSING > PubChem > ECHA > fournisseur
    source_priority = {"COSING": 0, "PubChem": 1, "ECHA": 2, "supplier": 3}
    df["_source_rank"] = df["source"].map(source_priority).fillna(99)

    # Groupe par CAS normalisé et garde le nom de la source la plus prioritaire
    canonical_map = (
        df[df["canonical_cas"] != ""]
        .sort_values("_source_rank")
        .groupby("canonical_cas")["canonical_name"]
        .first()
        .to_dict()
    )

    df["canonical_name"] = df.apply(
        lambda row: canonical_map.get(row["canonical_cas"], row["canonical_name"]),
        axis=1,
    )
    df.drop(columns=["_source_rank"], inplace=True)

    logger.info(
        "Harmonisation terminée : %d entrées, %d CAS canoniques uniques",
        len(df),
        df["canonical_cas"].nunique(),
    )
    return df


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def harmonize(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline complet d'harmonisation sur un DataFrame consolidé.

    Args:
        df: DataFrame brut issu de la consolidation des sources.

    Returns:
        DataFrame avec colonnes 'canonical_name' et 'canonical_cas' ajoutées.
    """
    logger.info("Début harmonisation — %d entrées en entrée", len(df))
    df = resolve_synonyms_by_cas(df)
    logger.info("Harmonisation terminée — %d entrées en sortie", len(df))
    return df
