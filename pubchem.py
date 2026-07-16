"""
pubchem.py — Enrichissement PubChem : CAS → SMILES, InChI, formule
====================================================================
API : https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest

Pour chaque ingrédient, interroge l'API PubChem REST en deux étapes :
  1. CAS → CID (identifiant PubChem)
  2. CID → propriétés chimiques (SMILES, InChI, formule, nom IUPAC)

Gestion robuste :
  - Retry automatique avec backoff exponentiel sur erreur réseau
  - Délai fixe entre requêtes (rate limiting PubChem ~5 req/s)
  - Fail-safe : une erreur sur un ingrédient n'arrête pas le pipeline

Usage :
    python pubchem.py                        # enrichit tous les ingrédients
    python pubchem.py --max 100              # limite à 100 ingrédients
    python pubchem.py --delay 0.5            # délai plus conservateur
"""

import os
import time
import logging
import argparse

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL       = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CLEAN_PATH     = "data/clean/cosing_clean.csv"
ENRICHED_PATH  = "data/clean/cosing_pubchem.csv"
TIMEOUT        = 15     # secondes par requête
MAX_RETRIES    = 3      # tentatives avant abandon


# ---------------------------------------------------------------------------
# Requête unitaire avec retry
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, retries: int = MAX_RETRIES) -> requests.Response | None:
    """Effectue une requête GET avec backoff exponentiel sur erreur.

    Args:
        url:     URL à requêter.
        retries: Nombre de tentatives maximum.

    Returns:
        Objet Response si succès, None si toutes les tentatives ont échoué.
    """
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            if response.status_code == 200:
                return response
            if response.status_code == 404:
                return None  # composé non trouvé — pas la peine de réessayer
            if response.status_code == 429:
                wait = 2 ** attempt
                logger.warning("Rate limit PubChem — attente %ds (tentative %d/%d)", wait, attempt, retries)
                time.sleep(wait)
        except requests.exceptions.Timeout:
            logger.warning("Timeout (tentative %d/%d) : %s", attempt, retries, url)
            time.sleep(2 ** attempt)
        except requests.exceptions.ConnectionError:
            logger.warning("Erreur réseau (tentative %d/%d)", attempt, retries)
            time.sleep(2 ** attempt)
    return None


def get_pubchem_by_cas(cas: str) -> dict:
    """Interroge l'API PubChem pour un numéro CAS.

    Étape 1 : CAS → CID
    Étape 2 : CID → SMILES, InChI, formule, nom IUPAC

    Args:
        cas: Numéro CAS de l'ingrédient (ex. '56-81-5').

    Returns:
        Dictionnaire avec les clés : cid, smiles, inchi, formula, iupac_name.
        Les valeurs sont None si l'ingrédient n'est pas trouvé.
    """
    result = {
        "cid": None, "smiles": None, "inchi": None,
        "formula": None, "iupac_name": None,
    }

    if not cas or pd.isna(cas) or str(cas).strip() == "":
        return result

    cas = str(cas).strip()

    # Étape 1 : CAS → CID
    url_cid = f"{BASE_URL}/compound/name/{cas}/cids/JSON"
    r = _get_with_retry(url_cid)
    if r is None:
        return result

    cids = r.json().get("IdentifierList", {}).get("CID", [])
    if not cids:
        return result

    cid = cids[0]
    result["cid"] = cid

    # Étape 2 : CID → propriétés
    props = "SMILES,InChI,MolecularFormula,IUPACName"
    url_props = f"{BASE_URL}/compound/cid/{cid}/property/{props}/JSON"
    r2 = _get_with_retry(url_props)
    if r2 is None:
        return result

    props_data = r2.json().get("PropertyTable", {}).get("Properties", [{}])[0]
    result["smiles"]     = props_data.get("SMILES")
    result["inchi"]      = props_data.get("InChI")
    result["formula"]    = props_data.get("MolecularFormula")
    result["iupac_name"] = props_data.get("IUPACName")

    return result


# ---------------------------------------------------------------------------
# Enrichissement en batch
# ---------------------------------------------------------------------------

def enrich_with_pubchem(
    df: pd.DataFrame,
    cas_col: str = "cas",
    max_ingredients: int | None = None,
    delay: float = 0.3,
    checkpoint_path: str | None = None,
    checkpoint_every: int = 200,
) -> pd.DataFrame:
    """Enrichit un DataFrame avec les données SMILES de PubChem.

    Stratégie :
    - Délai fixe entre requêtes (respecte la limite PubChem ~5 req/s)
    - Retry automatique avec backoff exponentiel sur erreur réseau
    - Fail-safe par ingrédient : une erreur n'arrête pas le pipeline
    - Skip des lignes sans CAS et des lignes déjà traitées (colonne pubchem_checked)
    - Sauvegarde périodique (checkpoint_path) : une interruption ne perd que les
      ingrédients traités depuis le dernier checkpoint, pas tout le run

    Args:
        df:               DataFrame avec au minimum une colonne CAS.
        cas_col:          Nom de la colonne CAS (défaut : 'cas').
        max_ingredients:  Nombre max d'ingrédients à traiter (None = tous).
        delay:            Délai en secondes entre chaque requête (défaut : 0.3).
        checkpoint_path:  Chemin CSV où sauvegarder périodiquement (None = pas de checkpoint).
        checkpoint_every: Nombre d'ingrédients entre deux sauvegardes (défaut : 200).

    Returns:
        Tuple (DataFrame enrichi, stats de CE run : success/total/errors).
    """
    df = df.copy()

    # Initialise les colonnes SMILES
    for col in ["cid", "smiles", "inchi", "formula", "iupac_name"]:
        if col not in df.columns:
            df[col] = None
    if "pubchem_checked" not in df.columns:
        df["pubchem_checked"] = False
    # Le CSV relu (reprise) stocke ce booléen en texte ("True"/"False") ;
    # astype(bool) sur une chaîne non vide renvoie toujours True, d'où ce parsing explicite.
    df["pubchem_checked"] = (
        df["pubchem_checked"].astype(str).str.strip().str.lower().eq("true")
    )

    if cas_col not in df.columns:
        logger.error("Colonne '%s' absente — enrichissement impossible", cas_col)
        return df, {"success": 0, "total": 0, "errors": 0}

    # Sélectionne les lignes avec CAS valide, pas encore vérifiées (reprise)
    mask = df[cas_col].notna() & (df[cas_col].astype(str).str.strip() != "")
    mask &= ~df["pubchem_checked"]
    targets = df[mask]
    if max_ingredients:
        targets = targets.head(max_ingredients)

    total = len(targets)
    estimate = total * delay * 2  # deux requêtes par ingrédient
    logger.info("Enrichissement PubChem : %d ingrédients (durée estimée ~%ds)", total, int(estimate))

    success, errors = 0, 0

    for i, (idx, row) in enumerate(targets.iterrows(), start=1):
        cas  = row[cas_col]
        name = row.get("inci_name") or row.get("name") or cas

        logger.debug("[%d/%d] %s (CAS: %s)", i, total, name, cas)

        result = get_pubchem_by_cas(cas)
        df.at[idx, "pubchem_checked"] = True

        if result["smiles"]:
            for col, val in result.items():
                # Cast en str : les colonnes relues via pd.read_csv(dtype=str) (reprise)
                # utilisent un dtype string strict qui refuse un int (ex. cid) tel quel.
                df.at[idx, col] = str(val) if val is not None else None
            success += 1
            logger.debug("  ✅ CID=%s  formule=%s", result["cid"], result["formula"])
        else:
            errors += 1
            logger.debug("  ❌ non trouvé dans PubChem")

        time.sleep(delay)

        if checkpoint_path and i % checkpoint_every == 0:
            save_enriched(df, checkpoint_path)
            logger.info("Checkpoint : %d/%d ingrédients traités depuis la reprise", i, total)

    if checkpoint_path and total:
        save_enriched(df, checkpoint_path)

    coverage = success / total * 100 if total else 0
    logger.info(
        "Enrichissement terminé : %d/%d SMILES (%.1f%%) — %d non trouvés",
        success, total, coverage, errors,
    )
    return df, {"success": success, "total": total, "errors": errors}


# ---------------------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------------------

def save_enriched(df: pd.DataFrame, dest: str = ENRICHED_PATH) -> str:
    """Sauvegarde le DataFrame enrichi en CSV (utf-8-sig pour Excel).

    Args:
        df:   DataFrame enrichi.
        dest: Chemin de destination.

    Returns:
        Chemin du fichier sauvegardé.
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    df.to_csv(dest, index=False, encoding="utf-8-sig")
    smiles_n = int(df["smiles"].notna().sum()) if "smiles" in df.columns else 0
    logger.info("Sauvegardé : %s (%d lignes, %d SMILES)", dest, len(df), smiles_n)
    return dest


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Enrichissement PubChem (CAS → SMILES)")
    parser.add_argument("--input",  default=CLEAN_PATH,    help="CSV COSING nettoyé en entrée")
    parser.add_argument("--output", default=ENRICHED_PATH, help="CSV enrichi en sortie")
    parser.add_argument("--max",    type=int, default=None, help="Nombre max d'ingrédients à enrichir")
    parser.add_argument("--delay",  type=float, default=0.3, help="Délai entre requêtes (secondes)")
    parser.add_argument("--checkpoint-every", type=int, default=200,
                         help="Sauvegarde tous les N ingrédients (défaut : 200)")
    parser.add_argument("--fresh", action="store_true",
                         help="Ignore une sortie existante et repart de zéro (par défaut : reprise automatique)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Fichier introuvable : {args.input}")
        print("Lancez d'abord : python cosing.py")
        raise SystemExit(1)

    if not args.fresh and os.path.exists(args.output):
        df = pd.read_csv(args.output, dtype=str)
        n_done = int(df["pubchem_checked"].fillna("False").astype(str).str.lower().eq("true").sum()) if "pubchem_checked" in df.columns else 0
        logger.info("Reprise depuis %s : %d ingrédients déjà vérifiés", args.output, n_done)
    else:
        df = pd.read_csv(args.input, dtype=str)
        logger.info("COSING chargé : %d ingrédients", len(df))

    df_enriched, stats = enrich_with_pubchem(
        df, cas_col="cas", max_ingredients=args.max, delay=args.delay,
        checkpoint_path=args.output, checkpoint_every=args.checkpoint_every,
    )
    save_enriched(df_enriched, args.output)

    # Stats de CE run uniquement (calculées dans enrich_with_pubchem, qui seul
    # sait combien d'ingrédients étaient réellement à traiter après reprise).
    coverage = stats["success"] / stats["total"] * 100 if stats["total"] else 0.0
    smiles_total = int(df_enriched["smiles"].notna().sum())
    print(f"\n{'='*55}")
    print(f"  Enrichissement PubChem terminé")
    print(f"  Ingrédients traités (ce run) : {stats['total']:,}")
    print(f"  SMILES récupérés (ce run)    : {stats['success']:,} ({coverage:.1f}%)")
    print(f"  SMILES au total (cumulé)     : {smiles_total:,} / {len(df_enriched):,}")
    print(f"  Fichier                      : {args.output}")
    print(f"{'='*55}")
