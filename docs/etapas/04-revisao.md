# Etapa 4 — revisão do Codex

Revisão em 21/10/2026 (America/Sao_Paulo), sobre `git diff b086545..HEAD` e alterações locais. Regras, plano, arquitetura, progresso, D23–D29 e implementação lidos. Estado sem pausa obrigatória. A alteração pré-existente em `docs/controle/estado.json` foi preservada; este relatório devolve a etapa ao Claude para conferência, sem iniciar outra etapa, commit, push ou outra IA.

## Problemas encontrados e correções

1. **Alta — bypass do throttle de ativação por cabeçalho.** `ScopedRateThrottle` aceitava a identidade derivada de `X-Forwarded-For`. Trocar o cabeçalho renovava a cota. Corrigido para `REMOTE_ADDR`. O throttle DRF também fazia leitura/escrita não atômica entre threads; agora esses passos são serializados no processo. Testes com cabeçalhos variados e 30 chamadas concorrentes verificam o limite de 10/min. Cache local continua inadequado para múltiplos processos.
2. **Alta — multiplicação de credenciais e renovação da cota por rotação.** Cada repetição emitia outra credencial, inclusive com a anterior dentro da tolerância; a cota era por credencial. Agora há uma única sucessora, retry idempotente sem estender a janela e espera de 20 dias para rotacionar sucessoras. A primeira rotação continua disponível. HMAC com chave do servidor e segredo apresentado recupera o mesmo token sem persistir segredo em claro e impede derivar sucessores offline só com token antigo. Cota de 120/min passa a ser por dispositivo, compartilhada por todos os endpoints protegidos e credenciais.
3. **Alta — alterações concorrentes sem protocolo comum de bloqueio.** Revogação/renovação não bloqueavam primeiro o dispositivo; edição salvava instância inteira obtida antes da transação, podendo sobrescrever estado de outra operação. Ativação bloqueava código e tabelas relacionadas; rotação bloqueava apenas credencial e não revalidava expiração/status. Corrigida ordem dispositivo → código/credencial e releitura sob bloqueio. Edição passa a obter dispositivo dentro da transação. Testes cobrem credencial autenticada antes de revogação, renovação ou expiração. Teste de duas ativações simultâneas incluído para PostgreSQL; não foi executado neste ambiente.
4. **Alta — credencial emitida sem auditoria atômica.** Falha de auditoria após ativação podia consumir código sem entregar token; rotação podia encurtar validade e criar token sem auditoria. Ambas agora compartilham a transação com o evento. Regressões simulam falha e verificam rollback do código, status, prazo e credenciais.
5. **Média — entrada malformada e proteção de respostas.** IDs de credencial não tinham limite explícito compatível com bigint; cabeçalho Unicode não codificável gerava erro 500 no adaptador DRF. Entradas inválidas agora falham com 401, sem consulta fora do intervalo. Segredos são comparados com `hmac.compare_digest`. Respostas contendo código/token usam `no-store`, e o filtro recursivo de auditoria passa a remover a chave `activation_code` além de token/secret/authorization.
6. **Média — localização podia ser gravada com consentimento desatualizado.** A API usava a instância obtida na autenticação; agora bloqueia e relê o dispositivo e revalida a credencial antes de inserir. Constraint rejeita justificativa só com espaços, além de vazia. Validação de coordenadas, precisão e data continua preservada.
7. **Alta — ciclo Dart sem serialização nem atualização periódica.** Heartbeats/rotações concorrentes podiam sobrescrever ou apagar token novo; rotação ignorava 401/403; o app só chamava heartbeat na inicialização ou manualmente. Agora compartilha uma operação em andamento, faz heartbeat a cada minuto enquanto montado, trata revogação/suspensão e cancela timer/fecha cliente no descarte. Respostas tardias não notificam controller descartado; revogação na rotação deixa de estar ativa mesmo se apagar o armazenamento falhar. Testes Dart adicionados, ainda não executados.
8. **Média — armazenamento Dart parcial e falhas silenciosas.** Token e data eram gravados separadamente e erro de leitura virava “sem credencial”. Agora usam um único JSON no armazenamento seguro; leitura falha leva a indisponibilidade, sem fingir que não existe credencial. Respostas inválidas não gravam a string `null` como token. Implementação anterior não foi compilada/distribuída nesta etapa; não houve migração de instalação Android existente.
9. **Defesa adicional no React.** `Operations` já remontava por empresa/permissão, mas `DevicesTab` isoladamente preservava seu estado ao mudar props. A própria aba agora remonta o painel, descartando código e respostas antigas junto com o estado anterior. Regressão verifica ausência de escrita em Storage e descarte do código ao trocar empresa/permissão. Código continua apenas em estado local, sem sessão, URL ou persistência.

## Verificações de segurança preservadas

- Ativação: código aleatório de 10 caracteres, hash SHA-256, uso único, validade de 15 minutos, invalidação por renovação, resposta uniforme para código inexistente/usado/expirado. O código formatado ou em minúsculas continua funcionando.
- Autenticação: sessão não substitui Device e vice-versa; token adulterado, truncado, ID inexistente, segredo de outro aparelho, revogado ou expirado não autoriza. Retry após renovação também falha, incluindo a sucessora.
- Isolamento: painel resolve empresa/vínculo; gestor não escreve nem lê localização; cadastro/edição rejeitam unidade de outra empresa. API do tablet deriva escopo do dispositivo, ignorando IDs no corpo/querystring. Consulta é exata, sem listagem, sem CPF, apenas funcionário ativo com lotação atual na unidade.
- **Enumeração residual da matrícula:** um tablet autorizado consegue distinguir matrícula existente na própria unidade (200 com nome) de ausente (404), conforme D27. A cota reduz abuso, mas não elimina esse oráculo nem ataques distribuídos. Remover essa distinção exige redefinir o fluxo de identificação; não alterado nesta revisão.
- Nenhuma migration contém códigos/tokens reais. Persistência de credenciais permanece por hash. Testes existentes de auditoria sem segredos continuam passando; logging de proxy/observabilidade não foi validado neste ambiente.

## Arquivos afetados

- Backend: `apps/devices/{auth,models,services,views}.py`, `apps/devices/tests/test_devices.py`, `apps/audit/services.py`.
- Migrations: `devices/0002_devicecredential_rotated_to.py` (relação única com sucessora, nullable) e `devices/0003_remove_device_device_location_requires_justification_and_more.py` (constraint de justificativa). `0001` preservada.
- Frontend: `src/DevicesTab.tsx`, `src/DevicesTab.test.tsx`.
- Tablet: `lib/{token_store,device_controller,main}.dart`, `test/{device_controller_test,status_test}.dart`. Testes de tela usam armazenamento em memória e desmontam a tela para cancelar timer; suas expectativas anteriores foram preservadas.
- Documentação: este relatório e notas de revisão em `docs/decisoes-tecnicas.md`.

## Testes e resultados

Executados em Windows, Python 3.15/Django 6.0.9, SQLite em memória. Em `backend`, com `DJANGO_DEBUG=true` e `DATABASE_URL=sqlite:///:memory:`:

| Verificação | Resultado final |
|---|---|
| `.venv\Scripts\python -m pytest -p no:cacheprovider` | **202 passaram, 1 ignorado** (concorrência PostgreSQL); inclui regressões das etapas 1–3 |
| `.venv\Scripts\python -m ruff check .` | passou |
| `.venv\Scripts\python -m ruff format --check .` | passou, 62 arquivos |
| `.venv\Scripts\python manage.py makemigrations --check --dry-run` | passou, sem alterações faltantes |
| Migrations em banco de testes novo | aplicadas pela suíte SQLite |
| `npm test` em `frontend` | **39 passaram**, sem avisos React na execução final |
| `npm run lint`, `npm run typecheck`, `npm run build`, `npm run format:check` | todos passaram |
| `git diff --check` | passou; avisos do Git sobre conversão LF/CRLF e acesso ao ignore global não impediram revisão |
| Flutter/Dart analyze, testes, APK; Docker/PostgreSQL | não executados: executáveis ausentes no PATH |

Na primeira execução das novas regressões houve duas falhas: uma revelou o erro Unicode na autenticação (corrigido); outra era duplicação de nome de unidade no fixture novo (corrigido sem mudar expectativas). Ruff apontou ordem de import e uma linha longa novos, corrigidos. Um teste React novo inicialmente gerou aviso de atualização fora de `act`; foi ajustado para aguardar os resultados assíncronos. As execuções finais acima estão limpas.

## Pendências essenciais

1. Executar em PostgreSQL 17 as migrations e o teste simultâneo, além de validar concorrência ativação × renovação/revogação, rotação × revogação e edição × localização. SQLite não demonstra bloqueio de linha nem ausência de deadlocks no banco do produto.
2. Conferir dados persistentes antes da migration `0003`: registros antigos com coleta ligada e justificativa só de espaços precisam de correção administrativa; a migration recusa esses dados, sem inventar justificativa ou apagá-los.
3. Executar Flutter analyze/test/build e validar Keystore, reinstalação/backup e falhas de armazenamento em Android real. Os testes Dart foram escritos e revisados por leitura, não compilados. CI continua sem execução comprovada nesta revisão.
4. Antes de produção multiprocesso: cache compartilhado **e atualização atômica** do throttle; definir proxy confiável para IP real. `REMOTE_ADDR` atrás de proxy compartilha a cota entre clientes; não voltar a confiar cegamente em cabeçalhos. Avaliar proteção de borda contra tentativas distribuídas e autenticação inválida, que ocorre antes do throttle por dispositivo.
5. Revogação só é verificável online. A validade de 30 dias do servidor não comprova enforcement offline no aplicativo; a etapa 7 deve implementar e testar a política local, inclusive relógio e persistência. Não há marcação offline implementada nesta etapa.
6. Retenção/descarte e base jurídica da localização dependem de validação especializada. Esta revisão não afirma conformidade legal.

## Melhorias opcionais / decisões futuras

- Alertas para enumeração de matrícula e falhas de ativação em múltiplos IPs, sem registrar matrícula/código/token em logs.
- Definir explicitamente se inativar uma unidade também deve suspender tablets já ativos: hoje impede ativação/renovação, mas não equivale a revogação do dispositivo existente.
- Exibir o prazo efetivo de validade da credencial no contrato do tablet, para a futura política offline. Hoje a data local é usada apenas para decidir quando solicitar rotação.

## Conclusão

**Revisada com correções; verificações locais de backend e frontend aprovadas.** Nenhum requisito ou teste existente removido/enfraquecido. A etapa é devolvida para conferência do Claude, com validação PostgreSQL/Flutter e demais pendências acima explicitamente abertas. Não equivale a aceite de produção, compilação Flutter ou validação externa. Nenhuma próxima etapa iniciada.
