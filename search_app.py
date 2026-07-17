"""
search_app.py — Interface de recherche des ingrédients cosmétiques (S6).

Application Streamlit qui charge la base d'ingrédients et permet de :
    - rechercher par nom INCI,
    - filtrer par catégorie fonctionnelle, type de matière et fonction COSING,
    - explorer la similarité moléculaire (onglet dédié, via similarity.py).

Lancement :  streamlit run search_app.py

Chargement des données, par ordre de priorité : PostgreSQL -> CSV propre ->
jeu de démonstration intégré (l'app reste fonctionnelle même sans base).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CSV_PATH = "data/clean/cosing_pubchem_clean.csv"


# --- Données (fonctions pures, testables sans Streamlit) ----------------------
def _demo_data() -> pd.DataFrame:
    return pd.DataFrame([
        {"inci_name": "GLYCERIN", "cas_no": "56-81-5", "smiles": "C(C(CO)O)O",
         "functional_category": "humectant", "matter_type": "polyol", "function": "humectant, solvent",
         "iupac_name": "propane-1,2,3-triol"},
        {"inci_name": "NIACINAMIDE", "cas_no": "98-92-0", "smiles": "C1=CC(=CN=C1)C(=O)N",
         "functional_category": "antioxydant", "matter_type": "vitamine", "function": "antioxidant, skin conditioning",
         "iupac_name": "pyridine-3-carboxamide"},
        {"inci_name": "SALICYLIC ACID", "cas_no": "69-72-7", "smiles": "C1=CC=C(C(=C1)C(=O)O)O",
         "functional_category": "conservateur", "matter_type": "acide", "function": "preservative, keratolytic",
         "iupac_name": "2-hydroxybenzoic acid"},
        {"inci_name": "TOCOPHEROL", "cas_no": "59-02-9", "smiles": "CC1=C(C(=C(C2=C1OC(CC2)(C)CCCC(C)CCCC(C)CCCC(C)C)C)C)O",
         "functional_category": "antioxydant", "matter_type": "vitamine", "function": "antioxidant",
         "iupac_name": "2,5,7,8-tetramethyl-2-(4,8,12-trimethyltridecyl)chroman-6-ol"},
        {"inci_name": "PROPYLENE GLYCOL", "cas_no": "57-55-6", "smiles": "CC(CO)O",
         "functional_category": "humectant", "matter_type": "polyol", "function": "humectant, solvent",
         "iupac_name": "propane-1,2-diol"},
        {"inci_name": "CITRIC ACID", "cas_no": "77-92-9", "smiles": "C(C(=O)O)C(CC(=O)O)(C(=O)O)O",
         "functional_category": "regulateur_pH", "matter_type": "acide", "function": "buffering, chelating",
         "iupac_name": "2-hydroxypropane-1,2,3-tricarboxylic acid"},
    ])


def _load_from_postgres() -> pd.DataFrame | None:
    """Charge les ingrédients depuis PostgreSQL (avec leurs fonctions agrégées), ou None si indisponible."""
    try:
        from sqlalchemy import text

        from database import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            query = text(
                "SELECT i.*, "
                "       STRING_AGG(DISTINCT r.role, ', ') AS function "
                "FROM ingredients i "
                "LEFT JOIN functional_roles r ON r.ingredient_id = i.ingredient_id "
                "GROUP BY i.ingredient_id"
            )
            return pd.read_sql_query(query, conn)
    except Exception:
        return None


def load_data() -> pd.DataFrame:
    """Charge les ingrédients depuis PostgreSQL, sinon CSV, sinon démo."""
    df = _load_from_postgres()
    if df is not None and not df.empty:
        return df
    if Path(CSV_PATH).exists():
        try:
            return pd.read_csv(CSV_PATH, encoding="utf-8-sig")
        except Exception:
            pass
    return _demo_data()


def _split_functions(value: object) -> list[str]:
    """Éclate une chaîne de fonctions séparées par virgule en tokens propres (minuscules)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [f.strip().lower() for f in str(value).split(",") if f.strip()]


def list_functions(df: pd.DataFrame, function_col: str = "function") -> list[str]:
    """Liste triée de toutes les fonctions disponibles (tokens uniques) dans le DataFrame."""
    if function_col not in df.columns:
        return []
    tokens: set[str] = set()
    for value in df[function_col]:
        tokens.update(_split_functions(value))
    return sorted(tokens)


def filter_ingredients(df: pd.DataFrame, query: str = "",
                       categories: list[str] | None = None,
                       matters: list[str] | None = None,
                       functions: list[str] | None = None,
                       function_col: str = "function") -> pd.DataFrame:
    """Filtre le DataFrame par texte (nom INCI et/ou nom scientifique IUPAC), catégorie/type, et fonction COSING."""
    out = df
    if query:
        name_match = out["inci_name"].astype(str).str.contains(query, case=False, na=False)
        if "iupac_name" in out.columns:
            name_match |= out["iupac_name"].astype(str).str.contains(query, case=False, na=False)
        out = out[name_match]
    if categories and "functional_category" in out.columns:
        out = out[out["functional_category"].isin(categories)]
    if matters and "matter_type" in out.columns:
        out = out[out["matter_type"].isin(matters)]
    if functions and function_col in out.columns:
        wanted = {f.lower() for f in functions}
        out = out[out[function_col].apply(lambda v: bool(wanted & set(_split_functions(v))))]
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
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        query = col1.text_input("Nom ou nom scientifique contient…", "")
        cats = sorted(df["functional_category"].dropna().unique()) if "functional_category" in df.columns else []
        mats = sorted(df["matter_type"].dropna().unique()) if "matter_type" in df.columns else []
        funcs = list_functions(df)
        sel_cats = col2.multiselect("Catégorie fonctionnelle", cats)
        sel_mats = col3.multiselect("Type de matière", mats)
        sel_funcs = col4.multiselect("Fonction", funcs)

        result = filter_ingredients(df, query, sel_cats, sel_mats, sel_funcs)
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
