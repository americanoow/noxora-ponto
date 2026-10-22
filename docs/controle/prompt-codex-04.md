Revise e corrija a etapa 4 (Autorização e gestão dos tablets) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/decisoes-tecnicas.md (D23–D29) e docs/etapas/04-implementacao.md.

Escopo entregue: app devices (ativação por código temporário, credencial individual com rotação/revogação, API do tablet com consulta de matrícula limitada à unidade, localização opt-in), painel React (aba Tablets) e código Flutter (token_store, device_controller, main) NÃO compilado.
Alterações a revisar: `git diff b086545..HEAD` mais arquivos não commitados.
Verificações já executadas: backend 182 testes e ruff ok (SQLite); frontend 38 testes, lint, typecheck, build ok.
Pendências conhecidas: Flutter/Docker/PostgreSQL ausentes; revogação offline limitada pela validade da credencial.

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes.

Foque em tentar QUEBRAR a autenticação do dispositivo: força bruta/enumeração do código de ativação, reutilização/corrida na ativação (duas ativações simultâneas do mesmo código), token forjado/truncado/de outro dispositivo, comparação em tempo constante, credencial que continua válida após revogação/renovação/expiração, janela de rotação (abuso, encadeamento infinito de credenciais), dispositivo acessando outra empresa/unidade (IDOR por corpo, querystring ou ids), consulta de matrícula como oráculo de enumeração, vazamento de código/token em logs/auditoria/respostas/migrations, escopo do gestor nos endpoints de dispositivos, constraint e validação de localização, transações e auditoria, throttling (chave de cache, bypass por cabeçalhos), e regressões das etapas 1–3. No Dart, leia com cuidado compilação, tratamento de erros, uso do armazenamento seguro e race conditions (heartbeat/rotação concorrentes). No frontend, o código de ativação só pode viver em estado local.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre proposta e devolva o controle. Sem commit/push.
Execute as verificações afetadas (backend: DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest -p no:cacheprovider; ruff; frontend: npm scripts) e registre o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/04-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.
Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso.
