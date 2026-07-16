"""
app/search_app.py — Interface de recherche des ingrédients cosmétiques (S6).

Application Streamlit qui charge la base d'ingrédients et permet de :
    - rechercher par nom INCI,
    - filtrer par catégorie fonctionnelle et type de matière,
    - explorer la similarité moléculaire (onglet dédié, via similarity.py).

Lancement :  streamlit run app/search_app.py

Chargement des données, par ordre de priorité : base SQLite -> CSV propre ->
jeu de démonstration intégré (l'app reste fonctionnelle même sans base).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = "data/db/cosmetics.sqlite"
CSV_PATH = "data/clean/cosing_pubchem_clean.csv"


# --- Données (fonctions pures, testables sans Streamlit) ----------------------
def _demo_data() -> pd.DataFrame:
    return pd.DataFrame([
        {"inci_name": "GLYCERIN", "cas_no": "56-81-5", "smiles": "C(C(CO)O)O",
         "functional_category": "humectant", "matter_type": "polyol"},
        {"inci_name": "NIACINAMIDE", "cas_no": "98-92-0", "smiles": "C1=CC(=CN=C1)C(=O)N",
         "functional_category": "antioxydant", "matter_type": "vitamine"},
        {"inci_name": "SALICYLIC ACID", "cas_no": "69-72-7", "smiles": "C1=CC=C(C(=C1)C(=O)O)O",
         "functional_category": "conservateur", "matter_type": "acide"},
        {"inci_name": "TOCOPHEROL", "cas_no": "59-02-9", "smiles": "CC1=C(C(=C(C2=C1OC(CC2)(C)CCCC(C)CCCC(C)CCCC(C)C)C)C)O",
         "functional_category": "antioxydant", "matter_type": "vitamine"},
        {"inci_name": "PROPYLENE GLYCOL", "cas_no": "57-55-6", "smiles": "CC(CO)O",
         "functional_category": "humectant", "matter_type": "polyol"},
        {"inci_name": "CITRIC ACID", "cas_no": "77-92-9", "smiles": "C(C(=O)O)C(CC(=O)O)(C(=O)O)O",
         "functional_category": "regulateur_pH", "matter_type": "acide"},
    ])


def load_data() -> pd.DataFrame:
    """Charge les ingrédients depuis SQLite, sinon CSV, sinon démo."""
    if Path(DB_PATH).exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                return pd.read_sql_query("SELECT * FROM ingredients", conn)
        except Exception:
            pass
    if Path(CSV_PATH).exists():
        try:
            return pd.read_csv(CSV_PATH, encoding="utf-8-sig")
        except Exception:
            pass
    return _demo_data()


def filter_ingredients(df: pd.DataFrame, query: str = "",
                       categories: list[str] | None = None,
                       matters: list[str] | None = None) -> pd.DataFrame:
    """Filtre le DataFrame par texte (nom INCI) et par catégories/types."""
    out = df
    if query:
        out = out[out["inci_name"].astype(str).str.contains(query, case=False, na=False)]
    if categories and "functional_category" in out.columns:
        out = out[out["functional_category"].isin(categories)]
    if matters and "matter_type" in out.columns:
        out = out[out["matter_type"].isin(matters)]
    return out.reset_index(drop=True)


# --- Interface Streamlit ------------------------------------------------------
def main() -> None:
    import streamlit as st
    import similarity

    st.set_page_config(page_title="Cosmetic Intelligence Engine", page_icon="", layout="wide")
    st.title("Cosmetic Intelligence Engine")
    st.caption("Recherche et exploration des ingrédients cosmétiques")

    df = load_data()

    tab_search, tab_sim = st.tabs([" Recherche", "Similarité moléculaire"])

    with tab_search:
        col1, col2, col3 = st.columns([2, 1, 1])
        query = col1.text_input("Nom INCI contient…", "")
        cats = sorted(df["functional_category"].dropna().unique()) if "functional_category" in df.columns else []
        mats = sorted(df["matter_type"].dropna().unique()) if "matter_type" in df.columns else []
        sel_cats = col2.multiselect("Catégorie fonctionnelle", cats)
        sel_mats = col3.multiselect("Type de matière", mats)

        result = filter_ingredients(df, query, sel_cats, sel_mats)
        st.write(f"**{len(result)}** ingrédient(s) trouvé(s) sur {len(df)}.")
        st.dataframe(result, use_container_width=True, hide_index=True)

    with tab_sim:
        st.markdown("Trouvez les ingrédients chimiquement les plus proches (empreintes de Morgan · Tanimoto).")
        if not similarity._RDKIT_OK:
            st.warning("RDKit n'est pas installé : la similarité est indisponible.")
        else:
            names = df["inci_name"].tolist() if "inci_name" in df.columns else []
            choice = st.selectbox("Ingrédient de référence", names) if names else None
            top_n = st.slider("Nombre de voisins", 1, 10, 5)
            if choice:
                smiles = str(df.loc[df["inci_name"] == choice, "smiles"].iloc[0])
                index = similarity.build_fingerprint_index(df)
                neighbours = similarity.find_similar(smiles, index, top_n=top_n + 1)
                neighbours = neighbours[neighbours["inci_name"] != choice].head(top_n)
                st.dataframe(neighbours, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()