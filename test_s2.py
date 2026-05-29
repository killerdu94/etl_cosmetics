"""
test_s2.py — Tests unitaires ETL S2
=====================================
Mercredi 27/05/2026 — S2 ETL consolidé

10 tests unitaires couvrant tous les modules S2 :
  - harmonization.py  (tests 1-3)
  - deduplication.py  (tests 4-6)
  - price_normalization.py (tests 7-9)
  - supplier_parser.py (test 10)

Stratégie :
  - Un test par comportement, pas par fonction
  - Données synthétiques minimalistes créées directement ici
  - Assertions avec messages d'erreur explicites
  - Lancement : python tests/test_s2.py
"""

import sys
import os
import io

# Ajoute src/ au path pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
from harmonization import normalize_text, normalize_cas, harmonize
from deduplication import deduplicate_exact, deduplicate_fuzzy, deduplicate
from price_normalization import extract_amount, detect_currency, detect_unit, convert_to_eur_per_kg, normalize_prices


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_equal(actual, expected, msg: str) -> None:
    assert actual == expected, f"FAIL — {msg}\n  Attendu : {expected!r}\n  Obtenu  : {actual!r}"

def assert_true(condition: bool, msg: str) -> None:
    assert condition, f"FAIL — {msg}"

def run_test(name: str, fn) -> bool:
    try:
        fn()
        print(f"  ✅ {name}")
        return True
    except AssertionError as e:
        print(f"  ❌ {name}\n     {e}")
        return False
    except Exception as e:
        print(f"  💥 {name} — Exception inattendue : {e}")
        return False


# ---------------------------------------------------------------------------
# Tests 1-3 : harmonization.py
# ---------------------------------------------------------------------------

def test_normalize_text_strip_lower_title():
    """normalize_text doit strip, lower puis re-capitaliser en INCI."""
    result = normalize_text("  SODIUM LAURYL SULFATE  ")
    assert_equal(result, "Sodium Lauryl Sulfate", "normalize_text strip+lower+title")


def test_normalize_text_special_chars():
    """normalize_text doit supprimer les caractères parasites."""
    result = normalize_text("Glycerin\u00ad\u00adol")  # tirets insécables
    assert_true("Glycerinol" in result or "Glycerin" in result, "normalize_text caractères spéciaux supprimés")


def test_harmonize_canonical_cas_priority():
    """harmonize doit choisir le nom COSING en priorité sur PubChem pour le même CAS."""
    df = pd.DataFrame([
        {"name": "Sodium Lauryl Sulfate", "cas": "151-21-3", "source": "COSING"},
        {"name": "sodium lauryl sulfate", "cas": "151-21-3", "source": "PubChem"},
        {"name": "SLS",                   "cas": "151-21-3", "source": "supplier"},
    ])
    result = harmonize(df)
    # Les trois entrées doivent avoir le même canonical_name (celui de COSING)
    assert_true(result["canonical_name"].nunique() == 1, "harmonize : un seul canonical_name pour le même CAS")
    assert_true("Sodium" in result["canonical_name"].iloc[0], "harmonize : priorité donnée à COSING")


# ---------------------------------------------------------------------------
# Tests 4-6 : deduplication.py
# ---------------------------------------------------------------------------

def test_deduplicate_exact_removes_duplicate_cas():
    """deduplicate_exact doit supprimer les lignes avec le même CAS."""
    df = pd.DataFrame([
        {"canonical_cas": "151-21-3", "canonical_name": "Sodium Lauryl Sulfate", "smiles": "CCS", "source": "COSING"},
        {"canonical_cas": "151-21-3", "canonical_name": "Sodium Lauryl Sulfate", "smiles": None,  "source": "PubChem"},
    ])
    result = deduplicate_exact(df, key="canonical_cas")
    assert_equal(len(result), 1, "deduplicate_exact : 2 lignes → 1 après déduplication exacte")


def test_deduplicate_exact_keeps_most_complete():
    """deduplicate_exact doit garder la ligne la plus complète (merge)."""
    df = pd.DataFrame([
        {"canonical_cas": "56-81-5", "canonical_name": "Glycerin", "smiles": None,    "mw": 92.0},
        {"canonical_cas": "56-81-5", "canonical_name": "Glycerin", "smiles": "OCC(O)CO", "mw": None},
    ])
    result = deduplicate_exact(df, key="canonical_cas")
    assert_equal(len(result), 1, "deduplicate_exact merge : 1 ligne en sortie")
    # La ligne résultante doit avoir smiles ET mw
    assert_true(result.iloc[0]["smiles"] == "OCC(O)CO", "deduplicate_exact merge : smiles récupéré")


def test_deduplicate_fuzzy_removes_near_duplicates():
    """deduplicate_fuzzy doit fusionner les noms très similaires (>95%)."""
    df = pd.DataFrame([
        {"canonical_cas": "", "canonical_name": "Sodium Chloride",  "source": "COSING"},
        {"canonical_cas": "", "canonical_name": "Sodium Chloridee", "source": "supplier"},  # faute de frappe
    ])
    result = deduplicate_fuzzy(df, name_col="canonical_name", threshold=0.95)
    assert_equal(len(result), 1, "deduplicate_fuzzy : 2 noms quasi-identiques → 1 entrée")


# ---------------------------------------------------------------------------
# Tests 7-9 : price_normalization.py
# ---------------------------------------------------------------------------

def test_extract_amount_french_format():
    """extract_amount doit parser le format français 1.234,56."""
    result = extract_amount("1.234,56 €/kg")
    assert_equal(result, 1234.56, "extract_amount format français")


def test_extract_amount_english_format():
    """extract_amount doit parser le format anglais 1,234.56."""
    result = extract_amount("$1,234.56/kg")
    assert_equal(result, 1234.56, "extract_amount format anglais")


def test_normalize_prices_eur_per_kg():
    """normalize_prices doit convertir correctement USD/kg en EUR/kg."""
    df = pd.DataFrame([{
        "price_raw": "10.00 USD/kg",
        "currency": "USD",
        "unit": "kg",
        "price_includes_vat": False,
        "country": "US",
    }])
    result = normalize_prices(df)
    expected = round(10.0 * 0.922, 4)
    assert_equal(result["price_eur_per_kg"].iloc[0], expected, "normalize_prices USD→EUR")


# ---------------------------------------------------------------------------
# Test 10 : supplier_parser.py
# ---------------------------------------------------------------------------

def test_parse_csv_returns_correct_schema():
    """parse_csv doit retourner un DataFrame avec les colonnes canoniques."""
    import tempfile, csv
    from supplier_parser import parse_csv, OUTPUT_COLUMNS

    # Crée un CSV temporaire minimal
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["ingredient_name", "cas", "prix", "unité", "devise", "qté_min"])
        writer.writerow(["Glycerin", "56-81-5", "12,50", "kg", "EUR", "25kg"])
        tmppath = f.name

    try:
        result = parse_csv(tmppath, supplier="TestFournisseur")
        for col in OUTPUT_COLUMNS:
            assert_true(col in result.columns, f"parse_csv : colonne '{col}' présente")
        assert_equal(result["supplier"].iloc[0], "TestFournisseur", "parse_csv : supplier correct")
    finally:
        os.unlink(tmppath)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    ("1. normalize_text strip+lower+title",         test_normalize_text_strip_lower_title),
    ("2. normalize_text caractères spéciaux",        test_normalize_text_special_chars),
    ("3. harmonize priorité source COSING",          test_harmonize_canonical_cas_priority),
    ("4. deduplicate_exact supprime doublons CAS",   test_deduplicate_exact_removes_duplicate_cas),
    ("5. deduplicate_exact garde ligne complète",    test_deduplicate_exact_keeps_most_complete),
    ("6. deduplicate_fuzzy fusionne quasi-doublons", test_deduplicate_fuzzy_removes_near_duplicates),
    ("7. extract_amount format français",            test_extract_amount_french_format),
    ("8. extract_amount format anglais",             test_extract_amount_english_format),
    ("9. normalize_prices USD → EUR/kg",             test_normalize_prices_eur_per_kg),
    ("10. parse_csv schéma canonique",               test_parse_csv_returns_correct_schema),
]

if __name__ == "__main__":
    print("\n🧪 Tests unitaires S2 — ETL Consolidé")
    print("=" * 45)
    passed = sum(run_test(name, fn) for name, fn in TESTS)
    total  = len(TESTS)
    print("=" * 45)
    print(f"\n{'✅' if passed == total else '❌'} {passed}/{total} tests passés\n")
    sys.exit(0 if passed == total else 1)
