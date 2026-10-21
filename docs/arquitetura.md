# Arquitetura

```
frontend (React/Vite)  ──HTTP/JSON──┐
tablet (Flutter/Android) ──HTTP/JSON─┼─> backend (Django+DRF) ──> PostgreSQL
                                     │
```

## Backend (`backend/`)
- Projeto `config`, apps: `core` (saúde/prontidão), `accounts` (usuário customizado).
- Configuração por variáveis de ambiente (`.env.example`).
- `GET /api/health/` — liveness (sempre 200 se o processo responde).
- `GET /api/ready/` — readiness (200 se o banco responde, 503 caso contrário).

## Frontend (`frontend/`)
Consulta `/api/health/` e `/api/ready/` via proxy do Vite; estados carregando/sucesso/falha.

## Tablet (`tablet/`)
App Flutter com consulta equivalente. URL da API configurável (`--dart-define=API_BASE_URL`); emulador usa `10.0.2.2`.
