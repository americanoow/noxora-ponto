# Decisões técnicas

| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D1 | Modelo de usuário Django customizado (`accounts.User`) criado na etapa 1, com login por e-mail | Evita migração difícil depois | Etapa 2 estende com empresas e papéis |
| D2 | Backend monolítico modular | Simplicidade | Sem microsserviços/filas até haver necessidade |
| D3 | Codex acionado por `tools/codex_handoff.ps1` com `codex exec --sandbox workspace-write` | CLI local disponível | Script verifica pausa antes de chamar |
| D4 | Commits pelo Claude; Codex não comita | Evitar histórico concorrente | Commit após cada etapa/checkpoint de segurança |
| D5 | Docker/Flutter ausentes no ambiente | Não instalar sem necessidade | Validações marcadas pendentes; testes do backend usam SQLite apenas quando `DATABASE_URL` ausente, nunca como prova de PostgreSQL |

## Pendências de validação especializada
- Requisitos REP-P/Portaria 671/2021 (etapa 5), LGPD para biometria (etapa 6), regras de apuração (etapa 8).
