Revise e corrija a etapa 6 (Reconhecimento facial) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/avaliacao-motor-biometrico.md, docs/requisitos-rep-p.md, docs/decisoes-tecnicas.md (D43-D51) e docs/etapas/06-implementacao.md.

IMPORTANTE: o motor biométrico real está BLOQUEADO por decisão de produto (custo/licença). O simulador existe só para testes e não comprova eficácia. Não implemente algoritmo biométrico próprio, não contrate serviço, não adicione dependências de modelos. Sua tarefa é revisar e corrigir a infraestrutura em volta do motor.

Escopo entregue: app biometrics (consentimento, template AES-256-GCM, tentativas, exceção autorizada por código, retenção), contrato BiometricEngine, endpoints do painel e do tablet, provedores `face` e `authorized_exception` na marcação, política por empresa, UI React e métodos Dart.
Alterações a revisar: `git diff 52ab49a..HEAD` mais arquivos não commitados.
Verificações já executadas: backend 285 testes em SQLite e 289 em PostgreSQL 17.5 real (.local via tools/postgres_local.ps1; porta 5433; DATABASE_URL=postgres://noxora@127.0.0.1:5433/noxora); frontend 51 testes, lint, typecheck, build ok.
Pendências conhecidas: motor real; câmera no tablet; Flutter não compilado; KMS; base legal.

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes.

Foque em tentar QUEBRAR a proteção dos dados e o fluxo de identificação: vazamento de template/chave/imagem (respostas, logs, auditoria, tracebacks, repr, admin do Django, backups, migrations), criptografia (nonce, AAD, rotação, falha de chave, comparação), reuso/expiração/corrida do token de verificação (duas marcações simultâneas com o mesmo token; token de outro dispositivo, funcionário, empresa), bloqueio por tentativas (contorno por matrícula alternada, janela, concorrência), código de exceção (força bruta, enumeração, reuso, entropia, vínculo ao funcionário, canal de exposição, quem pode gerar), política por empresa (contorno do modo facial por método desconhecido, tipos inesperados no JSON), simulador em produção (todas as portas de entrada), IDOR/escopo (gestor fora do escopo, outra empresa, plataforma), consentimento/revogação/exclusão (template realmente apagado? histórico?), limites de tamanho e base64, DoS por imagens grandes, ordem das transações (consumo do token + gravação), regressões das etapas 1-5, e o frontend (nunca guardar imagem em storage; código exibido uma vez). Confira se `python manage.py check --deploy` e a configuração de produção recusam combinações inseguras de biometria.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre a proposta e devolva o controle. Sem commit/push.
Execute as verificações afetadas (backend: DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest -p no:cacheprovider; se o PostgreSQL local estiver de pé em 127.0.0.1:5433, repita com ele; ruff; frontend: npm scripts) e registre o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/06-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.
Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso.
