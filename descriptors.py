"""
src/descriptors.py — Descripteurs moléculaires via RDKit (S5).

À partir du SMILES (récupéré via PubChem), on calcule les descripteurs
physico-chimiques utiles pour caractériser un ingrédient :
    - MW   : poids moléculaire
    - logP : lipophilie (octanol/eau)
    - TPSA : surface polaire topologique
    - HBD/HBA : donneurs / accepteurs de liaisons hydrogène

RDKit ne s'installe pas toujours dans tous les environnements ; le module
dégrade proprement (valeurs None) si l'import échoue, pour ne pas casser le
pipeline. Les SMILES invalides renvoient aussi None (et sont comptés).
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from rdkit import Chem  # type: ignore
    from rdkit.Chem import Descriptors, rdMolDescriptors  # type: ignore

    _RDKIT_OK = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    _RDKIT_OK = False
    logger.warning("RDKit indisponible : descripteurs renvoyés à None")


def compute_descriptors(smiles: Optional[str]) -> dict[str, Optional[float]]:
    """Calcule les descripteurs d'un SMILES. Renvoie des None si invalide/absent."""
    empty = {"mol_weight": None, "logp": None, "tpsa": None, "hbd": None, "hba": None}
    if not _RDKIT_OK or not smiles or pd.isna(smiles):
        return empty

    mol = Chem.MolFromSmiles(str(smiles))
    if mol is None:
        logger.info("SMILES invalide ignoré : %r", smiles)
        return empty

    return {
        "mol_weight": round(Descriptors.MolWt(mol), 2),
        "logp": round(Descriptors.MolLogP(mol), 2),
        "tpsa": round(rdMolDescriptors.CalcTPSA(mol), 2),
        "hbd": rdMolDescriptors.CalcNumHBD(mol),
        "hba": rdMolDescriptors.CalcNumHBA(mol),
    }


def enrich_with_descriptors(df: pd.DataFrame, smiles_col: str = "smiles") -> pd.DataFrame:
    """Ajoute les colonnes de descripteurs au DataFrame à partir du SMILES."""
    out = df.copy()
    desc = out[smiles_col].apply(compute_descriptors).apply(pd.Series)
    return pd.concat([out, desc], axis=1)


def _self_test() -> None:
    # Données de démo intégrées : aucune dépendance à pubchem.py.
    df = pd.DataFrame(
        {"smiles": ["O", "C(C(CO)O)O", "C1=CC(=CN=C1)C(=O)N", None, "bad_smiles"]}
    )
    enriched = enrich_with_descriptors(df)
    assert {"mol_weight", "logp", "tpsa"} <= set(enriched.columns)

    eth = compute_descriptors("CCO")  # éthanol
    bad = compute_descriptors("not_a_smiles")
    assert bad["mol_weight"] is None
    if _RDKIT_OK:
        assert eth["mol_weight"] is not None and 45 < eth["mol_weight"] < 47
        msg = f"MW éthanol={eth['mol_weight']}, TPSA={eth['tpsa']}"
    else:
        msg = "RDKit absent (mode dégradé)"
    print(f"[OK] self-test descriptors.py : {msg}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _self_test()