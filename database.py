"""
src/database.py — Schéma SQLite, chargement et contrôles d'intégrité.

Couvre les tâches S3 (schéma BDD) / S4 (BDD peuplée) :
    - Conception ERD : une table centrale `ingredients` + tables satellites
      reliées par clé étrangère (synonyms, suppliers, pricing,
      regulatory_status, functional_roles, molecular_descriptors, availability).
    - Création des tables avec contraintes (PK, FK, UNIQUE, NOT NULL).
    - Chargement du CSV propre (cosing_pubchem_clean.csv) en base.
    - Contrôles d'intégrité : intégrité référentielle, doublons, jointures.

SQLite est choisi pour le stage (zéro installation, un seul fichier, requêtes
SQL immédiates). Postgres reste la cible de production ; le schéma est volontairement
portable (types simples, FK explicites).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# --- Schéma : modèle en étoile autour de `ingredients` ------------------------
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id   INTEGER PRIMARY KEY,
    inci_name       TEXT NOT NULL UNIQUE,
    cas_no          TEXT,
    ec_no           TEXT,
    smiles          TEXT,
    inchikey        TEXT,
    formula         TEXT,
    iupac_name      TEXT
);

CREATE TABLE IF NOT EXISTS synonyms (
    synonym_id      INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL,
    synonym         TEXT NOT NULL,
    source          TEXT,                       -- COSING / INCI / PubChem
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id),
    UNIQUE (ingredient_id, synonym)
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    country         TEXT
);

CREATE TABLE IF NOT EXISTS pricing (
    pricing_id      INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL,
    supplier_id     INTEGER,
    price_eur_per_kg REAL,                       -- prix normalisé €/kg
    currency_src    TEXT,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id),
    FOREIGN KEY (supplier_id)   REFERENCES suppliers(supplier_id)
);

CREATE TABLE IF NOT EXISTS regulatory_status (
    reg_id          INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL,
    restriction     TEXT,                        -- ex. annexe III, limite %
    regulation_ref  TEXT,                        -- ex. (CE) 1223/2009
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
);

CREATE TABLE IF NOT EXISTS functional_roles (
    role_id         INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL,
    role            TEXT NOT NULL,               -- emollient, surfactant, ...
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id),
    UNIQUE (ingredient_id, role)
);

CREATE TABLE IF NOT EXISTS molecular_descriptors (
    descriptor_id   INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL UNIQUE,
    mol_weight      REAL,
    logp            REAL,
    tpsa            REAL,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
);

CREATE TABLE IF NOT EXISTS availability (
    availability_id INTEGER PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL,
    supplier_id     INTEGER,
    in_stock        INTEGER,                     -- 0/1
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id),
    FOREIGN KEY (supplier_id)   REFERENCES suppliers(supplier_id)
);

CREATE INDEX IF NOT EXISTS idx_ingredients_cas ON ingredients(cas_no);
CREATE INDEX IF NOT EXISTS idx_synonyms_ingredient ON synonyms(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_roles_ingredient ON functional_roles(ingredient_id);
"""


def create_database(db_path: str = "data/db/cosmetics.sqlite") -> sqlite3.Connection:
    """Crée le fichier SQLite et toutes les tables. Renvoie la connexion ouverte."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    logger.info("Base créée : %s", db_path)
    return conn


def load_ingredients(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """
    Charge la table `ingredients` depuis le CSV propre. Renvoie le nb de lignes.

    Les colonnes manquantes dans le DataFrame sont tolérées (remplies à NULL),
    pour que le chargement fonctionne avec un export partiel.
    """
    cols = ["inci_name", "cas_no", "ec_no", "smiles", "inchikey", "formula", "iupac_name"]
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = None
    frame = frame[cols].drop_duplicates(subset="inci_name")
    frame.to_sql("ingredients", conn, if_exists="append", index=False)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    logger.info("ingredients chargée : %d lignes", n)
    return n


def run_integrity_checks(conn: sqlite3.Connection) -> dict:
    """
    Contrôles d'intégrité S4 : FK orphelines, doublons, colonnes clés vides.

    Renvoie un dict de métriques (0 partout = base saine).
    """
    cur = conn.cursor()
    fk_violations = cur.execute("PRAGMA foreign_key_check;").fetchall()
    dup_inci = cur.execute(
        "SELECT COUNT(*) FROM (SELECT inci_name FROM ingredients "
        "GROUP BY inci_name HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    missing_cas = cur.execute(
        "SELECT COUNT(*) FROM ingredients WHERE cas_no IS NULL OR cas_no = ''"
    ).fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]

    report = {
        "fk_violations": len(fk_violations),
        "duplicate_inci": int(dup_inci),
        "ingredients_without_cas": int(missing_cas),
        "ingredients_total": int(total),
        "cas_coverage_pct": round(100 * (total - missing_cas) / total, 1) if total else 0.0,
    }
    logger.info("Contrôles d'intégrité : %s", report)
    return report


def _self_test() -> None:
    """Test hors-ligne : crée la base en mémoire, charge la démo, vérifie l'intégrité."""
    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)

    n = load_ingredients(conn, df)
    assert n == df["inci_name"].nunique()

    # Une jointure satellite doit fonctionner sans violer les FK.
    ing_id = conn.execute(
        "SELECT ingredient_id FROM ingredients WHERE inci_name = 'WATER'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO functional_roles (ingredient_id, role) VALUES (?, ?)",
        (ing_id, "solvent"),
    )
    conn.commit()

    report = run_integrity_checks(conn)
    assert report["fk_violations"] == 0
    assert report["duplicate_inci"] == 0
    joined = conn.execute(
        "SELECT i.inci_name, r.role FROM ingredients i "
        "JOIN functional_roles r ON r.ingredient_id = i.ingredient_id"
    ).fetchall()
    assert ("WATER", "solvent") in joined
    conn.close()
    print(
        f"[OK] self-test database.py : {n} ingrédients en base, FK OK, "
        f"jointure validée, couverture CAS {report['cas_coverage_pct']}%"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()
