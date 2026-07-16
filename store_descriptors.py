"""
store_descriptors.py — Calcul, stockage en base et couverture des descripteurs (S5).

S'appuie sur descriptors.py (RDKit) et database.py (schéma PostgreSQL) :
    1. calcule MW / logP / TPSA / HBD / HBA pour chaque ingrédient (via son SMILES)
    2. stocke le résultat dans la table `molecular_descriptors` (relation 1-1)
    3. produit un rapport de couverture : combien d'ingrédients ont des descripteurs
       valides, combien de SMILES manquants / invalides.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from descriptors import compute_descriptors

logger = logging.getLogger(__name__)


def store_descriptors(conn: Connection) -> int:
    """
    Calcule et insère les descripteurs pour tous les ingrédients ayant un SMILES.

    Renvoie le nombre de lignes insérées dans `molecular_descriptors`.
    """
    rows = conn.execute(
        text("SELECT ingredient_id, smiles FROM ingredients WHERE smiles IS NOT NULL")
    ).fetchall()

    inserted = 0
    for ingredient_id, smiles in rows:
        d = compute_descriptors(smiles)
        if d["mol_weight"] is None:  # SMILES invalide -> on n'insère pas
            continue
        conn.execute(
            text(
                "INSERT INTO molecular_descriptors (ingredient_id, mol_weight, logp, tpsa) "
                "VALUES (:ing_id, :mw, :logp, :tpsa) "
                "ON CONFLICT (ingredient_id) DO UPDATE SET "
                "mol_weight = EXCLUDED.mol_weight, logp = EXCLUDED.logp, tpsa = EXCLUDED.tpsa"
            ),
            {"ing_id": ingredient_id, "mw": d["mol_weight"], "logp": d["logp"], "tpsa": d["tpsa"]},
        )
        inserted += 1
    conn.commit()
    logger.info("Descripteurs stockés : %d ingrédients", inserted)
    return inserted


def coverage_report(conn: Connection) -> dict:
    """Rapport de couverture des descripteurs sur l'ensemble des ingrédients."""
    total = conn.execute(text("SELECT COUNT(*) FROM ingredients")).scalar()
    with_smiles = conn.execute(
        text("SELECT COUNT(*) FROM ingredients WHERE smiles IS NOT NULL AND smiles != ''")
    ).scalar()
    with_desc = conn.execute(
        text("SELECT COUNT(*) FROM molecular_descriptors")
    ).scalar()

    report = {
        "ingredients_total": int(total),
        "with_smiles": int(with_smiles),
        "with_descriptors": int(with_desc),
        "descriptor_coverage_pct": round(100 * with_desc / total, 1) if total else 0.0,
        "invalid_or_missing_smiles": int(total - with_desc),
    }
    logger.info("Couverture descripteurs : %s", report)
    return report


def _self_test() -> None:
    import os

    from database import create_database, get_database_url, load_ingredients, reset_tables
    from descriptors import _RDKIT_OK

    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    test_db_url = get_database_url(os.environ.get("PGDATABASE_TEST", "cosmetics_test"))
    conn = create_database(test_db_url)
    reset_tables(conn)
    load_ingredients(conn, df)

    n = store_descriptors(conn)
    report = coverage_report(conn)
    assert report["with_descriptors"] == n
    if _RDKIT_OK:
        # Avec RDKit, les 3 SMILES valides donnent des descripteurs.
        assert n == 3 and report["descriptor_coverage_pct"] > 0
        msg = f"{n} descripteurs stockés, couverture {report['descriptor_coverage_pct']}%"
    else:
        # Sans RDKit (ex. machine sans la lib), dégradation propre : 0 descripteur.
        assert n == 0
        msg = "RDKit absent (mode dégradé) : 0 descripteur, pas de crash"
    conn.close()
    print(f"[OK] self-test store_descriptors.py : {msg}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()
