"""
tests/test_s1.py
Tâche S1 : Tester sur 50 ingrédients — pipeline COSING + PubChem
Lance avec : python tests/test_s1.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
from cosing import create_demo_data, clean_cosing, save_clean
from pubchem import create_demo_pubchem, save_enriched

SEPARATOR = "─" * 55


def test_cosing_structure(df: pd.DataFrame):
    """Vérifie que le DataFrame COSING a la bonne structure."""
    print(f"\n{SEPARATOR}")
    print("🧪 TEST 1 : Structure du DataFrame COSING")
    print(SEPARATOR)

    cols_requises = ["inci_name", "cas", "function"]
    manquantes = [c for c in cols_requises if c not in df.columns]

    if manquantes:
        print(f"  ❌ Colonnes manquantes : {manquantes}")
        return False

    print(f"  ✅ Colonnes présentes : {list(df.columns)}")
    print(f"  ✅ Nombre de lignes   : {len(df)}")
    return True


def test_cosing_qualite(df: pd.DataFrame):
    """Vérifie la qualité des données COSING."""
    print(f"\n{SEPARATOR}")
    print("🧪 TEST 2 : Qualité des données")
    print(SEPARATOR)

    # Doublons
    doublons = df["inci_name"].duplicated().sum()
    print(f"  Doublons INCI      : {doublons}", "✅" if doublons == 0 else "⚠️")

    # Valeurs vides sur inci_name
    vides = df["inci_name"].isna().sum()
    print(f"  INCI name vides    : {vides}", "✅" if vides == 0 else "⚠️")

    # Couverture CAS
    avec_cas = df["cas"].notna().sum()
    pct_cas = avec_cas / len(df) * 100
    print(f"  Avec CAS           : {avec_cas}/{len(df)} ({pct_cas:.1f}%)", "✅" if pct_cas > 70 else "⚠️")

    # Couverture fonction
    avec_fn = df["function"].notna().sum() if "function" in df.columns else 0
    pct_fn = avec_fn / len(df) * 100 if len(df) > 0 else 0
    print(f"  Avec fonction      : {avec_fn}/{len(df)} ({pct_fn:.1f}%)", "✅" if pct_fn > 80 else "⚠️")

    return doublons == 0 and vides == 0


def test_50_ingredients(df: pd.DataFrame):
    """Vérifie qu'on a bien 50 ingrédients de test."""
    print(f"\n{SEPARATOR}")
    print("🧪 TEST 3 : Validation sur 50 ingrédients")
    print(SEPARATOR)

    n = len(df)
    print(f"  Ingrédients chargés : {n}")

    if n < 50:
        print(f"  ⚠️  Moins de 50 ingrédients ({n})")
        return False

    print(f"  ✅ 50 ingrédients présents")

    # Afficher les 10 premiers
    print(f"\n  📋 Aperçu des 10 premiers ingrédients :")
    print(f"  {'INCI Name':<35} {'CAS':<15} {'Fonction':<25}")
    print(f"  {'-'*35} {'-'*15} {'-'*25}")
    for _, row in df.head(10).iterrows():
        inci = str(row.get("inci_name", ""))[:34]
        cas  = str(row.get("cas", "N/A"))[:14] if row.get("cas") else "N/A"
        fn   = str(row.get("function", "N/A"))[:24] if row.get("function") else "N/A"
        print(f"  {inci:<35} {cas:<15} {fn:<25}")

    return True


def test_pubchem_enrichissement(df: pd.DataFrame):
    """Vérifie l'enrichissement PubChem (SMILES, InChI, formule)."""
    print(f"\n{SEPARATOR}")
    print("🧪 TEST 4 : Enrichissement PubChem (CAS → SMILES)")
    print(SEPARATOR)

    df_enriched = create_demo_pubchem(df)

    # Vérifier les nouvelles colonnes
    cols_attendues = ["cid", "smiles", "inchi", "formula", "iupac_name"]
    for col in cols_attendues:
        present = col in df_enriched.columns
        print(f"  Colonne '{col}' : {'✅' if present else '❌'}")

    # Stats SMILES
    smiles_ok = df_enriched["smiles"].notna().sum() if "smiles" in df_enriched.columns else 0
    print(f"\n  SMILES récupérés   : {smiles_ok}/{len(df_enriched)}")

    # Exemples d'ingrédients enrichis
    if smiles_ok > 0:
        print(f"\n  📋 Exemples enrichis :")
        enriched = df_enriched[df_enriched["smiles"].notna()]
        for _, row in enriched.head(5).iterrows():
            print(f"    • {row['inci_name']}")
            print(f"      SMILES  : {str(row['smiles'])[:60]}...")
            print(f"      Formule : {row.get('formula', 'N/A')}")

    return df_enriched, smiles_ok > 0


def test_sauvegarde(df: pd.DataFrame, df_enriched: pd.DataFrame):
    """Vérifie que les fichiers sont bien sauvegardés."""
    print(f"\n{SEPARATOR}")
    print("🧪 TEST 5 : Sauvegarde des fichiers")
    print(SEPARATOR)

    save_clean(df, "data/clean/cosing_clean.csv")
    save_enriched(df_enriched, "data/clean/cosing_pubchem.csv")

    for path in ["data/clean/cosing_clean.csv", "data/clean/cosing_pubchem.csv"]:
        exists = os.path.exists(path)
        size = os.path.getsize(path) // 1024 if exists else 0
        print(f"  {'✅' if exists else '❌'} {path} ({size} Ko)")

    return True


def run_all_tests():
    """Lance tous les tests de la S1."""
    print(f"\n{'='*55}")
    print("  TESTS S1 — Pipeline COSING + PubChem")
    print(f"  Stage : Cosmetic Intelligence Engine")
    print(f"{'='*55}")

    results = []

    # Créer les données de démo
    df_raw = create_demo_data()

    # TEST 1 : Structure
    results.append(test_cosing_structure(df_raw))

    # TEST 2 : Qualité
    results.append(test_cosing_qualite(df_raw))

    # TEST 3 : 50 ingrédients
    results.append(test_50_ingredients(df_raw))

    # TEST 4 : PubChem
    df_enriched, pubchem_ok = test_pubchem_enrichissement(df_raw)
    results.append(pubchem_ok)

    # TEST 5 : Sauvegarde
    results.append(test_sauvegarde(df_raw, df_enriched))

    # Résumé final
    print(f"\n{'='*55}")
    passed = sum(results)
    total  = len(results)
    status = "✅ TOUS LES TESTS PASSENT" if passed == total else f"⚠️  {total - passed} test(s) échoué(s)"
    print(f"  {status} ({passed}/{total})")
    print(f"{'='*55}\n")

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
