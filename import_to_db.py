"""
src/import_to_db.py — Chargement du CSV propre dans la base SQLite (S4).

Couvre les tâches S4 « Import COSING → BDD », « Import PubChem & INCI → BDD » :
on crée la base (schéma de database.py) puis on insère les ingrédients et leurs
descripteurs / rôles dans les tables satellites. Idempotent : on repart d'une
base vide pour garantir la reproductibilité (pas de doublons accumulés).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from database import create_database, load_ingredients, run_integrity_checks

logger = logging.getLogger(__name__)


def import_csv_to_db(
    csv_path: str = "data/clean/cosing_pubchem_clean.csv",
    db_path: str = "data/db/cosmetics.sqlite",
) -> dict:
    """Charge le CSV propre dans la base et renvoie le rapport d'intégrité."""
    # Repartir d'une base vierge pour un import reproductible.
    Path(db_path).unlink(missing_ok=True)
    conn = create_database(db_path)

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    load_ingredients(conn, df)

    # functional_roles : on éclate la colonne 'functions' si présente.
    if "functions" in df.columns:
        _load_roles(conn, df)

    report = run_integrity_checks(conn)
    conn.close()
    return report


def _load_roles(conn, df: pd.DataFrame) -> None:
    rows = []
    name_to_id = dict(
        conn.execute("SELECT inci_name, ingredient_id FROM ingredients").fetchall()
    )
    for _, r in df.iterrows():
        ing_id = name_to_id.get(r["inci_name"])
        if ing_id is None or pd.isna(r.get("functions")):
            continue
        for role in str(r["functions"]).split(","):
            role = role.strip().lower()
            if role:
                rows.append((ing_id, role))
    conn.executemany(
        "INSERT OR IGNORE INTO functional_roles (ingredient_id, role) VALUES (?, ?)",
        rows,
    )
    conn.commit()


def _self_test() -> None:
    import tempfile

    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    df["functions"] = "emollient, solvent"
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = f"{tmp}/clean.csv"
        db_path = f"{tmp}/cosmetics.sqlite"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        report = import_csv_to_db(csv_path, db_path)
        assert report["fk_violations"] == 0
        assert report["ingredients_total"] == df["inci_name"].nunique()
    print(
        f"[OK] self-test import_to_db.py : {report['ingredients_total']} ingrédients "
        f"importés, FK={report['fk_violations']}, doublons={report['duplicate_inci']}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()