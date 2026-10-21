# Etapa 2 — revisão do Codex

Data: 21/10/2026. Base: `git diff 95a32ae..HEAD` e alterações locais. Na abertura, somente `docs/controle/estado.json` estava modificado; frontend e documentação da implementação já estavam no HEAD. Estado sem pausa obrigatória. Nenhuma credencial real foi consultada; nenhum commit, push, outra IA ou nova etapa foi iniciado.

## Problemas encontrados e correções

1. **Exposição de identidade entre empresas por convite.** Convidar um e-mail de outra empresa retornava `User.first_name`, permitindo confirmar uma conta existente e obter seu nome global. `Membership.name` agora guarda somente o nome informado pela própria empresa. POST, GET e PATCH serializam esse valor local. Migration `companies.0002_membership_name` deixa nomes antigos vazios, sem copiar dados globais; a interface usa o e-mail como fallback. A identidade e a senha globais de contas existentes continuam intactas.
2. **Corrida no consumo do token de reset.** Duas requisições podiam validar o mesmo token antes de qualquer gravação e ambas trocar a senha. A gravação agora exige que hash, e-mail, último login e situação ativa ainda coincidam com a identidade validada. Apenas uma atualização vence; atualização e auditoria são atômicas. Teste intercala uma troca concorrente depois da validação e comprova que a segunda não sobrescreve a primeira.
3. **Corrida na criação da identidade global.** Dois convites em empresas diferentes podiam disputar o mesmo e-mail e resultar em 500 ou 409 indevido. A criação usa savepoint e, em conflito de unicidade, recupera a conta existente. A constraint de vínculo continua impedindo duplicatas. Teste simula esse conflito; concorrência real em PostgreSQL permanece pendente.
4. **Alterações administrativas sem atomicidade com a auditoria e autorização sujeita a corrida.** PATCH de empresa/vínculo podia persistir sem evento se a auditoria falhasse. Transações agora abrangem as gravações e a auditoria; alterações de empresa e de vínculos bloqueiam a linha da empresa antes de resolver o papel. Isso serializa, no PostgreSQL, revogações concorrentes entre administradores e desativação da empresa. Convite de membro é enviado somente após commit. Teste confirma rollback quando a auditoria falha.
5. **Acesso operacional da plataforma contrário a D8.** Uma conta com `is_platform_admin` e vínculo ativo era tratada como membro comum, conseguia ler/alterar membros e escapava do evento de acesso da plataforma. A identidade de plataforma agora prevalece e nunca recebe papel operacional. Listagem e alteração de empresas também registram acesso. Tentativas de POST/PATCH em membros retornam 403 preservando o evento de acesso negado.
6. **Auditoria: segredos aninhados e upsert.** A limpeza só verificava chaves no primeiro nível; `bulk_create(update_conflicts=True)` podia alterar eventos existentes. Agora a limpeza percorre dicionários/listas e também remove chaves de autorização/cookies; upsert é rejeitado. Isso não substitui proteção no banco nem permite enviar conteúdo arbitrário em campos livres.
7. **E-mail: tokens em logs e enumeração por erro de transporte.** O backend console imprimia links com tokens; erros SMTP só afetavam contas existentes. O padrão agora é SMTP, console é rejeitado na configuração, e falhas SMTP/rede geram resposta pública uniforme e mensagem de log fixa, sem traceback, endereço ou token. Configure um servidor SMTP de teste para receber mensagens em desenvolvimento; sem servidor, o envio falha e fica registrado de forma genérica. Testes usam locmem. Não há retry durável nesta etapa.
8. **Frontend: dados da empresa anterior.** O painel preservava membros ao trocar empresa; falha ou resposta atrasada podia manter dados sob a seleção errada. A instância do painel agora é identificada por empresa/papel, descartando estado anterior. Regressão cobre troca para empresa cujo endpoint responde 403.
9. **Frontend: saída falsa e CSRF.** `finally` mostrava login mesmo quando logout falhava. Agora a interface mantém o estado e informa o erro. Falhas ao obter CSRF impedem a mutação; 403 descarta o token armazenado para a próxima tentativa, sem repetir automaticamente a operação. Testes verificam renovação após login/logout, 403 e 429.

## Cobertura e limites da revisão

- Mantidos e executados os testes anteriores: IDOR entre empresas por todos os papéis, vínculo de B pela URL de A, papéis independentes, listagens/auditoria isoladas, autoalteração, duplicata, inatividade, sessões ociosas/absolutas, senha fraca e token reutilizado sequencialmente.
- Acrescentados testes de mass assignment em PATCH (identidade, empresa, senha e privilégios), bloqueio de todos os endpoints de empresa após revogar usuário/vínculo/empresa, CSRF em reset e mutações, rotação da chave de sessão, sessão sem marca de login, reset expirado/inativo, conflito de reset, transporte SMTP, auditoria recursiva/upsert e rollback.
- Não encontrado acesso cruzado por id nos endpoints cobertos. Isso não é garantia de ausência de outras vulnerabilidades.
- **Enumeração por tempo ainda possível:** reset de conta ativa executa geração/envio de e-mail; conta inexistente não. Convite novo envia mensagem; conta existente não. Igualar status/corpo e tratar falha SMTP não elimina essa diferença. Não foi feita medição estatística em produção.
- A resposta 409 de convite duplicado revela somente vínculo já consultável pelo administrador da própria empresa.
- As migrations existentes foram inspecionadas; a nova é aditiva, sem alteração das anteriores. O pytest cria o banco de testes com migrations. Não foi aplicada migration a banco persistente.

## Verificações e resultados

Executado em `backend`, com `DJANGO_DEBUG=true` e `DATABASE_URL=sqlite:///:memory:`:

| Comando | Resultado |
|---|---|
| `.venv\Scripts\python -m pytest` | **82 passaram** (64 anteriores + 18 novos); inclui regressões da etapa 1 |
| `.venv\Scripts\python -m ruff check .` | Passou |
| `.venv\Scripts\python manage.py makemigrations --check --dry-run` | Passou, sem alterações pendentes |
| `.venv\Scripts\python manage.py check` | Passou, sem problemas |

Executado em `frontend`:

| Comando | Resultado |
|---|---|
| `npm test` | **25 passaram** (19 anteriores + 6 novos) |
| `npm run lint` | Passou |
| `npm run typecheck` | Passou |
| `npm run build` | Passou |
| `npm run format:check` | Passou |

`git diff --check`: passou. O pytest emitiu aviso de falha ao gravar seu cache (`WinError 183`); isso não impediu testes ou migrations. Na primeira execução intermediária, um teste detectou rollback indevido de eventos de acesso negado da plataforma; corrigido antes da execução final. Ruff inicialmente detectou imports/linha longa; corrigidos. Não houve enfraquecimento das asserções anteriores; o teste de convite passou a executar callbacks de commit para verificar o envio após a transação.

Docker, Flutter e psql não foram encontrados no PATH. PostgreSQL real, locks sob concorrência, Compose, Flutter/analyze/APK e CI externa não foram executados. SQLite não valida os bloqueios `select_for_update` do PostgreSQL.

## Arquivos afetados

- `backend/apps/accounts/{services,views}.py` e `tests/test_auth.py`.
- `backend/apps/companies/{models,permissions,serializers,views}.py`, `migrations/0002_membership_name.py` e `tests/test_isolation.py`.
- `backend/apps/audit/{models,services}.py` e `tests/test_audit.py`.
- `backend/config/settings.py`, `backend/.env.example`, `backend/apps/core/tests/test_settings.py`.
- `frontend/src/{App.tsx,App.test.tsx,http.ts,http.test.ts}`.
- Este relatório, `docs/etapas/02-implementacao.md`, `docs/decisoes-tecnicas.md`, `docs/progresso.md` e `docs/controle/estado.json`.

## Pendências essenciais / proposta para decisão

1. **Decidir entrega assíncrona de e-mails para reduzir enumeração temporal e garantir retry.** Proposta: registrar pedidos em uma outbox com resposta uniforme e processá-los fora da requisição, incluindo o caminho de e-mail inexistente; resolver elegibilidade no processamento e nunca registrar tokens em logs. Definir retenção, proteção dos dados, operação do worker e limite de tentativas antes de implementar. Isso altera arquitetura/operação frente a D2, portanto não foi introduzido sem decisão. Não usar sleeps nem threads descartáveis como suposta solução.
2. Validar em PostgreSQL concorrência real: dois resets do mesmo token, convites concorrentes do mesmo e-mail na mesma empresa e em empresas diferentes, revogações recíprocas de administradores e desativação da empresa durante mutação. O teste de interleaving do reset e de conflito de identidade é determinístico, não substitui conexões simultâneas reais.
3. Configurar/testar entrega SMTP segura; falha tratada não significa e-mail entregue. Validar migrações em banco persistente: checar duplicatas por caixa antes de `accounts.0002`, aplicar migrations da etapa e `companies.0002`, com backup e procedimento de retorno.
4. Antes de produção multiprocesso, usar cache compartilhado para throttling, como já registrado. Permanecem pendentes Docker/PostgreSQL, Flutter e CI.

## Melhorias opcionais / adiamentos mantidos

- Paginar empresas/membros e agrupar inserções dos eventos da listagem da plataforma, preservando o registro por empresa.
- Melhorar UX de sessão expirada, ocultar edição do próprio vínculo e recuperar convites com falha de entrega.
- MFA permanece pendente de avaliação; escopo por unidade/setor segue adiado por D11. Proteção append-only no banco segue etapa 14; proxy/IP confiável, etapa 15.
- Requisitos legais não foram alterados nem considerados validados por estes testes.

## Conclusão

Revisão e correções locais concluídas, com backend/frontend verdes. **Aprovação final da etapa fica pendente da decisão sobre enumeração temporal e das validações essenciais acima.** Controle devolvido para conferência do Claude/usuário, sem iniciar a etapa 3 e sem commit/push.
