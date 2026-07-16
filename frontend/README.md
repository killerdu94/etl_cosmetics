# Cosmetic Intelligence Engine — Frontend React

Interface React (Vite) qui consomme l'API FastAPI (`api.py`, à la racine du projet).
Coexiste avec l'app Streamlit (`search_app.py`) : les deux lisent les mêmes données,
aucune n'est requise pour faire fonctionner l'autre.

## Prérequis

- Node.js ≥ 18 (non installé sur cette machine au moment de la création de ce projet —
  installer depuis https://nodejs.org avant de continuer).

## Installation et lancement

```powershell
# 1. Backend (depuis la racine du projet, dans un terminal séparé)
python -m uvicorn api:app --reload --port 8000

# 2. Frontend (depuis ce dossier frontend/)
npm install
npm run dev
```

Ouvrir http://localhost:5173. Le frontend appelle l'API sur http://localhost:8000
(voir `src/api.js` pour changer l'URL si besoin).

## Structure

- `src/api.js` — client HTTP vers l'API FastAPI (filtres, recherche, similarité).
- `src/components/SearchTab.jsx` — recherche par nom INCI + filtres catégorie/matière.
- `src/components/SimilarityTab.jsx` — voisins les plus proches (Tanimoto) d'un ingrédient.
- `src/App.css` — thème vert / violet / bleu, clair et sombre.
