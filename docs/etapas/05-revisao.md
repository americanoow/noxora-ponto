# Etapa 5 — revisão do Codex

Data: 22/10/2026. Base: `git diff ff6323e..HEAD` e alterações locais (o estado de controle já estava modificado). Sem commit/push, sem outra IA e sem início da etapa 6. Não havia pausa ativa.

## Conclusão

**Revisada com correções, mas não aprovada para avanço ou produção.** Os testes locais passam, porém INSERT direto continua capaz de criar marcações arbitrárias, PostgreSQL real não foi executado e Flutter não foi compilado. A proposta abaixo exige decisão de arquitetura; devolvo o controle nesta etapa. Isto não é declaração de conformidade REP-P.

## Problemas e correções

| Problema encontrado | Correção / resultado |
|---|---|
| Data impossível (`2026-02-30`) causava ValueError/500 no filtro | Captura e resposta 400; testes para mês/dia impossíveis |
| `identification.method` como lista/dicionário causava TypeError/500 | Validação textual no serializer e defesa no serviço; quatro casos de regressão |
| Autenticação podia anteceder revogação/renovação concorrente | Serviço atômico bloqueia dispositivo, recarrega credencial e revalida estado/expiração/empresa antes do registro; simulação de credencial obsoleta coberta |
| CPF do empregador exposto no terminal, gestor e auditoria | Máscara nas respostas informativas e omissão na auditoria, incluindo troca CPF → CNPJ. Administrador mantém acesso para cadastro |
| Alterar empregador/endereço/INPI reescrevia o comprovante de registros antigos | Snapshot no INSERT; reenvio e consulta retornam o mesmo comprovante. Legados sem snapshot são sinalizados, sem inventar histórico |
| CNPJ descartava letras e aceitava algarismos Unicode | Validação estrita de caracteres; regressão. Formulário com empregador sem documento agora aceita tipo vazio, coerente com modelo e campos pendentes |
| Validação/atualização do empregador usava estado sem bloqueio | Bloqueio do cadastro antes de validar e auditar, evitando combinação concorrente de tipo e número |
| Divergência de relógio superior a 32 bits causaria falha PostgreSQL | Campo `clock_skew_seconds` passa a BigInteger; teste com ano 9999 |
| Verificador lia contador depois da cadeia, podendo acusar corrupção durante append | Bloqueio do contador antes da leitura; detecta contador não vazio sem registros, versão desconhecida e data local incoerente |
| SQLite REPLACE pode substituir linha sem disparar DELETE | Migration 0004 rejeita INSERT colidindo em PK, unidade/NSR ou dispositivo/evento; teste SQL direto |
| Flutter descartava evento ao alternar matrícula e antes de terminar o parse da resposta | Payload pendente por matrícula; descarte só após construir sucesso; reenvio mantém UUID, horário e tipo |
| Flutter dizia “não registrada” ao receber 401/400/404 após resposta anterior perdida | Mantém estado sem confirmação nesses casos; 400 inicial distingue dados/identificação de matrícula desconhecida |
| Duplo submit do painel e hash curto podiam causar comportamento incorreto | Guarda `_busy` e exibição tolerante a hash curto |
| Flush PostgreSQL dos testes transacionais acionaria o bloqueio de TRUNCATE | Fixture exclusiva dos testes desativa gatilhos de usuário somente durante o flush transacional do banco descartável. Gatilhos ativos durante todos os testes, inclusive teste de TRUNCATE |

## Integridade e limites demonstrados

- Idempotência existente preservada: mesmo evento devolve original, payload divergente não cria novo registro. Eventos distintos continuam independentes. Rollback testado antes de INSERT e depois de INSERT (falha ao salvar contador), seguido de nova marcação sem lacuna.
- Teste preexistente de `bulk_create` forjado permanece: consegue inserir NSR 9/hash arbitrário; `verify_timeclock` detecta lacuna/hash/contador. **Detecção não equivale a prevenção.** Manager base, inserção ORM e SQL novo também não impõem o protocolo de append. Contador é mutável e pode causar indisponibilidade ou cadeia inválida. Hash não autentica o autor e não cobre campos informativos.
- UPDATE/DELETE diretos bloqueados em SQLite; ORM bloqueia update/delete/bulk_update/upsert; FKs PROTECT cobertas para empresa, unidade, funcionário e dispositivo. TRUNCATE não existe no SQLite. Teste específico PostgreSQL foi escrito e ignorado aqui.
- Isolamento de listagem/detalhe/comprovante, filtros e paginação mantido pelos testes existentes. Gestor segue funcionários na lotação atual (D18), podendo ver histórico em outras unidades desses funcionários; isso é a decisão existente, não filtro por unidade histórica. Não há edição de marcação na API ou na aba React.
- Unidade inativada continua permitindo marcação conforme D35; empresa inativa e dispositivo revogado não registram. Identificação exige empregado ativo na unidade conforme D27. Lotação ainda usa data UTC (D20); na meia-noite local, pode divergir da data do ponto. Mudar isso exige decisão explícita de produto e regressões nas etapas 3–4.
- Fusos testados: meia-noite em São Paulo, +05:45, -03:30 e hora repetida no término do horário de verão em Nova York. Offset vem do instante gravado, não do offset atual.
- Flutter: não há persistência dos eventos pendentes após reinício, limite conhecido da etapa 7. Reativar como outro dispositivo também muda o domínio de idempotência; não afirmar deduplicação nessa situação. Fila durável/recuperação de eventos exige tratar esse contrato antes de uso real.

## Verificações e resultados

Ambiente: Windows; backend Python 3.15/Django 6.0.9. Docker, psql e Flutter não localizados no PATH; nenhum instalado. Nenhuma credencial lida.

- Backend, `DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest -p no:cacheprovider`: **255 passaram, 5 ignorados**. Inclui regressões das etapas 1–4. Ignorados: ativação simultânea da etapa 4; TRUNCATE; três cenários de concorrência da etapa 5 (mesmo evento, eventos distintos no mesmo aparelho e aparelhos distintos na mesma unidade).
- `ruff check .` e `ruff format --check .`: aprovados. `manage.py makemigrations --check --dry-run`: sem mudanças.
- Migração SQLite em memória com linha legada: 0002 → migrations atuais; linha/hash preservados, snapshot ausente sinalizado e UPDATE direto rejeitado. Banco persistente/PostgreSQL e downgrade ainda precisam de validação própria.
- Frontend: `npm test` **44 passaram**; `npm run lint`, `npm run typecheck`, `npm run build`: aprovados. Não foi necessário alterar o frontend.
- Dart: cinco testes de regressão adicionados (alternância/payload, resposta incompleta e 400/401/404 após falha). **Não executados**; analyze/test/APK continuam pendentes.
- Durante o trabalho: uma execução intermediária falhou porque a primeira máscara também omitia CNPJ na auditoria; corrigida preservando a asserção existente. Ruff inicialmente apontou formatação/importação/linha longa; corrigidos. Chamada ao alias `python` do Windows falhou; comandos seguintes usaram o executável já existente da venv. Nenhum teste foi enfraquecido.

## Arquivos afetados

- `backend/apps/timeclock/{models,services,views,serializers,receipt,hashing}.py`.
- `backend/apps/timeclock/migrations/0003_receipt_snapshot.py` e `0004_sqlite_replace_guard.py`.
- `backend/apps/timeclock/tests/test_timeclock.py` e `backend/conftest.py`.
- `tablet/lib/device_controller.dart`, `tablet/lib/punch_panel.dart`, `tablet/test/device_controller_test.dart`.
- Este relatório, `docs/requisitos-rep-p.md`, `docs/decisoes-tecnicas.md`, `docs/progresso.md` e `docs/controle/estado.json`.

## Pendências essenciais e proposta para decisão

1. **Prevenir INSERT arbitrário e adulteração do contador.** Proposta: rotina exclusiva de append no PostgreSQL que valide tenant/FKs, aloque NSR e calcule cadeia sob o mesmo bloqueio/transação; usuário de aplicação sem INSERT/UPDATE/DELETE direto em ARP/contador, apenas EXECUTE na rotina; proprietário de migrations separado. Incluir testes com o papel real da aplicação, SQL forjado, rollback e concorrência. Isso desloca a autoridade de escrita para o banco e altera provisionamento; não foi implementado sem decisão. Um gatilho que apenas compare o contador não basta se o mesmo papel puder editar esse contador.
2. Executar testes PostgreSQL 17 com migrations e gatilhos reais, inclusive concorrência sob carga, contador inicialmente ausente e rollback. SQLite não prova `select_for_update`. A fixture de flush também precisa ser validada nesse banco.
3. Compilar/analisar/testar Flutter com SDK compatível e Android real; confirmar fluxo após timeout, revogação, troca de trabalhador e reinício. Não há evidência de compilação nesta revisão.
4. Resolver divergência do preenchimento do hash e obter vetor validado; decidir ARP completa/NSR de outros tipos e unidade versus estabelecimento. Conferência da fonte oficial e dúvidas estão em [requisitos-rep-p.md](../requisitos-rep-p.md), seção 3. Algoritmo histórico não foi modificado.
5. Snapshot legado inexistente não pode ser reconstruído com segurança. Se já houver dados reais, definir procedimento de tratamento antes de migrar. Novas migrations alteram esquema e reinstalam gatilhos atomicamente; executar com papel de migrations e validar em banco persistente.
6. Persistem requisitos externos: PDF/PAdES, certificados, INPI/Atestado, identificação suficiente, sincronismo HLB, disponibilidade/backup e validação especializada. CPF mascarado no JSON não satisfaz por si só o comprovante oficial.

## Melhorias opcionais

- Acrescentar aviso operacional para pendências de cadastro e link de detalhe/comprovante na listagem React.
- Medir tempo de bloqueio por unidade e monitorar verificação da cadeia sem dados pessoais nos logs.
- Evoluir o verificador para diagnosticar todo campo inválido inserido fora do serviço, em vez de poder interromper ao encontrar valores impossíveis; não substitui a prevenção no banco.
