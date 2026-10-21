Revise e corrija a etapa 3 (Cadastros da operação) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/decisoes-tecnicas.md (D16–D22) e docs/etapas/03-implementacao.md.

Escopo entregue: app operations (unidades, setores, funcionários, lotação e jornada com vigência, importação CSV, seed_demo), escopo de gestor em Membership, painel React de operação.
Alterações a revisar: `git diff 3fdba9b..HEAD` mais arquivos não commitados.
Verificações já executadas: backend 121 testes e ruff ok (SQLite); frontend 30 testes, lint, typecheck, build ok.
Pendências conhecidas: PostgreSQL/Docker/Flutter ausentes; exclusão de sobreposição de intervalos só no nível de aplicação.

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes.

Foque em: IDOR em todos os endpoints novos (inclusive ids de unidade/setor/jornada enviados no corpo e nos filtros), escopo do gestor (vazamento por filtros, paginação, busca, detalhe, lotação futura/passada), mass assignment, histórico de lotação/jornada (sobreposição, datas iguais/retroativas, concorrência, fechamento do intervalo anterior, lotação futura), inativação sem perda de dados, importação CSV (injeção de fórmula em campos reexibidos, delimitadores, BOM, limites, atomicidade, vazamento entre empresas, linhas/erros), CPF (validação, mascaramento, vazamento em auditoria/logs/respostas), consultas N+1 nas listagens, migrations, e o frontend (permissões na UI, tratamento de erro, estado ao trocar de empresa). Verifique regressões das etapas 1-2.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre proposta e devolva o controle. Sem commit/push.
Execute as verificações afetadas (backend: DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest; ruff; frontend: npm scripts) e registre o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/03-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.
Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso.
