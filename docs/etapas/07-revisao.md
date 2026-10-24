# Etapa 07 — Revisão (Operação offline e sincronização)

> **O Codex NÃO revisou esta etapa.** Em 2026-10-24 o usuário determinou que a retomada use apenas o Claude Code. Abaixo está a **auto-revisão do Claude** (não é revisão independente, e não há aprovação do Codex). Uma revisão do Codex continua desejável (a etapa mexe em integridade das marcações e em autenticação de dispositivo) e pode ser pedida quando o usuário autorizar.

## Auto-revisão: o que foi examinado
- **Backend** (`apps/timeclock/services.py`, `views.py`, `serializers.py`): ordem de bloqueios (`Device → Employee → NsrCounter`, igual à marcação online, com `FOR NO KEY UPDATE`); idempotência antes da política (um evento já gravado continua `duplicate` mesmo se a política for desligada depois); corrida entre lotes iguais (teste em PostgreSQL); horário (`occurred ≤ recorded` sempre); cadeia de hash válida com registros online e offline; rejeição sem gravar; autenticação que interrompe o lote sem perder o que já foi gravado.
- **Dart** (`offline_queue.dart`, `device_controller.dart`, `punch_panel.dart`, `main.dart`): persistência antes de dar a marcação como guardada, falha de gravação, recuperação após reinício, quarentena, lote parcial, 401 com fila preservada e reativação.

## Defeitos encontrados na auto-revisão
1. **Laço infinito de reenvio (Dart) — CONFIRMADO por leitura e corrigido.** Se o servidor respondesse 200 sem resultado definitivo para nenhum evento do lote, os eventos voltavam a `pending` e `syncPending` reenviava sem fim. Correção: parar quando o lote não produziu nenhum resultado definitivo. Teste de regressão: `lote sem nenhum resultado definitivo não gera laço infinito de reenvio` (escrito, **não executado**).
2. **Mensagem e escopo em cache na revogação (Dart) — corrigido.** Os caminhos de 401 de `punch()` e `verifyFace()` não limpavam o escopo em cache nem avisavam que as marcações pendentes continuam guardadas; agora usam o mesmo tratamento do heartbeat.
3. **Migration (backend) — corrigido antes de commitar.** A migration gerada pelo Django para `sync_flags` não preservava os gatilhos de imutabilidade no SQLite (que reconstrói a tabela); foi reescrita para removê-los e reinstalá-los (testes de SQL direto continuam passando nos dois bancos).

## Riscos aceitos (registrados em decisoes-tecnicas.md)
- D56: a credencial de um tablet pode lançar marcações offline de qualquer funcionário da empresa por até 35 dias (todas sinalizadas, política desligada por padrão); sem limite diário por aparelho.
- D54: o horário offline é uma estimativa corrigida pelo desvio medido, não prova da Hora Legal Brasileira.
- D58: proteção da fila em repouso não é prova de integridade em aparelho com root.

## Testes executados e resultados
Ver `07-implementacao.md` (backend: SQLite 357 / PostgreSQL 366; frontend 60; Dart **não executado**).

## Pendências
- Dart sem compilação e sem teste; armazenamento seguro e reinício não validados em Android real.
- Revisão do Codex da etapa 7 não realizada.
- Validações especializadas (requisitos-rep-p.md, seção 3).

## Revisão complementar necessária?
Não houve revisão principal do Codex. **Recomendada** uma revisão do Codex sobre `process_offline_event`/`resolve_offline_time` (integridade e autenticação) e sobre o fluxo Dart, quando o uso do Codex for autorizado novamente.
