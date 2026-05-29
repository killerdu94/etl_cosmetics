"""
pipeline.py — Pipeline ETL Cosmetics Intelligence Engine
=========================================================
Enchaîne toutes les étapes S1 + S2 en une seule commande :
  1. Téléchargement et nettoyage COSING
  2. Enrichissement SMILES via API PubChem (CAS → SMILES)
  3. Parsing des catalogues fournisseurs
  4. Harmonisation des noms et CAS entre sources
  5. Déduplication hybride (exacte + fuzzy)
  6. Normalisation des prix en EUR/kg HT
  7. Export CSV propre + résumé JSON

Usage :
    python pipeline.py                        # pipeline complet
    python pipeline.py --no-download          # skip téléchargement COSING
    python pipeline.py --max-smiles 200       # limite SMILES à 200 ingrédients
    python pipeline.py --config config.yaml
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from cosing import run_cosing_etl, CLEAN_PATH as COSING_CLEAN_PATH
from pubchem import enrich_with_pubchem, save_enriched, ENRICHED_PATH
from harmonization import harmonize
from deduplication import deduplicate
from price_normalization import normalize_prices
from supplier_parser import parse_supplier_catalogue

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_file: str = "pipeline.log") -> None:
    """Configure le logging : console (INFO) + fichier (DEBUG)."""
    fmt     = "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.DEBUG,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Console : INFO et au-dessus seulement
    logging.getLogger().handlers[1].setLevel(logging.INFO)


logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "paths": {
        "cosing_clean":   "data/clean/cosing_clean.csv",
        "pubchem_out":    "data/clean/cosing_pubchem.csv",
        "output_csv":     "data/clean/cosing_pubchem_clean.csv",
        "output_summary": "data/clean/export_summary.json",
        "suppliers_dir":  "data/raw/suppliers/",
        "log_file":       "pipeline.log",
    },
    "pubchem": {
        "max_ingredients": None,   # None = tous les ingrédients avec CAS
        "delay":           0.3,    # secondes entre requêtes API
    },
    "dedup": {
        "fuzzy_threshold": 0.95,
    },
    "exchange_rates": {
        "EUR": 1.0,
        "USD": 0.922,
        "GBP": 1.168,
        "CHF": 1.013,
    },
}


def load_config(config_path: str | None = None) -> dict:
    """Charge la configuration depuis un fichier YAML ou utilise les défauts.

    Args:
        config_path: Chemin vers config.yaml (optionnel).

    Returns:
        Dictionnaire de configuration fusionné avec les défauts.
    """
    if config_path and Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_CONFIG.items()}
        for section, values in user_cfg.items():
            if section in cfg and isinstance(cfg[section], dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
        logger.info("Configuration chargée depuis %s", config_path)
    else:
        cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_CONFIG.items()}
        logger.info("Configuration par défaut utilisée")
    return cfg


# ---------------------------------------------------------------------------
# Étapes du pipeline
# ---------------------------------------------------------------------------

def step_cosing(download: bool, config: dict) -> pd.DataFrame:
    """Étape 1 — Télécharge et nettoie la base COSING depuis l'UE."""
    logger.info("══ Étape 1 : COSING ══")
    df = run_cosing_etl(download=download)
    logger.info("COSING prêt : %d ingrédients", len(df))
    return df


def step_smiles(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Étape 2 — Enrichit chaque ingrédient avec son SMILES via PubChem."""
    logger.info("══ Étape 2 : Enrichissement SMILES (PubChem) ══")
    pubchem_cfg = config["pubchem"]
    df_enriched = enrich_with_pubchem(
        df,
        cas_col="cas",
        max_ingredients=pubchem_cfg.get("max_ingredients"),
        delay=pubchem_cfg.get("delay", 0.3),
    )
    save_enriched(df_enriched, config["paths"]["pubchem_out"])
    return df_enriched


def step_suppliers(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Étape 3 — Parse et intègre les catalogues fournisseurs."""
    logger.info("══ Étape 3 : Catalogues fournisseurs ══")
    suppliers_dir = Path(config["paths"]["suppliers_dir"])

    if not suppliers_dir.exists():
        logger.info("Dossier fournisseurs absent (%s) — étape sautée", suppliers_dir)
        return df

    frames = [df]
    for filepath in suppliers_dir.iterdir():
        if filepath.suffix.lower() in (".csv", ".xlsx", ".xls", ".pdf"):
            try:
                df_sup = parse_supplier_catalogue(str(filepath), filepath.stem)
                df_sup["source"] = "supplier"
                frames.append(df_sup)
                logger.info("Fournisseur '%s' intégré : %d entrées", filepath.stem, len(df_sup))
            except Exception as e:
                logger.error("Erreur fournisseur %s : %s", filepath.name, e)

    if len(frames) > 1:
        df = pd.concat(frames, ignore_index=True)
        logger.info("Consolidation : %d entrées au total", len(df))

    return df


def step_harmonize(df: pd.DataFrame) -> pd.DataFrame:
    """Étape 4 — Harmonise les noms et CAS entre toutes les sources."""
    logger.info("══ Étape 4 : Harmonisation ══")
    return harmonize(df)


def step_deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Étape 5 — Déduplication hybride (exacte sur CAS + fuzzy sur noms)."""
    logger.info("══ Étape 5 : Déduplication ══")
    return deduplicate(df)


def step_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Étape 6 — Normalise les prix fournisseurs en EUR/kg HT."""
    logger.info("══ Étape 6 : Normalisation des prix ══")
    if "price_raw" not in df.columns:
        logger.info("Aucun prix à normaliser — étape sautée")
        return df
    return normalize_prices(df)


def step_export(df: pd.DataFrame, config: dict, elapsed: float) -> None:
    """Étape 7 — Exporte le CSV final et le résumé JSON des métriques."""
    logger.info("══ Étape 7 : Export ══")

    output_csv = config["paths"]["output_csv"]
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    logger.info("CSV exporté : %s (%d lignes, %d colonnes)", output_csv, len(df), len(df.columns))

    smiles_n = int(df["smiles"].notna().sum()) if "smiles" in df.columns else 0
    summary = {
        "export_date":    datetime.now().isoformat(),
        "pipeline_time_s": round(elapsed, 2),
        "rows":            len(df),
        "columns":         len(df.columns),
        "column_names":    df.columns.tolist(),
        "smiles_count":    smiles_n,
        "smiles_pct":      round(smiles_n / len(df) * 100, 1) if len(df) else 0,
        "sources":         df["source"].value_counts().to_dict() if "source" in df.columns else {},
        "null_pct":        {col: round(df[col].isna().mean() * 100, 2) for col in df.columns},
    }

    summary_path = config["paths"]["output_summary"]
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(
        "Résumé : %s | SMILES: %d (%.1f%%)",
        summary_path, smiles_n, summary["smiles_pct"],
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def run(
    config_path:  str | None = None,
    download:     bool = True,
    max_smiles:   int | None = None,
) -> None:
    """Lance le pipeline ETL complet.

    Args:
        config_path: Chemin vers config.yaml (optionnel).
        download:    Si False, réutilise le fichier COSING existant.
        max_smiles:  Nombre max d'ingrédients à enrichir en SMILES (None = tous).
    """
    setup_logging()
    t0 = time.time()

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║  Cosmetics Intelligence Engine — Pipeline ETL ║")
    logger.info("║  %s                         ║", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("╚══════════════════════════════════════════════╝")

    config = load_config(config_path)

    if max_smiles is not None:
        config["pubchem"]["max_ingredients"] = max_smiles

    df = step_cosing(download, config)
    df["source"] = "COSING"
    df = step_smiles(df, config)
    df = step_suppliers(df, config)
    df = step_harmonize(df)
    df = step_deduplicate(df)
    df = step_prices(df)

    elapsed = time.time() - t0
    step_export(df, config, elapsed)

    smiles_final = int(df["smiles"].notna().sum()) if "smiles" in df.columns else 0
    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║  Pipeline terminé en %.1fs", elapsed)
    logger.info("║  Ingrédients finaux : %d", len(df))
    logger.info("║  SMILES enrichis    : %d (%.1f%%)", smiles_final, smiles_final / len(df) * 100 if len(df) else 0)
    logger.info("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline ETL Cosmetics Intelligence Engine")
    parser.add_argument("--config",       default="config.yaml",  help="Chemin vers config.yaml")
    parser.add_argument("--no-download",  action="store_true",    help="Réutilise le fichier COSING existant")
    parser.add_argument("--max-smiles",   type=int, default=None, help="Nombre max d'ingrédients à enrichir en SMILES")
    args = parser.parse_args()

    run(
        config_path=args.config,
        download=not args.no_download,
        max_smiles=args.max_smiles,
    )
