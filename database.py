"""
database.py — Schéma PostgreSQL, chargement et contrôles d'intégrité.

Couvre les tâches S3 (schéma BDD) / S4 (BDD peuplée) :
    - Conception ERD : une table centrale `ingredients` + tables satellites
      reliées par clé étrangère (synonyms, suppliers, pricing,
      regulatory_status, functional_roles, molecular_descriptors, availability).
    - Création des tables avec contraintes (PK, FK, UNIQUE, NOT NULL).
    - Chargement du CSV propre (cosing_pubchem_clean.csv) en base.
    - Contrôles d'intégrité : doublons, colonnes clés vides, jointures.

PostgreSQL est la cible de production ; la connexion est configurable via les
variables d'environnement standard PG* (PGHOST, PGPORT, PGDATABASE, PGUSER,
PGPASSWORD), avec des valeurs par défaut pour le développement local.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# --- Schéma : modèle en étoile autour de `ingredients` ------------------------
# PostgreSQL applique les contraintes FK en continu (pas de PRAGMA à activer),
# donc une ligne satellite orpheline est rejetée dès l'insertion.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id   SERIAL PRIMARY KEY,
    inci_name       TEXT NOT NULL UNIQUE,
    cas_no          TEXT,
    ec_no           TEXT,
    smiles          TEXT,
    inchikey        TEXT,
    formula         TEXT,
    iupac_name      TEXT
);

CREATE TABLE IF NOT EXISTS synonyms (
    synonym_id      SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    synonym         TEXT NOT NULL,
    source          TEXT,                       -- COSING / INCI / PubChem
    UNIQUE (ingredient_id, synonym)
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    country         TEXT
);

CREATE TABLE IF NOT EXISTS pricing (
    pricing_id      SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    supplier_id     INTEGER REFERENCES suppliers(supplier_id),
    price_eur_per_kg REAL,                       -- prix normalisé €/kg
    currency_src    TEXT
);

CREATE TABLE IF NOT EXISTS regulatory_status (
    reg_id          SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    restriction     TEXT,                        -- ex. annexe III, limite %
    regulation_ref  TEXT                          -- ex. (CE) 1223/2009
);

CREATE TABLE IF NOT EXISTS functional_roles (
    role_id         SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    role            TEXT NOT NULL,               -- emollient, surfactant, ...
    UNIQUE (ingredient_id, role)
);

CREATE TABLE IF NOT EXISTS molecular_descriptors (
    descriptor_id   SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL UNIQUE REFERENCES ingredients(ingredient_id),
    mol_weight      REAL,
    logp            REAL,
    tpsa            REAL
);

CREATE TABLE IF NOT EXISTS availability (
    availability_id SERIAL PRIMARY KEY,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(ingredient_id),
    supplier_id     INTEGER REFERENCES suppliers(supplier_id),
    in_stock        INTEGER                      -- 0/1
);

CREATE INDEX IF NOT EXISTS idx_ingredients_cas ON ingredients(cas_no);
CREATE INDEX IF NOT EXISTS idx_synonyms_ingredient ON synonyms(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_roles_ingredient ON functional_roles(ingredient_id);
"""

_TABLES_IN_FK_ORDER = [
    "availability", "molecular_descriptors", "functional_roles",
    "regulatory_status", "pricing", "synonyms", "suppliers", "ingredients",
]


def get_database_url(dbname: Optional[str] = None) -> str:
    """URL de connexion PostgreSQL, configurable via PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD."""
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "postgres")
    db = dbname or os.environ.get("PGDATABASE", "cosmetics")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_engine(db_url: Optional[str] = None) -> Engine:
    return create_engine(db_url or get_database_url())


def create_database(db_url: Optional[str] = None) -> Connection:
    """Crée (si besoin) toutes les tables sur la base PostgreSQL. Renvoie une connexion ouverte."""
    engine = get_engine(db_url)

    # SCHEMA_SQL contient plusieurs instructions ; on l'exécute via le driver
    # psycopg2 brut (protocole simple, accepte un script multi-instructions).
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        raw.commit()
    finally:
        raw.close()

    conn = engine.connect()
    logger.info("Base créée/vérifiée : %s", engine.url.render_as_string(hide_password=True))
    return conn


def load_ingredients(conn: Connection, df: pd.DataFrame) -> int:
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
    # pandas.to_sql veut un Engine (ou une chaîne de connexion), pas une Connection SQLAlchemy.
    frame.to_sql("ingredients", conn.engine, if_exists="append", index=False)
    n = conn.execute(text("SELECT COUNT(*) FROM ingredients")).scalar()
    logger.info("ingredients chargée : %d lignes", n)
    return n


def run_integrity_checks(conn: Connection) -> dict:
    """
    Contrôles d'intégrité S4 : doublons, colonnes clés vides, jointures.

    PostgreSQL applique les FK en continu (une ligne orpheline est rejetée à
    l'insertion), donc fk_violations reste toujours à 0 par construction ici —
    le champ est conservé pour la compatibilité du rapport avec l'ancien schéma.

    Renvoie un dict de métriques (0 partout = base saine).
    """
    dup_inci = conn.execute(text(
        "SELECT COUNT(*) FROM (SELECT inci_name FROM ingredients "
        "GROUP BY inci_name HAVING COUNT(*) > 1) t"
    )).scalar()
    missing_cas = conn.execute(text(
        "SELECT COUNT(*) FROM ingredients WHERE cas_no IS NULL OR cas_no = ''"
    )).scalar()
    total = conn.execute(text("SELECT COUNT(*) FROM ingredients")).scalar()

    report = {
        "fk_violations": 0,
        "duplicate_inci": int(dup_inci),
        "ingredients_without_cas": int(missing_cas),
        "ingredients_total": int(total),
        "cas_coverage_pct": round(100 * (total - missing_cas) / total, 1) if total else 0.0,
    }
    logger.info("Contrôles d'intégrité : %s", report)
    return report


def reset_tables(conn: Connection) -> None:
    """Vide toutes les tables (schéma conservé) — pour un import reproductible sans doublons accumulés."""
    for table in _TABLES_IN_FK_ORDER:
        conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    conn.commit()


def _self_test() -> None:
    """
    Test sur une base PostgreSQL locale dédiée (cosmetics_test) : crée le schéma,
    charge la démo, vérifie l'intégrité. Nécessite un serveur PostgreSQL local
    (contrainte assouplie par rapport au ':memory:' sqlite historique).
    """
    test_db_url = get_database_url(os.environ.get("PGDATABASE_TEST", "cosmetics_test"))

    # Crée la base de test si elle n'existe pas encore (connexion à la base par défaut).
    admin_engine = get_engine(get_database_url("postgres"))
    admin_conn = admin_engine.raw_connection()
    admin_conn.set_isolation_level(0)  # autocommit, requis pour CREATE DATABASE
    try:
        with admin_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'cosmetics_test'")
            if cur.fetchone() is None:
                cur.execute("CREATE DATABASE cosmetics_test")
    finally:
        admin_conn.close()

    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {
            "inci_name": ["WATER", "GLYCERIN", "NIACINAMIDE"],
            "cas_no": ["7732-18-5", "56-81-5", "98-92-0"],
            "smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N"],
        }
    )
    conn = create_database(test_db_url)
    reset_tables(conn)

    n = load_ingredients(conn, df)
    assert n == df["inci_name"].nunique()

    # Une jointure satellite doit fonctionner sans violer les FK.
    ing_id = conn.execute(
        text("SELECT ingredient_id FROM ingredients WHERE inci_name = 'WATER'")
    ).scalar()
    conn.execute(
        text("INSERT INTO functional_roles (ingredient_id, role) VALUES (:ing_id, :role)"),
        {"ing_id": ing_id, "role": "solvent"},
    )
    conn.commit()

    report = run_integrity_checks(conn)
    assert report["fk_violations"] == 0
    assert report["duplicate_inci"] == 0
    joined = conn.execute(text(
        "SELECT i.inci_name, r.role FROM ingredients i "
        "JOIN functional_roles r ON r.ingredient_id = i.ingredient_id"
    )).fetchall()
    assert ("WATER", "solvent") in [tuple(row) for row in joined]
    conn.close()
    print(
        f"[OK] self-test database.py : {n} ingrédients en base PostgreSQL, FK OK, "
        f"jointure validée, couverture CAS {report['cas_coverage_pct']}%"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()
