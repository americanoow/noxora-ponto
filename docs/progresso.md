# Progresso

Estado vivo em [controle/estado.json](controle/estado.json).

## Ambiente (2026-10-21)
Git, Python 3.15, Node 24, Codex CLI 0.163.0 disponíveis. **Ausentes:** Docker, Flutter. PostgreSQL 17.5 portátil disponível via `tools/postgres_local.ps1` (porta 5433). JAVA_HOME definido (JDK 21).

## Etapas
| Etapa | Implementado | Testado | Revisado Codex | Validado ext. | Implantado |
|-------|--------------|---------|----------------|---------------|------------|
| 1 | sim, com validações pendentes | backend SQLite e frontend; Flutter/PostgreSQL pendentes | sim, conferido pelo Claude | não | não |
| 2 | sim | backend 83 (SQLite), frontend 25 | sim, conferido pelo Claude: [relatório](etapas/02-revisao.md) | não | não |
| 3 | sim | backend 150 (SQLite), frontend 33 | sim, relatório completo; conferido pelo Claude: [relatório](etapas/03-revisao.md) | não | não |
| 4 | sim (Flutter não compilado) | backend 202 (SQLite, 1 ignorado), frontend 39 | sim, conferido pelo Claude: [relatório](etapas/04-revisao.md) | não | não |
| 5 | sim (Flutter não compilado) | backend 259 em PostgreSQL 17.5 e 255 em SQLite; frontend 44 | sim, conferido pelo Claude: [relatório](etapas/05-revisao.md) | não (ver requisitos-rep-p.md) | não |
| 6 | parcial: infraestrutura sim; motor real e câmera NÃO (bloqueado) | backend 336 em PostgreSQL e 328 em SQLite; frontend 54 | revisão principal feita (3 apontamentos corrigidos pelo Claude); revisão complementar NÃO feita (apenas Claude Code, por instrução do usuário); auto-revisão registrada | não | não |
| 7 | sim (Dart não compilado) | backend 366 em PostgreSQL e 357 em SQLite; frontend 60; Dart não executado | **não** (apenas Claude Code, por instrução do usuário); auto-revisão registrada | não | não |

## Modelo
Pedidos de troca de modelo (Opus 5.5 médio para decisões difíceis) são feitos ao usuário via `/model`; nenhum até agora.

## Revisão da etapa 2 (21/10/2026)
Implementada e revisada com correções pelo Codex; conferência do Claude pendente. Backend: 82 testes SQLite; frontend: 25 testes, lint, typecheck e build. Decisão sobre enumeração temporal por e-mail síncrono e validação PostgreSQL permanecem essenciais. Ver [etapas/02-revisao.md](etapas/02-revisao.md). Etapa 3 não iniciada.

## Histórico de pausas
- 2026-10-21 (etapa 3): Codex atingiu limite de uso. Retomada manual autorizada pelo usuário às 23:25 do mesmo dia.
- 2026-10-22 (etapa 6): Codex atingiu limite de uso durante a revisão (renovação informada pela ferramenta: 4:33 AM). Projeto pausado; retomada manual obrigatória.
- 2026-10-22 11:37: retomada manual autorizada pelo usuário. Nova divisão de trabalho: Codex apenas revisa (sandbox somente leitura); Claude implementa, corrige e valida. Ver CLAUDE.md e AGENTS.md.
- 2026-10-22: pausa pedida pelo usuário após a etapa 6. Revisão complementar do Codex não realizada (modelo em capacidade máxima, não é limite de uso). Aguardando retomada manual.
- 2026-10-24: retomada autorizada pelo usuário. Instrução: usar apenas o Claude Code (sem Codex) e parar ao terminar a próxima etapa (etapa 7).
- 2026-10-24: etapa 7 concluída só com o Claude Code. Pausa solicitada pelo usuário: etapa 8 não iniciada.
