# start.ps1 — Lance l'API FastAPI et l'interface React ensemble.
# Usage : .\start.ps1  (depuis la racine du projet, en PowerShell)

$root = $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; python -m uvicorn api:app --reload --port 8000"

Set-Location "$root\frontend"
npm run dev
