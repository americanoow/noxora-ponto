# Noxora Ponto

SaaS de controle de jornada e gestão operacional de funcionários (Django + DRF, React, Flutter, PostgreSQL). Plano completo em [docs/plano.md](docs/plano.md); regras para as IAs em [CLAUDE.md](CLAUDE.md) e [AGENTS.md](AGENTS.md).

## Requisitos
Python 3.13+, Node 22+, Docker (PostgreSQL) e Flutter (tablet). Sem Docker, o backend usa SQLite apenas para desenvolvimento; isso **não** substitui a validação em PostgreSQL.

## Backend (PowerShell)
```powershell
docker compose up -d db                       # PostgreSQL
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env                   # ajuste se necessário
$env:DJANGO_DEBUG = "true"
$env:DATABASE_URL = "postgres://noxora:noxora_dev@localhost:5432/noxora"
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```
Verificações: `ruff check .`, `ruff format --check .`, `pytest -q`.
Endpoints: `GET /api/health/` (liveness) e `GET /api/ready/` (readiness, 503 sem banco).

## Frontend
```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173, proxy /api -> http://localhost:8000
npm run lint; npm run typecheck; npm test; npm run build
```

## Tablet
Veja [tablet/README.md](tablet/README.md). URL da API via `--dart-define=API_BASE_URL=...` (emulador: `10.0.2.2`; dispositivo físico: IP da máquina).

## Revisão pelo Codex
`tools/codex_handoff.ps1 -Etapa N -Nome "..."` (exige `docs/controle/prompt-codex-NN.md`).
