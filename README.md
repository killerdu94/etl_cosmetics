# etl_cosmetics 🧴

Plateforme de données enrichies pour l'exploration d'ingrédients cosmétiques.  
Stage IA-Institut — Latentia Labs | 18 mai → 18 juillet 2026

## Stack
- Python 3 + pandas + requests
- SQLite / Postgres
- RDKit (semaine 5)
- Streamlit (semaine 6)
- FAISS (semaine 7)

## Setup
```bash
python -m venv venv
source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
```

## Structure
```
etl_cosmetics/
├── data/raw/      # données brutes téléchargées
├── data/clean/    # données nettoyées et harmonisées
├── src/           # scripts ETL
├── notebooks/     # explorations
└── tests/         # tests unitaires
```

## Sources
- COSING (UE) — base prioritaire
- PubChem — identifiants chimiques
- INCI nomenclature
- ECHA — données réglementaires
