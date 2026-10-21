Revise e corrija a etapa 1 (Estrutura inicial) do Noxora Ponto.

Leia AGENTS.md, CLAUDE.md, docs/controle/estado.json, docs/plano.md e docs/etapas/01-implementacao.md.

Escopo entregue: backend Django/DRF (health, ready, usuário customizado por e-mail), frontend React/Vite, app Flutter (não compilado: sem SDK), docker-compose com PostgreSQL, CI, README.
Alterações a revisar: todo o repositório (ainda sem histórico além do commit inicial desta etapa).
Verificações já executadas: pytest 4 ok (SQLite), ruff ok, frontend lint/typecheck/vitest/build ok.
Pendências conhecidas: Docker e Flutter ausentes; CI nunca rodou.

Você está autorizado a corrigir diretamente defeitos dentro desta etapa, ajustar documentação e adicionar testes relevantes.

Inspecione o código real. Verifique funcionamento, segurança de configuração (SECRET_KEY, DEBUG, ALLOWED_HOSTS, cookies), migrations, contratos dos endpoints, risco do modelo de usuário customizado para etapas futuras, corretude do código Dart (leitura cuidadosa, já que não compila aqui) e do workflow de CI.

Não remova requisitos nem enfraqueça testes. Sem refatorações alheias. Mudança grande de arquitetura/custo/produto: registre a proposta e devolva o controle.
Não instale ferramentas globais nem faça commit/push. Execute as verificações afetadas (backend: `.venv\Scripts\python -m pytest`, ruff; frontend: npm scripts) e registre exatamente o que passou, falhou ou não pôde ser executado.

Atualize docs/etapas/01-revisao.md com: problemas encontrados, correções, arquivos afetados, testes e resultados, pendências essenciais, melhorias opcionais, conclusão.

Não inicie outra etapa nem acione outra IA. Respeite a regra de pausa por limites de uso e não tente contornar bloqueios.
