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
# .env.example é uma referência: o Django não carrega arquivos .env automaticamente.
$env:DJANGO_DEBUG = "true"
$env:DATABASE_URL = "postgres://noxora:noxora_dev@localhost:5432/noxora"
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```
Verificações (em `backend`, com as variáveis acima):
```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python manage.py check
.\.venv\Scripts\python manage.py makemigrations --check --dry-run
```
Sem PostgreSQL, defina `$env:DATABASE_URL = "sqlite:///:memory:"` somente para testes;
para desenvolvimento persistente, remova a variável com `Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue`.
SQLite exige `DJANGO_DEBUG=true` e não valida comportamento de PostgreSQL.

Fora de debug, `DJANGO_SECRET_KEY` precisa de uma chave aleatória privada com pelo menos
50 caracteres e 5 caracteres distintos; o exemplo não é uma chave válida para produção.
`DATABASE_URL` deve apontar para PostgreSQL e `DJANGO_ALLOWED_HOSTS` deve listar os hosts
autorizados (sem `*`). Cookies de sessão e CSRF exigem HTTPS fora de debug;
`DJANGO_COOKIE_SECURE=false` não desativa essa proteção. A terminação TLS, o proxy,
redirecionamento HTTPS e HSTS ainda precisam de configuração na etapa de implantação.

Endpoints: `GET /api/health/` (liveness) e `GET /api/ready/` (readiness, 503 sem banco).
Respostas JSON: saúde `{"status":"ok"}`; prontidão `{"status":"ok","database":"ok"}`
ou HTTP 503 com `{"status":"indisponivel","database":"falha"}`. São endpoints públicos,
sem detalhes do banco. Prontidão verifica conectividade (`SELECT 1`), não migrations aplicadas.

## PostgreSQL sem Docker (opcional, Windows)
```powershell
.\tools\postgres_local.ps1 setup    # baixa o PostgreSQL 17 portátil (~330 MB) para .local/ e confere o SHA-256
.\tools\postgres_local.ps1 start    # porta 5433, somente 127.0.0.1, sem senha: apenas desenvolvimento
$env:DATABASE_URL = (.\tools\postgres_local.ps1 env)
cd backend; .\.venv\Scripts\python -m pytest -q    # suíte completa em PostgreSQL real (concorrência, gatilhos)
.\tools\postgres_local.ps1 stop
```
A primeira instalação é demorada (milhares de arquivos). Os testes de concorrência e de `TRUNCATE` só executam em PostgreSQL.

## Frontend
```powershell
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxy /api -> http://localhost:8000
npm run lint; npm run format:check; npm run typecheck; npm test; npm run build
```

O proxy `/api` existe no servidor de desenvolvimento do Vite. O build estático precisa
ser servido com roteamento de `/api` para o backend; a hospedagem não integra esta etapa.

## Tablet
Veja [tablet/README.md](tablet/README.md). URL da API via `--dart-define=API_BASE_URL=...` (emulador: `10.0.2.2`; dispositivo físico: IP da máquina).

## Revisão pelo Codex
`tools/codex_handoff.ps1 -Etapa N -Nome "..."` (exige `docs/controle/prompt-codex-NN.md`).
