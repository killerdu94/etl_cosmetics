"""
cosing.py — Téléchargement, parsing et nettoyage de la base COSING (EU)
========================================================================
Source : Open Beauty Facts / OpenFoodFacts (miroir officiel COSING v2)
URL    : https://raw.githubusercontent.com/openfoodfacts/openbeautyfacts/refs/heads/develop/cosing/COSING_Ingredients-Fragrance.Inventory_v2.csv

Pipeline :
  1. Téléchargement du CSV depuis GitHub (miroir public du fichier officiel EU)
  2. Parsing avec détection automatique des lignes parasites d'en-tête
  3. Nettoyage et normalisation des colonnes clés
  4. Sauvegarde en CSV propre

Usage :
    python cosing.py                   # télécharge + nettoie
    python cosing.py --no-download     # utilise le fichier brut existant
"""

import os
import sys
import argparse
import logging

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COSING_CSV_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/openbeautyfacts"
    "/refs/heads/develop/cosing/COSING_Ingredients-Fragrance.Inventory_v2.csv"
)
RAW_PATH   = "data/raw/cosing_raw.csv"
CLEAN_PATH = "data/clean/cosing_clean.csv"

# Mapping colonnes COSING v2 → noms canoniques
COLUMN_MAP = {
    "COSING Ref No":               "ref_no",
    "INCI name":                   "inci_name",
    "INN name":                    "inn_name",
    "Ph. Eur. Name":               "ph_eur_name",
    "CAS No":                      "cas",
    "EINECS/ELINCS No":            "ec",
    "Chem/IUPAC Name / Description": "description",
    "Restriction":                 "restriction",
    "Function":                    "function",
    "Update Date":                 "update_date",
}


# ---------------------------------------------------------------------------
# Étape 1 — Téléchargement
# ---------------------------------------------------------------------------

def download_cosing(url: str = COSING_CSV_URL, dest: str = RAW_PATH) -> str:
    """Télécharge le fichier COSING brut.

    Args:
        url:  URL du fichier CSV.
        dest: Chemin de destination local.

    Returns:
        Chemin du fichier téléchargé.

    Raises:
        requests.HTTPError: Si le téléchargement échoue.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    logger.info("Téléchargement COSING depuis : %s", url)

    response = requests.get(url, timeout=60, stream=True)
    response.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    size_kb = os.path.getsize(dest) // 1024
    logger.info("Téléchargement terminé : %s (%d Ko)", dest, size_kb)
    return dest


# ---------------------------------------------------------------------------
# Étape 2 — Parsing
# ---------------------------------------------------------------------------

def parse_cosing(filepath: str = RAW_PATH) -> pd.DataFrame:
    """Parse le CSV COSING brut.

    Le fichier COSING v2 contient plusieurs lignes parasites en en-tête
    (sep=, date de création, titre) avant l'en-tête réel des colonnes.
    Cette fonction détecte automatiquement la ligne d'en-tête.

    Args:
        filepath: Chemin vers le fichier CSV brut.

    Returns:
        DataFrame brut avec toutes les colonnes d'origine.

    Raises:
        FileNotFoundError: Si le fichier n'existe pas.
        ValueError: Si l'en-tête des colonnes ne peut pas être trouvé.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Fichier COSING introuvable : {filepath}\n"
            "Lancez d'abord : python cosing.py"
        )

    logger.info("Parsing : %s", filepath)

    # Détecte la ligne contenant l'en-tête réel (contient "INCI name")
    header_line = None
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if "INCI name" in line or "INCI Name" in line:
                header_line = i
                break

    if header_line is None:
        raise ValueError(
            f"Impossible de trouver l'en-tête dans {filepath}. "
            "Vérifiez que le fichier est bien le CSV COSING."
        )

    logger.info("En-tête trouvé à la ligne %d", header_line)

    # Lit le CSV en sautant les lignes parasites avant l'en-tête
    df = pd.read_csv(
        filepath,
        skiprows=header_line,
        encoding="utf-8",
        sep=",",
        low_memory=False,
        on_bad_lines="skip",
    )

    logger.info("Parsing réussi : %d lignes, %d colonnes", len(df), len(df.columns))
    return df


# ---------------------------------------------------------------------------
# Étape 3 — Nettoyage
# ---------------------------------------------------------------------------

def clean_cosing(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoie et normalise le DataFrame COSING brut.

    Opérations :
    - Sélection et renommage des colonnes canoniques
    - Suppression des espaces parasites
    - Normalisation INCI en majuscules
    - Nettoyage des numéros CAS et EC
    - Suppression des doublons sur inci_name
    - Suppression des lignes sans nom INCI

    Args:
        df: DataFrame brut issu de parse_cosing().

    Returns:
        DataFrame nettoyé et normalisé.
    """
    logger.info("Nettoyage : %d lignes en entrée", len(df))

    # Sélectionner les colonnes disponibles
    cols_present = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
    if not cols_present:
        raise ValueError(
            f"Aucune colonne COSING reconnue. Colonnes trouvées : {list(df.columns)}"
        )

    df = df[list(cols_present.keys())].rename(columns=cols_present).copy()

    # Nettoyage des chaînes
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": None, "": None, "-": None})

    # Normalisation INCI en majuscules
    if "inci_name" in df.columns:
        df["inci_name"] = df["inci_name"].str.upper()

    # Nettoyage CAS : suppression espaces internes et tirets isolés
    if "cas" in df.columns:
        df["cas"] = df["cas"].str.replace(r"\s+", "", regex=True)
        df.loc[df["cas"].isin(["None", "-", ""]), "cas"] = None

    # Nettoyage EC
    if "ec" in df.columns:
        df["ec"] = df["ec"].str.replace(r"\s+", "", regex=True)
        df.loc[df["ec"].isin(["None", "-", ""]), "ec"] = None

    # Suppression des lignes sans nom INCI
    before = len(df)
    df = df[df["inci_name"].notna() & (df["inci_name"] != "NAN")].copy()
    logger.info("Lignes sans INCI supprimées : %d", before - len(df))

    # Déduplication sur inci_name
    before = len(df)
    df = df.drop_duplicates(subset=["inci_name"], keep="first")
    logger.info("Doublons supprimés : %d", before - len(df))

    df = df.reset_index(drop=True)
    logger.info("Nettoyage terminé : %d ingrédients propres", len(df))
    return df


# ---------------------------------------------------------------------------
# Étape 4 — Sauvegarde
# ---------------------------------------------------------------------------

def save_clean(df: pd.DataFrame, dest: str = CLEAN_PATH) -> str:
    """Sauvegarde le DataFrame nettoyé en CSV (utf-8-sig pour Excel).

    Args:
        df:   DataFrame nettoyé.
        dest: Chemin de destination.

    Returns:
        Chemin du fichier sauvegardé.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    df.to_csv(dest, index=False, encoding="utf-8-sig")
    logger.info("Sauvegardé : %s (%d ingrédients)", dest, len(df))
    return dest


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------

def run_cosing_etl(download: bool = True) -> pd.DataFrame:
    """Lance le pipeline COSING complet.

    Args:
        download: Si True, télécharge le fichier même s'il existe déjà.

    Returns:
        DataFrame COSING nettoyé.
    """
    if download or not os.path.exists(RAW_PATH):
        download_cosing()
    df_raw   = parse_cosing()
    df_clean = clean_cosing(df_raw)
    save_clean(df_clean)
    return df_clean


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="ETL COSING — Téléchargement et nettoyage")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Utilise le fichier brut existant sans retélécharger",
    )
    args = parser.parse_args()

    df = run_cosing_etl(download=not args.no_download)

    print(f"\n{'='*55}")
    print(f"  COSING ETL terminé")
    print(f"  Ingrédients : {len(df):,}")
    print(f"  Avec CAS    : {df['cas'].notna().sum():,} ({df['cas'].notna().mean()*100:.1f}%)")
    if "ec" in df.columns:
        print(f"  Avec EC     : {df['ec'].notna().sum():,}")
    if "restriction" in df.columns:
        print(f"  Restreints  : {df['restriction'].notna().sum():,}")
    print(f"  Fichier     : {CLEAN_PATH}")
    print(f"{'='*55}\n")
    print(df[["inci_name", "cas", "function"]].head(10).to_string(index=False))