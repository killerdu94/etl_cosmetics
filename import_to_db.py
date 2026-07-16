"""
import_to_db.py — Chargement du CSV propre dans la base PostgreSQL (S4).

Couvre les tâches S4 « Import COSING → BDD », « Import PubChem & INCI → BDD » :
on crée la base (schéma de database.py) puis on insère les ingrédients et leurs
descripteurs / rôles dans les tables satellites. Idempotent : les tables sont
vidées avant chargement pour garantir la reproductibilité (pas de doublons
accumulés d'un run à l'autre).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from database import create_database, load_ingredients, reset_tables, run_integrity_checks

logger = logging.getLogger(__name__)


def import_csv_to_db(
    csv_path: str = "data/clean/cosing_pubchem_clean.csv",
    db_url: Optional[str] = None,
) -> dict:
    """Charge le CSV propre dans la base et renvoie le rapport d'intégrité."""
    conn = create_database(db_url)
    reset_tables(conn)  # repartir d'une base vide pour un import reproductible

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    load_ingredients(conn, df)

    # functional_roles : on éclate la colonne 'function' (nom réel côté COSING) si présente.
    if "function" in df.columns:
        _load_roles(conn, df)

    report = run_integrity_checks(conn)
    conn.close()
    return report


def _load_roles(conn: Connection, df: pd.DataFrame) -> None:
    rows = []
    name_to_id = dict(
        conn.execute(text("SELECT inci_name, ingredient_id FROM ingredients")).fetchall()
    )
    for _, r in df.iterrows():
        ing_id = name_to_id.get(r["inci_name"])
        if ing_id is None or pd.isna(r.get("function")):
            continue
        for role in str(r["function"]).split(","):
            role = role.strip().lower()
            if role:
                rows.append({"ing_id": ing_id, "role": role})
    if rows:
        conn.execute(
            text(
                "INSERT INTO functional_roles (ingredient_id, role) VALUES (:ing_id, :role) "
                "ON CONFLICT (ingredient_id, role) DO NOTHING"
            ),
            rows,
        )
    conn.commit()


def _self_test() -> None:
    import os
    import tempfile

    from database import get_database_url

    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    df["function"] = "emollient, solvent"
    test_db_url = get_database_url(os.environ.get("PGDATABASE_TEST", "cosmetics_test"))
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = f"{tmp}/clean.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        report = import_csv_to_db(csv_path, test_db_url)
        assert report["fk_violations"] == 0
        assert report["ingredients_total"] == df["inci_name"].nunique()
    print(
        f"[OK] self-test import_to_db.py : {report['ingredients_total']} ingrédients "
        f"importés, FK={report['fk_violations']}, doublons={report['duplicate_inci']}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()
