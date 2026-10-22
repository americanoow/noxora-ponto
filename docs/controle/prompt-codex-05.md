Revise e corrija a etapa 5 (Núcleo de marcação de ponto) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/requisitos-rep-p.md (fonte dos requisitos: Portaria MTP 671/2021, arts. 73-91 e Anexo IX), docs/decisoes-tecnicas.md (D30-D40) e docs/etapas/05-implementacao.md.

Escopo entregue: app timeclock (TimeRecord imutável, NSR por unidade, hash SHA-256 encadeado, idempotência, gatilhos de imutabilidade no banco, comprovante informativo, painel somente leitura), dados do empregador, contrato de identificação, abas React e fluxo de marcação Flutter (não compilado).
Alterações a revisar: `git diff ff6323e..HEAD` mais arquivos não commitados.
Verificações já executadas: backend 233 testes (1 ignorado) e ruff ok (SQLite); frontend 44 testes, lint, typecheck, build ok.
Pendências conhecidas: Docker/PostgreSQL/Flutter ausentes; o layout vigente do AFD está no portal gov.br e não foi consultado (só a versão histórica do texto consolidado).

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes. Se tiver acesso à web, pode conferir fontes oficiais, mas NÃO invente regras: registre divergências e dúvidas em docs/requisitos-rep-p.md.

Foque em tentar QUEBRAR a integridade: marcação perdida ou duplicada (reenvio, corrida entre dois envios do mesmo client_event_id, falha após alocar NSR, rollback), lacunas ou repetição de NSR sob concorrência (select_for_update em PostgreSQL; SQLite não prova), cadeia de hash quebrável por escrita direta, gatilhos (cobrem UPDATE/DELETE/TRUNCATE? e INSERT com NSR/hash arbitrário?), alteração indireta (FKs, cascatas, PROTECT, bulk operations, caminhos de QuerySet/Manager), vazamento entre empresas/unidades (painel, detalhe, comprovante, filtros, paginação), escopo do gestor, CPF completo em respostas/logs/auditoria, fusos e datas (occurred_local_date, horário de verão, meia-noite, offsets negativos/fracionários), validação do formato DH e do hash contra o texto do Anexo (docs/requisitos-rep-p.md), comportamento com unidade/empresa/dispositivo inativos, e regressões das etapas 1-4. No Dart, leia com cuidado compilação, idempotência do evento no reenvio e tratamento de 401/404/400. No frontend, garanta que não existe controle de edição de marcação.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre a proposta e devolva o controle. Sem commit/push.
Execute as verificações afetadas (backend: DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest -p no:cacheprovider; ruff; frontend: npm scripts) e registre o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/05-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.
Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso.
