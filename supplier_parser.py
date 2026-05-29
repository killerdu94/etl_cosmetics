"""
supplier_parser.py — Parser catalogues fournisseurs
====================================================
Mardi 26/05/2026 — S2 ETL consolidé

Lit et structure les catalogues fournisseurs d'ingrédients cosmétiques.
Supporte les formats : CSV, Excel (.xlsx/.xls), PDF.
Interface commune : chaque parser retourne un DataFrame avec le même schéma.

Schéma de sortie :
    supplier        : str   — nom du fournisseur
    ingredient_name : str   — nom brut de l'ingrédient
    cas             : str   — numéro CAS brut
    price_raw       : str   — prix brut tel que dans le catalogue
    unit            : str   — unité de prix (kg, L, g…)
    currency        : str   — devise (EUR, USD, GBP…)
    min_order       : str   — quantité minimale de commande
    source          : str   — toujours "supplier"
"""

import io
import logging
import re
import chardet
import pandas as pd

logger = logging.getLogger(__name__)

# Colonnes standardisées en sortie
OUTPUT_COLUMNS = ["supplier", "ingredient_name", "cas", "price_raw", "unit", "currency", "min_order", "source"]


# ---------------------------------------------------------------------------
# Détection d'encodage
# ---------------------------------------------------------------------------

def detect_encoding(filepath: str) -> str:
    """Détecte l'encodage d'un fichier via chardet.

    Args:
        filepath: Chemin vers le fichier à analyser.

    Returns:
        Nom de l'encodage détecté (ex. 'utf-8', 'latin-1').
    """
    with open(filepath, "rb") as f:
        raw = f.read(50_000)  # Lit les 50 premiers Ko pour la détection
    result = chardet.detect(raw)
    encoding = result.get("encoding") or "utf-8"
    logger.debug("Encodage détecté pour %s : %s (confiance %.0f%%)", filepath, encoding, (result.get("confidence") or 0) * 100)
    return encoding


# ---------------------------------------------------------------------------
# Parser CSV
# ---------------------------------------------------------------------------

def parse_csv(filepath: str, supplier: str) -> pd.DataFrame:
    """Parse un catalogue fournisseur au format CSV.

    Détecte automatiquement le séparateur et l'encodage.

    Args:
        filepath: Chemin vers le fichier CSV.
        supplier: Nom du fournisseur.

    Returns:
        DataFrame normalisé avec les colonnes OUTPUT_COLUMNS.
    """
    encoding = detect_encoding(filepath)
    # Essaie les séparateurs courants
    for sep in [";", ",", "\t", "|"]:
        try:
            df = pd.read_csv(filepath, sep=sep, encoding=encoding, dtype=str)
            if len(df.columns) > 1:
                break
        except Exception:
            continue

    df = _rename_columns(df)
    df["supplier"] = supplier
    df["source"]   = "supplier"
    logger.info("CSV parsé : %d lignes depuis %s", len(df), filepath)
    return _ensure_columns(df)


# ---------------------------------------------------------------------------
# Parser Excel
# ---------------------------------------------------------------------------

def parse_excel(filepath: str, supplier: str) -> pd.DataFrame:
    """Parse un catalogue fournisseur au format Excel.

    Gère les feuilles multiples et les en-têtes sur plusieurs lignes.

    Args:
        filepath: Chemin vers le fichier Excel (.xlsx ou .xls).
        supplier: Nom du fournisseur.

    Returns:
        DataFrame normalisé avec les colonnes OUTPUT_COLUMNS.
    """
    xl = pd.ExcelFile(filepath)
    frames = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(filepath, sheet_name=sheet, dtype=str, header=0)
        # Si la première ligne ressemble à un sous-en-tête, on la saute
        if df.iloc[0].astype(str).str.contains(r"[Nn]ame|[Ii]ngr|[Cc]AS", regex=True).any():
            df.columns = df.iloc[0]
            df = df.iloc[1:].reset_index(drop=True)
        df = _rename_columns(df)
        df["supplier"] = supplier
        df["source"]   = "supplier"
        frames.append(df)

    result = pd.concat(frames, ignore_index=True)
    logger.info("Excel parsé : %d lignes depuis %s (%d feuilles)", len(result), filepath, len(xl.sheet_names))
    return _ensure_columns(result)


# ---------------------------------------------------------------------------
# Parser PDF
# ---------------------------------------------------------------------------

def parse_pdf(filepath: str, supplier: str) -> pd.DataFrame:
    """Parse un catalogue fournisseur au format PDF.

    Extrait les tableaux via pdfplumber, puis les lignes de données par regex.

    Args:
        filepath: Chemin vers le fichier PDF.
        supplier: Nom du fournisseur.

    Returns:
        DataFrame normalisé avec les colonnes OUTPUT_COLUMNS.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber non installé — pip install pdfplumber")
        return _empty_frame(supplier)

    rows = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(row):
                        rows.append([str(c or "").strip() for c in row])

    if not rows:
        logger.warning("Aucun tableau trouvé dans %s", filepath)
        return _empty_frame(supplier)

    df = pd.DataFrame(rows)
    # Utilise la première ligne comme en-tête si elle ne contient pas de CAS
    cas_pattern = re.compile(r"\d{2,7}-\d{2}-\d")
    if not cas_pattern.search(" ".join(df.iloc[0].tolist())):
        df.columns = df.iloc[0]
        df = df.iloc[1:].reset_index(drop=True)

    df = _rename_columns(df)
    df["supplier"] = supplier
    df["source"]   = "supplier"
    logger.info("PDF parsé : %d lignes depuis %s", len(df), filepath)
    return _ensure_columns(df)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

# Correspondances de noms de colonnes courants → noms canoniques
_COLUMN_MAP = {
    r"ingr[ée]dient|nom|name|product|produit": "ingredient_name",
    r"cas|cas.?n|cas.?number": "cas",
    r"prix|price|tarif|cost|coût": "price_raw",
    r"unit[ée]?|uom": "unit",
    r"devise|currency|curr": "currency",
    r"qté.?min|min.?order|commande.?min": "min_order",
}


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomme les colonnes du DataFrame vers les noms canoniques."""
    rename = {}
    for col in df.columns:
        col_str = str(col).lower().strip()
        for pattern, canonical in _COLUMN_MAP.items():
            if re.search(pattern, col_str):
                rename[col] = canonical
                break
    return df.rename(columns=rename)


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """S'assure que toutes les colonnes OUTPUT_COLUMNS existent."""
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[OUTPUT_COLUMNS].copy()


def _empty_frame(supplier: str) -> pd.DataFrame:
    """Retourne un DataFrame vide avec le bon schéma."""
    df = pd.DataFrame(columns=OUTPUT_COLUMNS)
    df["supplier"] = supplier
    df["source"]   = "supplier"
    return df


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def parse_supplier_catalogue(filepath: str, supplier: str) -> pd.DataFrame:
    """Parse un catalogue fournisseur quel que soit son format.

    Détecte automatiquement le format (CSV, Excel, PDF) et appelle
    le parser approprié.

    Args:
        filepath: Chemin vers le fichier catalogue.
        supplier: Nom du fournisseur.

    Returns:
        DataFrame normalisé avec les colonnes OUTPUT_COLUMNS.

    Raises:
        ValueError: Si le format de fichier n'est pas supporté.
    """
    ext = filepath.lower().rsplit(".", 1)[-1]
    if ext == "csv":
        return parse_csv(filepath, supplier)
    elif ext in ("xlsx", "xls"):
        return parse_excel(filepath, supplier)
    elif ext == "pdf":
        return parse_pdf(filepath, supplier)
    else:
        raise ValueError(f"Format non supporté : .{ext} (acceptés : csv, xlsx, xls, pdf)")
