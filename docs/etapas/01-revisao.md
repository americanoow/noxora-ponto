# Etapa 1 — Revisão do Codex

Data: 2026-10-21. Escopo: estrutura inicial completa, incluindo backend, frontend,
tablet, migrations, Compose, CI, documentação e script de passagem. Código real
inspecionado; nenhuma outra etapa iniciada. Não houve commit, push, instalação global
ou acionamento de outra IA. O estado não indicava pausa. A alteração prévia de
`docs/controle/estado.json` foi preservada ao atualizar os campos de acompanhamento.

## Problemas encontrados e correções

1. **Exceção do banco nos logs:** `logger.exception` em `/api/ready/` registrava a
   mensagem completa da exceção, que pode conter dados de conexão. Substituído por
   evento genérico sem traceback nem texto da exceção. Regressão verifica a resposta
   503 e o conteúdo dos logs com uma exceção contendo um segredo fictício.
2. **Configuração fora de debug permissiva:** aceitava chave em branco/espaços,
   chave de exemplo, fallback SQLite, hosts `*` e desativação dos cookies seguros.
   Agora exige chave com mínimo de 50 caracteres e 5 distintos, PostgreSQL, hosts
   não vazios sem `*` e cookies Secure fora de debug. A chave deve ser aleatória;
   a validação estrutural não comprova entropia. DEBUG continua falso por padrão.
   Desenvolvimento explícito com DEBUG permite SQLite e a chave local existente.
3. **Modelo de usuário:** `create_superuser` aceitava flags administrativas falsas;
   e-mails eram normalizados só pelo manager e o login não seguia essa normalização.
   Corrigidas as flags, rejeitado e-mail vazio/espaços, normalização em `clean/save`
   e busca de autenticação sem diferença de caixa. A migration aditiva `0002`
   introduz unicidade de `Lower(email)` no banco, inclusive para inserção em lote.
   A migration inicial foi preservada.
4. **Falso sucesso nos clientes:** frontend e Dart aceitavam JSON sem campos do
   contrato e exibiam `undefined`/`null` como sucesso. Ambos exigem `status=ok`
   em saúde/prontidão e `database=ok` na prontidão. O frontend passou a limitar
   cada requisição a 8 segundos, preservando cancelamento ao desmontar.
5. **Ciclo de vida Flutter:** o cliente HTTP interno era criado em `build` e não
   fechado. Agora pertence ao estado da página e é fechado no descarte; clientes
   injetados continuam sob responsabilidade de quem os fornece. Adicionados testes
   Dart para respostas inválidas e falha de rede, ainda não executados.
6. **Preparação Flutter/CI incompleta:** o teste de contador gerado pelo SDK não
   corresponde ao app Noxora; o workflow agora remove apenas esse teste gerado,
   mantém os testes do produto, configura Java 17 e inclui build APK debug.
   Manifesto debug versionado permite INTERNET e HTTP local. CI tem permissões
   mínimas de leitura e cache pip acompanha ambos os arquivos de requisitos.
7. **Documentação operacional:** copiar `.env` não carregava configuração no Django.
   README esclarece variáveis de processo, SQLite apenas em debug, contratos dos
   endpoints, HTTPS/cookies e necessidade de roteamento `/api` no build estático.
   README do tablet registra geração Android, remoção do teste gerado, build debug
   e configuração para dispositivo físico. Caches e staticfiles foram ignorados.

## Inspeções e limites do escopo

- `health` é público e independente de banco; `ready` faz `SELECT 1`, retorna 200
  ou 503 e não demonstra que migrations foram aplicadas. Métodos de escrita são
  rejeitados. A permissão padrão DRF continua `IsAuthenticated`; as duas exceções
  públicas são explícitas. Não há APIs de empresas, marcações ou biometria nesta etapa.
- `AUTH_USER_MODEL` existe desde a migration inicial; dependências de auth/admin
  e a migration nova aplicaram sem inconsistências no SQLite vazio.
- O usuário permanece uma identidade global com e-mail único, separado do funcionário.
  Na etapa 2, validar vínculos de uma identidade com empresas e papéis por vínculo;
  não usar `is_staff/is_superuser` como autorização de cliente nem confiar em empresa
  recebida do frontend. Nenhuma arquitetura multiempresa foi antecipada nesta revisão.
- Métodos do manager não executam validadores de senha automaticamente, conforme o
  padrão Django: os futuros fluxos de cadastro/troca devem fazê-lo. O usuário ainda
  não está registrado em um admin personalizado; não foi criado CRUD nesta etapa.
- Dart foi lido manualmente: inicializadores `late` que acessam `widget` são válidos,
  assim como classes sealed, promoção de tipos após checagem de Map e FutureBuilder.
  Leitura estática não substitui analyze, testes, build ou teste no dispositivo.
- Compose limita a publicação de PostgreSQL ao loopback, usa volume persistente e
  healthcheck. As credenciais de exemplo são apenas locais. Não há servidor de
  aplicação containerizado nesta entrega; o README inicia o backend pelo Python.
- O script de passagem foi inspecionado, sem executá-lo ou acionar outra IA. Sua
  regra de pausa foi respeitada. Nenhum limite de uso ou erro de autenticação ocorreu.

## Arquivos afetados

- Backend: `config/settings.py`, `apps/core/views.py`, `apps/core/tests/test_health.py`,
  `apps/core/tests/test_settings.py`, `apps/accounts/models.py`,
  `apps/accounts/tests/test_users.py`,
  `apps/accounts/migrations/0002_user_accounts_user_email_ci_unique.py` (todos em `backend/`).
- Frontend: `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/App.test.tsx`.
- Tablet: `tablet/lib/api_client.dart`, `tablet/lib/main.dart`,
  `tablet/test/status_test.dart`, `tablet/test/api_client_test.dart`,
  `tablet/android/app/src/debug/AndroidManifest.xml`, `tablet/README.md`.
- Infra/documentação: `.github/workflows/ci.yml`, `.gitignore`, `README.md`,
  `docs/progresso.md`, `docs/controle/estado.json` e este relatório.

## Verificações executadas

Backend em `backend/`, usando o virtualenv existente, com `DJANGO_DEBUG=true` e
`DATABASE_URL=sqlite:///:memory:` definidos explicitamente. Nenhum banco persistente
ou credencial real foi usado. Comandos abaixo executados nesta revisão:

| Verificação | Resultado |
|---|---|
| `.venv\Scripts\python -m pytest -q` | **27 passaram**, execução final após ajuste de cookies |
| `.venv\Scripts\python -m ruff check .` | **Passou** |
| `.venv\Scripts\python -m ruff format --check .` | **Passou**, 16 arquivos |
| `.venv\Scripts\python manage.py check` | **Passou**, nenhum problema |
| `.venv\Scripts\python manage.py makemigrations --check --dry-run` | **Passou**, nenhuma alteração pendente |
| `.venv\Scripts\python manage.py migrate --noinput` | **Passou**, todas as migrations em SQLite vazio, incluindo `accounts.0002` |
| `.venv\Scripts\python -m pip check` | **Passou**, dependências instaladas consistentes |
| `npm run lint` | **Passou** |
| `npm run format:check` | **Passou** |
| `npm run typecheck` | **Passou** |
| `npm test` | **13 passaram**, 2 arquivos |
| `npm run build` | **Passou**, Vite gerou `dist/` |
| Parse de CI e Compose com `js-yaml` já instalado no frontend | **Passou**, sintaxe YAML válida; não valida execução do GitHub Actions |
| `git diff --check` | **Passou** |

Os 4 testes originais do backend e os 3 do frontend foram preservados; fixtures de
sucesso foram alinhadas ao JSON real do backend. Novos testes cobrem configuração
de produção, host recusado, flags administrativas, autenticação, usuário inativo,
senha inutilizável, unicidade no banco, logs, contratos inválidos e timeout/cancelamento.

Ocorrências intermediárias: Ruff encontrou 3 linhas longas nos testes novos;
`ruff format` corrigiu e as verificações finais passaram. Pytest passou com **1 aviso
de cache** por falta de acesso ao `.pytest_cache` preexistente (também houve aviso
de diretório já existente); não foi alterada sua permissão nem desabilitado teste.
Git emitiu avisos de acesso ao ignore global e de conversão LF/CRLF, sem impedir a
inspeção. Dependências existentes foram usadas; não se executou instalação limpa
com `npm ci` ou `pip install`, nem reprodução do ambiente Linux/Python 3.13 da CI.

## Pendências essenciais

1. **PostgreSQL/Compose:** Docker e psql não disponíveis (`Get-Command` não os encontrou).
   Executar Compose, migrations e os testes no PostgreSQL 17. O aceite de
   backend+banco do produto continua pendente; SQLite não é evidência suficiente.
2. **Flutter:** Flutter e Dart não disponíveis. Não foram executados geração do
   projeto Android, analyze, testes (12 casos no código), build APK ou instalação.
   Confirmar preservação do manifesto debug pelo SDK, conexão HTTP ao backend,
   estados da tela e tentativa novamente em emulador/dispositivo.
3. **CI:** workflow nunca executado; validar jobs no GitHub Actions, instalação das
   versões fixadas e o ambiente Android gerado. Parsing YAML não comprova CI verde.
4. **Migration nova:** se houver dados pré-existentes com e-mails que diferem apenas
   por caixa, identificar e resolver os conflitos antes de aplicar `0002`; não há
   fusão/exclusão automática de contas. A aplicação local persistente fica para quem
   controla esse banco; esta revisão só aplicou migrations em banco descartável.

## Melhorias opcionais / etapas futuras

- Fixar versão do Flutter e versionar o projeto Android completo e seu lockfile após
  a primeira execução validada; considerar actions fixadas por SHA para reprodutibilidade.
- Na implantação, definir HTTPS/proxy/HSTS, servir estáticos, revisar com
  `manage.py check --deploy` e provisionar chaves privadas. Não foi alegada prontidão
  de produção nem conformidade legal nesta etapa.
- Considerar verificação separada de migrations pendentes na implantação; manter
  explícito o contrato atual de readiness como conectividade.

## Conclusão

**Revisão concluída com correções e ressalvas de validação.** Backend em SQLite e
frontend passaram nas verificações locais. PostgreSQL/Compose, Flutter e execução
real da CI permanecem pendentes; a etapa não tem aceite integral de infraestrutura.
Controle devolvido para conferência das correções e dessas pendências, sem iniciar
a etapa 2.
