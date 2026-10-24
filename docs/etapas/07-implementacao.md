# Etapa 7 — Operação offline e sincronização

**Status: IMPLEMENTADA; sem revisão do Codex (instrução do usuário: apenas Claude Code). Dart NÃO compilado/testado (Flutter ausente).** Só Claude Code (instrução do usuário em 2026-10-24: sem Codex nesta etapa). Parada solicitada ao concluir a etapa: a etapa 8 **não** foi iniciada.

## Decisões de desenho (já tomadas)
1. **Reconhecimento facial não funciona offline** (nenhum motor foi validado em Android; template no aparelho amplia a exposição). Alternativa definida: marcação offline **por matrícula**, gravada como `registration_offline` e **sinalizada para revisão**, e só se o administrador habilitar `Company.offline_policy = registration_only` (padrão `disabled`). Não é identificação forte; vale também para empresas em modo `face` (rebaixamento deliberado e visível).
2. **Servidor**: `POST /api/device/punches/batch/` recebe até `OFFLINE_BATCH_MAX` (50) eventos e devolve **resultado individual**: `confirmed` | `duplicate` | `rejected` (+ motivo, flags, registro/comprovante). Idempotente por `(dispositivo, client_event_id)`; cada evento em sua transação (`Device → Employee → NsrCounter`); falha de autenticação interrompe o lote com 401/403 e os já gravados permanecem (reenvio devolve `duplicate`).
3. **Horário**: o tablet envia `device_reported_at` (horário original) e o último desvio medido contra o servidor (`clock_offset_seconds` = servidor − aparelho, `offset_measured_at` = horário do servidor na medição). O servidor corrige `occurred_at = device_reported_at + offset`; `recorded_at` = recebimento. Flags: `clock_unverified` (sem desvio), `clock_skew_large` (|desvio| > 30 s), `clock_offset_stale` (medição > 24 h), `time_in_future` (limitado ao recebimento), `before_device_activation`. Mais antigo que 35 dias → **recusado** (`too_old`). `clock_skew_seconds` = aparelho − servidor (= −desvio).
4. **Funcionário**: matrícula inexistente na empresa → `rejected: unknown_registration` (fica visível no tablet, não some). Inativo ou sem lotação na unidade na data do evento → **aceito e sinalizado** (`employee_inactive`, `not_assigned_to_unit`): não se perde marcação.
5. **Credencial**: revogada/expirada → 401 e a **fila permanece** no tablet; após reativação (novo código do mesmo cadastro) a fila é enviada. Sem tolerância de credencial expirada.
6. **NSR segue a ordem de recebimento, não a cronológica** (limite inerente; o horário real está em `occurred_at`).
7. **Fila no tablet**: persistente (armazenamento seguro do Android), estados `pending → sent → confirmed | rejected`, recuperação após reinício (`sent` volta a `pending`), lote parcial tratado por evento, JSON corrompido é **posto em quarentena, nunca descartado**, limite de 2000 eventos. Proteção em repouso **não** garante integridade contra aparelho com root: controles compensatórios são as flags e a revisão no servidor.
8. **Comprovante offline**: o tablet mostra confirmação **provisória** (sem NSR/hash); o comprovante com NSR só existe após a sincronização. Pendência para validação especializada (Anexo IX, item 5 e art. 80).

## Checklist
- [x] Campos: `TimeRecord.sync_flags`, `Company.offline_policy`, settings `OFFLINE_*`; migration 0005 preserva gatilhos (verificado em SQLite e PostgreSQL)
- [x] Backend: `_insert` aceita `occurred_at`, `offline`, `sync_flags`, skew; `resolve_offline_time`; `process_offline_event`; endpoint `punches/batch/`; auditoria por lote
- [x] Backend: política `offline_policy` no endpoint de identificação; `offline_policy` e `identification_mode` no escopo do dispositivo; `sync_flags` e filtro `offline` no histórico
- [x] Backend: testes (lote feliz, reenvio idempotente, parcial, política desligada, regras de horário, funcionário inativo/outra empresa/sem lotação, revogado/expirado/reativado, duplicado no mesmo lote, limites, concorrência PostgreSQL, imutabilidade preservada, cadeia de hash válida)
- [x] Frontend: rótulos das flags, seletor `offline_policy`, filtro offline, testes
- [x] Tablet (Dart): `OfflineQueue` + armazenamento seguro, integração no `DeviceController` (enfileirar sem rede, sincronizar, 401/403/429/5xx, escopo persistido, amostra de relógio), indicação de pendências na UI, testes (não executáveis: Flutter ausente)
- [x] Documentos: decisões D52+, requisitos-rep-p.md (offline), avaliacao-motor-biometrico.md (alternativa offline), este arquivo (resultados), progresso e estado
- [x] Auto-revisão do Claude (sem Codex) e verificação final: SQLite, PostgreSQL, ruff, migrations, frontend
- [x] Commit final, estado `pausado` ("parar após a etapa 7") e aviso ao usuário

## Entregue
- **Backend**: `POST /api/device/punches/batch/` (lote idempotente, resultado por evento), `process_offline_event`, `resolve_offline_time`, flags em `sync_flags`, política `offline_policy` (PATCH `/identification/`), escopo do dispositivo com `offline_policy`, histórico com `sync_flags` e filtro `offline`, auditoria do lote (`device.offline_sync`, só contagens). Migrations `timeclock.0005` (preserva gatilhos) e `companies.0006`.
- **Painel**: rótulos legíveis das sinalizações, filtro de origem (online/offline), seletor da política offline com aviso das limitações.
- **Tablet (Dart)**: `OfflineQueue` persistente (armazenamento seguro, recuperação, quarentena, limite), integração no `DeviceController` (enfileirar quando não há resposta, sincronizar após heartbeat/ativação/manual, tratar 401/403/429/5xx e lote parcial, escopo e desvio de relógio em cache, operar após reinício sem conexão), indicação visual de pendências e recusas, confirmação provisória.

## Verificações executadas (somente pelo Claude)
| Verificação | Resultado |
|---|---|
| Backend, SQLite em memória | 357 passam, 10 ignorados |
| Backend, PostgreSQL 17.5 real (inclui lotes simultâneos) | **366 passam**, 1 ignorado (específico do SQLite) |
| `ruff check`, `ruff format --check`, `makemigrations --check` | limpos |
| Migrations novas sobre o banco de desenvolvimento já populado + `verify_timeclock` | aplicadas; cadeias íntegras |
| Frontend: testes, lint, typecheck, build, prettier | 60 testes; tudo limpo |
| Dart (analyze/test) — 31 testes novos | **não executados**: Flutter ausente |

## Critérios de aceite (situação)
- Queda de conexão não elimina eventos já persistidos: **atendido no backend e no desenho do tablet** (testado no backend; no Dart só por testes não executados).
- Reenvios não duplicam: **atendido e testado** (idempotência por evento, inclusive concorrência em PostgreSQL).
- Confirmações parciais tratadas: **atendido e testado** no backend; no Dart, testes escritos e não executados.
- Reinicialização preserva a fila: **desenhado e testado só em Dart não executado**; **não demonstrado em Android real**.
- Limitações técnicas e normativas documentadas: **sim** (D52–D61; requisitos-rep-p.md seção 3).

## Pendências
- Compilar, analisar e testar o Dart; validar o armazenamento seguro e o reinício em Android real.
- Revisão do Codex da etapa 7 **não realizada** (instrução do usuário); pode ser pedida depois.
- Validações especializadas listadas em requisitos-rep-p.md seção 3.
- Limite diário de eventos offline por aparelho; revisão e ajuste das marcações sinalizadas (etapa 9).
