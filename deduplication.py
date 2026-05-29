"""
deduplication.py — Dédupliquer les entrées
===========================================
Lundi 25/05/2026 — S2 ETL consolidé

Identifie et supprime les doublons dans les données consolidées COSING/PubChem.
Stratégie hybride :
  1. Déduplication exacte sur le numéro CAS (identifiant chimique non ambigu)
  2. Déduplication fuzzy sur les noms INCI (seuil 95 %) pour les entrées sans CAS
  3. Conservation de la ligne la plus complète (merge) en cas de doublon partiel
"""

import logging
import pandas as pd
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Déduplication exacte
# ---------------------------------------------------------------------------

def deduplicate_exact(df: pd.DataFrame, key: str = "canonical_cas") -> pd.DataFrame:
    """Déduplication exacte sur une colonne clé.

    En cas de doublon, conserve la ligne avec le plus de champs non nuls
    (stratégie merge) plutôt que keep='first' arbitraire.

    Args:
        df:  DataFrame à dédupliquer.
        key: Colonne servant de clé de déduplication (défaut : 'canonical_cas').

    Returns:
        DataFrame sans doublons exacts sur la colonne key.
    """
    before = len(df)
    # Ne déduplique que les lignes avec une clé non vide
    df_with_key = df[df[key] != ""].copy()
    df_no_key   = df[df[key] == ""].copy()

    # Pour chaque groupe de même CAS, garde la ligne la plus complète
    def keep_most_complete(group: pd.DataFrame) -> pd.Series:
        scores = group.notna().sum(axis=1)
        best   = scores.idxmax()
        merged = group.loc[best].copy()
        # Complète les champs manquants avec les autres lignes du groupe
        for col in group.columns:
            if pd.isna(merged[col]):
                non_null = group[col].dropna()
                if not non_null.empty:
                    merged[col] = non_null.iloc[0]
        return merged

    df_dedup = (
        df_with_key
        .groupby(key, group_keys=False)
        .apply(keep_most_complete)
        .reset_index(drop=True)
    )

    result = pd.concat([df_dedup, df_no_key], ignore_index=True)
    after  = len(result)
    logger.info("Déduplication exacte : %d → %d entrées (%d doublons supprimés)", before, after, before - after)
    return result


# ---------------------------------------------------------------------------
# Déduplication fuzzy
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    """Calcule le ratio de similarité entre deux chaînes (0.0 → 1.0)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate_fuzzy(df: pd.DataFrame, name_col: str = "canonical_name", threshold: float = 0.95) -> pd.DataFrame:
    """Déduplication fuzzy sur les noms INCI pour les entrées sans CAS.

    Identifie les paires dont la similarité dépasse le seuil (95 % par défaut)
    et fusionne la moins complète dans la plus complète.

    Args:
        df:        DataFrame à traiter (uniquement les lignes sans CAS).
        name_col:  Colonne de nom canonique.
        threshold: Seuil de similarité (0.95 = 95 %).

    Returns:
        DataFrame avec doublons fuzzy résolus.
    """
    before = len(df)
    names  = df[name_col].tolist()
    to_drop = set()

    for i in range(len(names)):
        if i in to_drop:
            continue
        for j in range(i + 1, len(names)):
            if j in to_drop:
                continue
            if _similarity(names[i], names[j]) >= threshold:
                # Garde l'entrée la plus complète
                score_i = df.iloc[i].notna().sum()
                score_j = df.iloc[j].notna().sum()
                to_drop.add(j if score_i >= score_j else i)

    result = df.drop(index=list(to_drop)).reset_index(drop=True)
    after  = len(result)
    logger.info("Déduplication fuzzy : %d → %d entrées (%d doublons supprimés)", before, after, before - after)
    return result


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline de déduplication hybride (exacte puis fuzzy).

    Args:
        df: DataFrame harmonisé (avec colonnes 'canonical_cas' et 'canonical_name').

    Returns:
        DataFrame dédupliqué.
    """
    logger.info("Début déduplication — %d entrées en entrée", len(df))

    # Étape 1 : déduplication exacte sur CAS
    df = deduplicate_exact(df, key="canonical_cas")

    # Étape 2 : déduplication fuzzy sur les noms pour les entrées sans CAS
    no_cas  = df[df["canonical_cas"] == ""].copy()
    has_cas = df[df["canonical_cas"] != ""].copy()

    if not no_cas.empty:
        no_cas = deduplicate_fuzzy(no_cas, name_col="canonical_name", threshold=0.95)

    df = pd.concat([has_cas, no_cas], ignore_index=True)
    logger.info("Déduplication terminée — %d entrées en sortie", len(df))
    return df
