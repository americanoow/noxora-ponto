# Etapa 7 — Operação offline e sincronização

**Status: EM ANDAMENTO (checkpoint de retomada; backend CONCLUÍDO (SQLite 357, PostgreSQL 366) e frontend CONCLUÍDO (60 testes)).** Só Claude Code (instrução do usuário em 2026-10-24: sem Codex nesta etapa). **Parar ao concluir esta etapa; não iniciar a etapa 8.** O checklist abaixo é a fonte para retomar em outra sessão.

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
- [ ] Tablet (Dart): `OfflineQueue` + armazenamento seguro, integração no `DeviceController` (enfileirar sem rede, sincronizar, 401/403/429/5xx, escopo persistido, amostra de relógio), indicação de pendências na UI, testes (não executáveis: Flutter ausente)
- [ ] Documentos: decisões D52+, requisitos-rep-p.md (offline), avaliacao-motor-biometrico.md (alternativa offline), este arquivo (resultados), progresso e estado
- [ ] Auto-revisão do Claude (sem Codex) e verificação final: SQLite, PostgreSQL, ruff, migrations, frontend
- [ ] Commit final, estado `pausado` ("parar após a etapa 7") e aviso ao usuário
