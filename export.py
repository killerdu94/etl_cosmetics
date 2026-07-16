"""
src/export.py — Export du livrable CSV propre + résumé de métriques.

Tâche « Export CSV propre » (S2) : produire le fichier consolidé
`data/clean/cosing_pubchem_clean.csv` et un `export_summary.json` reproductible.

Choix techniques (cf. rapport Notion) :
    - CSV          : format de livraison universel, lisible Excel/pandas/SQL.
    - utf-8-sig    : BOM pour qu'Excel affiche correctement accents et symboles
                     grecs (α, β) sans manipulation.
    - summary JSON : métriques générées automatiquement à chaque export
                     (nb lignes/colonnes, % manquants par colonne), comparables
                     d'un run à l'autre.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CSV = "data/clean/cosing_pubchem_clean.csv"
DEFAULT_SUMMARY = "data/clean/export_summary.json"


def build_export_summary(df: pd.DataFrame, csv_path: str) -> dict:
    """Construit le dict de métriques de l'export (sérialisable en JSON)."""
    missing_pct = (df.isna().mean() * 100).round(2)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file": csv_path,
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": list(df.columns),
        "missing_pct_by_col": {c: float(missing_pct[c]) for c in df.columns},
        "duplicated_rows": int(df.duplicated().sum()),
    }


def export_clean_csv(
    df: pd.DataFrame,
    csv_path: str = DEFAULT_CSV,
    summary_path: str = DEFAULT_SUMMARY,
    encoding: str = "utf-8-sig",
) -> dict:
    """
    Exporte le DataFrame en CSV propre + écrit le résumé JSON.

    Crée les dossiers parents au besoin. Renvoie le dict de métriques pour
    permettre une vérification immédiate (assert dans les tests, log, etc.).
    """
    csv_p = Path(csv_path)
    csv_p.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(csv_p, index=False, encoding=encoding)

    summary = build_export_summary(df, str(csv_p))
    summary_p = Path(summary_path)
    summary_p.parent.mkdir(parents=True, exist_ok=True)
    summary_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "Export OK : %s (%d lignes, %d colonnes), résumé -> %s",
        csv_p, summary["n_rows"], summary["n_cols"], summary_p,
    )
    return summary


def _self_test() -> None:
    """Test hors-ligne : exporte un petit DataFrame dans un dossier temporaire."""
    import tempfile

    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = f"{tmp}/clean/cosing_pubchem_clean.csv"
        summary_path = f"{tmp}/clean/export_summary.json"
        summary = export_clean_csv(df, csv_path, summary_path)

        # Le CSV se relit avec le bon nombre de lignes et l'encodage attendu.
        reread = pd.read_csv(csv_path, encoding="utf-8-sig")
        assert len(reread) == len(df) == summary["n_rows"]
        assert summary["n_cols"] == df.shape[1]
        # Le résumé JSON est bien écrit et contient les % de manquants.
        loaded = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        assert "missing_pct_by_col" in loaded
        assert set(loaded["columns"]) == set(df.columns)
    print(
        f"[OK] self-test export.py : {summary['n_rows']} lignes exportées, "
        f"{summary['n_cols']} colonnes, résumé JSON valide"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()