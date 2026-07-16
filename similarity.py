"""
src/similarity.py — Similarité moléculaire par plus proches voisins (S7).

À partir du SMILES d'un ingrédient, on cherche les ingrédients chimiquement
les plus proches. La similarité repose sur les empreintes moléculaires de Morgan
(ECFP, RDKit) comparées par le coefficient de Tanimoto — la méthode standard en
chémoinformatique pour comparer des structures.

Le module dégrade proprement si RDKit est absent (liste vide, pas de crash) et
fonctionne hors-ligne grâce à un petit jeu de démonstration.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    _RDKIT_OK = True
    _MORGAN_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
except ImportError:  # pragma: no cover
    _RDKIT_OK = False
    _MORGAN_GEN = None
    logger.warning("RDKit indisponible : la similarité renverra une liste vide")

_RADIUS = 2      # ECFP4
_NBITS = 2048


def _fingerprint(smiles: str):
    """SMILES -> empreinte de Morgan (ou None si invalide/RDKit absent)."""
    if not _RDKIT_OK or not smiles or pd.isna(smiles):
        return None
    mol = Chem.MolFromSmiles(str(smiles))
    if mol is None:
        return None
    return _MORGAN_GEN.GetFingerprint(mol)


def build_fingerprint_index(df: pd.DataFrame, smiles_col: str = "smiles",
                            name_col: str = "inci_name") -> list[dict]:
    """
    Pré-calcule les empreintes de tous les ingrédients ayant un SMILES valide.
    Renvoie une liste d'entrées {name, smiles, fp} réutilisable pour les requêtes.
    """
    index = []
    for _, row in df.iterrows():
        fp = _fingerprint(row.get(smiles_col))
        if fp is not None:
            index.append({"name": row.get(name_col), "smiles": row.get(smiles_col), "fp": fp})
    logger.info("Index de similarité : %d molécules indexées", len(index))
    return index


def find_similar(query_smiles: str, index: list[dict], top_n: int = 5) -> pd.DataFrame:
    """
    Renvoie les `top_n` molécules les plus proches du SMILES requête,
    triées par similarité de Tanimoto décroissante.
    """
    cols = ["inci_name", "smiles", "similarity"]
    q = _fingerprint(query_smiles)
    if q is None or not index:
        return pd.DataFrame(columns=cols)

    scored = []
    for entry in index:
        sim = DataStructs.TanimotoSimilarity(q, entry["fp"])
        scored.append((entry["name"], entry["smiles"], round(float(sim), 3)))
    scored.sort(key=lambda x: x[2], reverse=True)
    return pd.DataFrame(scored[:top_n], columns=cols)


def create_demo_index() -> list[dict]:
    """Jeu de démonstration hors-ligne (ingrédients cosmétiques + apparentés)."""
    demo = pd.DataFrame([
        {"inci_name": "GLYCERIN", "smiles": "C(C(CO)O)O"},
        {"inci_name": "PROPYLENE GLYCOL", "smiles": "CC(CO)O"},
        {"inci_name": "BUTYLENE GLYCOL", "smiles": "CCC(CO)O"},
        {"inci_name": "SALICYLIC ACID", "smiles": "C1=CC=C(C(=C1)C(=O)O)O"},
        {"inci_name": "BENZOIC ACID", "smiles": "C1=CC=C(C=C1)C(=O)O"},
        {"inci_name": "NIACINAMIDE", "smiles": "C1=CC(=CN=C1)C(=O)N"},
        {"inci_name": "CITRIC ACID", "smiles": "C(C(=O)O)C(CC(=O)O)(C(=O)O)O"},
        {"inci_name": "WATER", "smiles": "O"},
    ])
    return build_fingerprint_index(demo)


def _self_test() -> None:
    index = create_demo_index()
    if not _RDKIT_OK:
        assert index == []
        print("[OK] self-test similarity.py : RDKit absent, dégradation propre")
        return
    # La glycérine doit ressortir les autres glycols en tête.
    res = find_similar("C(C(CO)O)O", index, top_n=3)
    assert not res.empty and res.iloc[0]["inci_name"] == "GLYCERIN"
    neighbours = set(res["inci_name"])
    assert "PROPYLENE GLYCOL" in neighbours or "BUTYLENE GLYCOL" in neighbours
    top = res.iloc[1]
    print(f"[OK] self-test similarity.py : voisin le plus proche de GLYCERIN = "
          f"{top['inci_name']} (Tanimoto {top['similarity']})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()