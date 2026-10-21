Revise e corrija a etapa 2 (Empresas, autenticação e permissões) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/decisoes-tecnicas.md (D6–D12) e docs/etapas/02-implementacao.md.

Escopo entregue: apps companies/audit, extensão de accounts, API de auth e de empresas/vínculos/auditoria, middleware de sessão absoluta, frontend de login e gestão de acessos.
Alterações a revisar: `git diff 95a32ae..HEAD` mais arquivos não commitados (frontend, docs).
Verificações já executadas: backend 64 testes e ruff ok (SQLite); frontend 19 testes, lint, typecheck, build ok.
Pendências conhecidas: Docker/Flutter ausentes; MFA e escopo por unidade/setor adiados (D11).

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes.

Foque em tentar QUEBRAR o isolamento: acesso cruzado por id (IDOR) em qualquer endpoint, autoelevação, mass assignment, enumeração de usuários (login, reset, convite), CSRF, fixação/expiração de sessão, token de reset reutilizável, vazamento de segredos em auditoria/logs/respostas, comportamento de usuário inativo ou vínculo/empresa desativados, condições de corrida (ex.: vínculo duplicado), migrations, e regressões na etapa 1. Verifique também se o frontend trata 403/429 e rotação do CSRF.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre proposta e devolva o controle. Sem commit/push.
Execute as verificações afetadas (backend: DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: .venv\Scripts\python -m pytest; ruff; frontend: npm scripts) e registre o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/02-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.
Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso.
