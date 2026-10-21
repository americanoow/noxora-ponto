# Etapa 1 — Estrutura inicial: implementação

## Entregue
- Backend Django 6.0.9 + DRF 3.18.3 (`backend/`): `config`, apps `core` (saúde/prontidão) e `accounts` (usuário customizado por e-mail, migration 0001).
- `GET /api/health/` e `GET /api/ready/` (503 sem banco, sem vazar o erro).
- Configuração por ambiente (`DJANGO_SECRET_KEY` obrigatório fora de debug, `DATABASE_URL`); `.env.example` sem segredos.
- Frontend React 19 + Vite + TS (`frontend/`) com estados carregando/sucesso/falha; proxy `/api`.
- App Flutter (`tablet/`) com consulta equivalente, URL via `--dart-define`.
- `docker-compose.yml` (PostgreSQL 17 com volume), CI em `.github/workflows/ci.yml`, README (PowerShell).

## Verificações executadas
- Backend: `pytest` 4 passando (SQLite); `ruff check`/`format` limpos; migrations aplicadas.
- Frontend: lint, typecheck, `vitest` 3 passando, build ok.
- Integração real: backend em `:8000` e Vite em `:5173` responderam `/api/health/` e `/api/ready/` pelo proxy.

## Pendências de validação
- **Docker ausente:** PostgreSQL/Compose não executados; testes rodaram em SQLite (não prova PostgreSQL). CI roda em PostgreSQL.
- **Flutter ausente:** `tablet/` não compilado nem testado; `android/` será gerado por `flutter create .`.
- CI nunca executada (sem repositório remoto).
