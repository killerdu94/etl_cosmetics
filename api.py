"""
api.py — API FastAPI : recherche d'ingrédients + similarité moléculaire (S6 bis).

Expose en JSON la même logique métier que search_app.py (Streamlit) — load_data,
filter_ingredients — et similarity.py (empreintes de Morgan + Tanimoto), pour une
interface React qui coexiste avec l'app Streamlit existante. Aucune duplication :
les deux interfaces consomment les mêmes fonctions pures.

Lancement :  uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import search_app
import similarity

app = FastAPI(title="Cosmetic Intelligence Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev local uniquement
    allow_methods=["*"],
    allow_headers=["*"],
)

_df_cache: Optional[pd.DataFrame] = None


def _get_df() -> pd.DataFrame:
    """Charge les ingrédients une seule fois (SQLite -> CSV -> démo), mis en cache."""
    global _df_cache
    if _df_cache is None:
        _df_cache = search_app.load_data()
    return _df_cache


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "rdkit_available": similarity._RDKIT_OK}


@app.get("/api/filters")
def get_filters() -> dict:
    """Valeurs disponibles pour les menus déroulants (catégorie, type de matière)."""
    df = _get_df()
    cats = sorted(df["functional_category"].dropna().unique().tolist()) if "functional_category" in df.columns else []
    mats = sorted(df["matter_type"].dropna().unique().tolist()) if "matter_type" in df.columns else []
    names = sorted(df["inci_name"].dropna().unique().tolist()) if "inci_name" in df.columns else []
    return {"categories": cats, "matters": mats, "inci_names": names}


@app.get("/api/ingredients")
def get_ingredients(query: str = "", category: str = "", matter: str = "") -> dict:
    """Recherche/filtre les ingrédients par nom INCI, catégorie fonctionnelle, type de matière."""
    df = _get_df()
    cats = [category] if category else None
    mats = [matter] if matter else None
    result = search_app.filter_ingredients(df, query, cats, mats)
    return {
        "total": int(len(df)),
        "count": int(len(result)),
        "items": result.to_dict(orient="records"),
    }


@app.get("/api/similarity")
def get_similarity(inci_name: str, top_n: int = 5) -> dict:
    """Voisins les plus proches (Tanimoto) d'un ingrédient de référence donné par son nom INCI."""
    df = _get_df()
    if not similarity._RDKIT_OK:
        return {"rdkit_available": False, "neighbours": []}
    if "inci_name" not in df.columns or inci_name not in df["inci_name"].values:
        return {"rdkit_available": True, "error": "ingrédient introuvable", "neighbours": []}

    smiles = str(df.loc[df["inci_name"] == inci_name, "smiles"].iloc[0])
    index = similarity.build_fingerprint_index(df)
    neighbours = similarity.find_similar(smiles, index, top_n=top_n + 1)
    neighbours = neighbours[neighbours["inci_name"] != inci_name].head(top_n)
    return {"rdkit_available": True, "neighbours": neighbours.to_dict(orient="records")}


def _self_test() -> None:
    """Test hors-ligne : appelle les endpoints via TestClient (aucune requête réseau réelle)."""
    from fastapi.testclient import TestClient

    client = TestClient(app)

    r = client.get("/api/health")
    assert r.status_code == 200 and "rdkit_available" in r.json()

    r = client.get("/api/filters")
    assert r.status_code == 200
    filters = r.json()
    assert "categories" in filters and "inci_names" in filters

    r = client.get("/api/ingredients", params={"query": "GLY"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] <= data["total"]
    assert all("GLY" in item["inci_name"].upper() for item in data["items"])

    if filters["inci_names"]:
        ref = filters["inci_names"][0]
        r = client.get("/api/similarity", params={"inci_name": ref, "top_n": 3})
        assert r.status_code == 200

    print(
        f"[OK] self-test api.py : {data['total']} ingrédients disponibles, "
        f"endpoints /health /filters /ingredients /similarity OK"
    )


if __name__ == "__main__":
    _self_test()
