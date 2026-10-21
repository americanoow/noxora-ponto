# Etapa 3 — Revisão do Codex

Revisão em 21/10/2026 sobre `git diff 3fdba9b..HEAD` e alterações locais. Estado inicial sem pausa obrigatória. Nenhum commit, push, acionamento de outra IA ou avanço de etapa.

## Problemas encontrados e correções

1. **Gestor sem escopo acessava todas as jornadas da empresa**, inclusive por detalhe. Listagem e detalhe agora restringem jornadas às atribuídas a funcionários visíveis pela lotação atual. Inclui jornadas históricas/futuras desses funcionários, coerentemente com os endpoints de histórico; não concede acesso a funcionários fora do escopo.
2. **D21 não era cumprida:** `commit=true` podia gravar sem prévia. O servidor agora exige prévia válida do mesmo conteúdo na mesma sessão e empresa. Armazena somente SHA-256 na sessão, revalida na gravação e remove a autorização após sucesso. A UI bloqueia importar antes da prévia, durante envio e após editar o conteúdo.
3. **CSV aceitava estrutura ambígua e podia gerar 500:** cabeçalhos duplicados, campos excedentes descartados, campos ausentes, aspas malformadas e `csv.Error` sem tratamento. Parser estrito rejeita esses casos, suporta BOM/vírgula/ponto e vírgula/campos entre aspas e informa linhas físicas, inclusive após campos multilinha. Limite corrigido para 1.000.000 bytes UTF-8, além de 2.000 registros.
4. **Fórmulas em campos importados persistiam para reexibição.** Prefixos `=`, `+`, `-` e `@`, após espaços de borda, passam a gerar erro por linha/campo. Mensagens não repetem matrícula/unidade/setor enviados. React já exibia texto escapado; uma futura exportação de planilha deverá aplicar sua própria proteção.
5. **Conflito entre validação e gravação CSV podia expor erro interno.** `IntegrityError` agora retorna 400 genérico, com rollback integral, sem detalhes do banco ou CPF. O teste injeta conflito após uma inclusão e comprova rollback; não equivale a concorrência PostgreSQL.
6. **Atribuição de jornada não adquiria o mesmo bloqueio da edição de dias.** O serviço agora bloqueia a jornada antes do funcionário, serializando atribuição e edição no PostgreSQL. Unidade/setor/jornada também têm situação ativa relida sob bloqueio, evitando aceitar objetos carregados antes da inativação. A garantia concorrente ainda precisa ser executada em PostgreSQL.
7. **PATCH de jornada com dias incompletos podia gerar `KeyError`/500.** Cada item de substituição exige dia, início e fim; erro 400 preserva os dias existentes.
8. **Filtros com dígitos Unicode não conversíveis podiam gerar 500.** IDs de filtro aceitam apenas decimal ASCII positivo no intervalo de bigint; entradas inválidas retornam lista vazia.
9. **Listagem de membros ganhou duas consultas adicionais por membro** com os escopos M2M. Adicionado prefetch; testes com crescimento de funcionários e membros verificam quantidade constante de consultas.
10. **Buscas concorrentes no frontend podiam exibir resposta antiga sobre filtros novos.** Carregadores descartam respostas superadas e limpam dados ao recarregar. O componente também reinicia estado por empresa/permissão, apresenta erros de unidades/setores e condiciona o formulário de lotação à permissão atual.

## Pontos conferidos sem mudança de requisito

- Endpoints operacionais resolvem empresa e papel; plataforma não recebe acesso operacional. IDs de unidade/setor/jornada no corpo e escopos de Membership são resolvidos na própria empresa. Novos testes cobrem escrita em históricos de outra empresa, alteração de jornada alheia e rollback de escopo parcialmente válido.
- Filtros, busca e paginação operam após o escopo. Datas futuras não antecipam acesso; na mudança de vigência o antigo gestor perde detalhe/histórico. Funcionário sem lotação atual fica invisível ao gestor.
- Matrícula, empresa, usuário vinculado por ID, timestamps e ID não podem ser atribuídos arbitrariamente. Inativação preserva históricos; DELETE de funcionário não existe.
- CPF mantém validação dos verificadores, máscara em listas e detalhe de gestor, e valor completo nas respostas administrativas previstas. Auditoria operacional registra IDs/campos alterados, sem valores de CPF ou conteúdo CSV.
- Intervalos novos exigem início posterior ao mais recente e fecham o anterior na véspera; datas iguais/anteriores são rejeitadas. Datas anteriores a hoje, mas posteriores à última vigência, continuam permitidas conforme D17.
- D16 protege os **dias** de jornada atribuída. Renomeação e inativação continuam permitidas, conforme comportamento e teste entregues; não alteram horários históricos.
- Migrations aditivas e dependências entre `operations.0001` e `companies.0003` conferidas. `seed_demo` continua limitado a DEBUG e idempotente no cenário coberto pelo teste existente.

## Arquivos afetados

- `backend/apps/operations/{importing,serializers,services,views}.py`
- `backend/apps/companies/views.py`
- `backend/apps/operations/tests/test_review.py` (29 novos casos)
- `frontend/src/Operations.tsx` e `frontend/src/Operations.test.tsx` (3 novos casos)
- `docs/etapas/03-revisao.md`, `docs/decisoes-tecnicas.md`, `docs/progresso.md`, `docs/controle/estado.json`

## Testes e resultados

Backend com `DJANGO_DEBUG=true` e `DATABASE_URL=sqlite:///:memory:`:

| Verificação | Resultado |
|---|---|
| `.venv\Scripts\python -m pytest -p no:cacheprovider` | **150 passaram**, incluindo regressões das etapas 1–2 e seed_demo |
| `.venv\Scripts\python -m ruff check .` | Passou |
| `manage.py check` | Sem problemas |
| `manage.py makemigrations --check --dry-run` | Sem alterações pendentes |
| `manage.py migrate --noinput` | Todas aplicadas em SQLite em memória |
| Frontend `npm test` | **33 passaram**, 5 arquivos |
| `npm run lint`, `npm run typecheck`, `npm run build`, `npm run format:check` | Passaram |
| `git diff --check` | Sem erros de whitespace; avisos LF/CRLF do Git |

O cache pytest existente não era acessível no sandbox; usado `-p no:cacheprovider`, sem desativar testes. Na preparação, dois parâmetros gigantes geraram erros de setup pelo tamanho dos identificadores; corrigidos com IDs curtos, mantendo os conteúdos e asserções. Ruff apontou importação/formatação dos novos testes e ESLint um aviso no cleanup do carregador; corrigidos antes da execução final.

## Pendências essenciais

- **PostgreSQL real indisponível:** executar migrations e concorrência de duas atribuições ao mesmo funcionário, edição versus atribuição de jornada, inativação versus atribuição e importações simultâneas. SQLite não valida `select_for_update`, deadlocks, collation nem garantias concorrentes.
- Exclusão de sobreposição no banco continua ausente conforme D17. Proteções de aplicação e unicidade não protegem escrita SQL/ORM que contorne os serviços.
- Docker, `psql` e Flutter não encontrados no PATH; CI não executada. Pendências herdadas de banco persistente, SMTP, MFA e cache compartilhado permanecem no estado.
- Conferência das correções pelo responsável da implementação, sem início automático da próxima etapa.

## Melhorias opcionais

- Paginar catálogos/históricos e carregar apenas a lotação corrente na listagem quando o volume justificar; não há N+1 por funcionário, mas o prefetch ainda carrega seu histórico completo.
- Evoluir a UI para administrar escopos, atribuir jornadas e consultar históricos, hoje disponíveis por API; o painel entregue cobre criação de jornadas e alteração de lotação.
- Automatizar testes concorrentes em PostgreSQL na CI e avaliar mensagens por linha para conflitos surgidos somente durante gravação.

## Conclusão

Etapa 3 revisada e corrigida no escopo autorizado, com verificações locais aprovadas. Pronta para conferência das alterações, **sem afirmar validação PostgreSQL, implantação ou conformidade legal**. Nenhuma mudança grande de arquitetura foi necessária. Validações especializadas previstas para REP-P/LGPD continuam fora desta etapa.
