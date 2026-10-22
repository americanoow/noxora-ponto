Revise as CORREÇÕES da etapa 6 (Reconhecimento facial) do Noxora Ponto. Esta é uma revisão complementar curta: não refaça a revisão da etapa inteira.

Sua função é somente revisão. Não altere arquivos, não implemente correções, não crie commits e não acione outra IA.

Objetivo: confirmar se as 3 correções feitas pelo Claude resolvem os apontamentos da sua revisão anterior sem criar novo defeito de integridade, concorrência ou segurança. O relatório anterior está em `docs/etapas/06-revisao.md` (seção "Análise e correções do Claude").

Critérios de aceite relevantes: marcação sem perda nem duplicação (idempotência); verificação facial e exceção autorizada de uso único; proteção contra adivinhação do código de exceção; sem deadlock entre verificação facial e marcação.

Alterações: `git diff edcece3..da6d194` (backend e tablet). Resumo:
1. Todos os `select_for_update()` do código de aplicação viraram `select_for_update(no_key=True)` (FOR NO KEY UPDATE) para não conflitar com o FOR KEY SHARE das chaves estrangeiras. Teste de reprodução com barreiras: `test_verificacao_e_marcacao_concorrentes_nao_geram_deadlock` (falhava com DeadlockDetected antes; passa depois).
2. `reserve_exception_attempt` continua reservando antes; novo `refund_exception_attempt` devolve a tentativa quando a marcação é gravada (apps/timeclock/views.py e apps/biometrics/services.py).
3. Tablet (Dart): a nova tentativa renova a identificação mantendo o mesmo `client_event_id`; 400/404 em reenvio encerra a tentativa, com a premissa de que o servidor consulta o evento existente antes de validar matrícula, identificação ou política (teste de contrato: `test_evento_gravado_e_devolvido_antes_de_validar_identificacao_ou_matricula`).

Testes já executados pelo Claude: backend 328 passam em SQLite e 336 em PostgreSQL 17.5 real (inclui concorrência); ruff e `makemigrations --check` limpos. Dart não executado (SDK ausente).

Riscos e dúvidas conhecidos (verifique em especial):
- Resta algum ciclo de espera entre os bloqueios (dispositivo, funcionário, token/autorização, contador de NSR, cota) nos caminhos de marcação, verificação, rotação de credencial e revogação? Há caso em que NO KEY UPDATE seja insuficiente (por exemplo, atualização de coluna de chave)?
- Contorno da cota: rajada concorrente que exceda 10 palpites, devolução indevida (dupla devolução, resposta perdida), ou devolução que reabra espaço para adivinhação.
- Premissa do Dart: existe caminho em que o evento foi gravado e, mesmo assim, o reenvio recebe 400 ou 404 (por exemplo, validação do serializer antes da consulta do evento, mudança de vínculo do funcionário, permissões)? Se existir, o encerramento da tentativa no tablet seria perigoso (marcação duplicada).

Comece pelo diff e consulte dependências quando necessário. Procure defeitos concretos. Evite sugestões cosméticas e refatorações opcionais. Não repita a suíte de testes. Faça apenas verificações pontuais sem escrita.

Para cada problema, informe: gravidade; arquivo e linha, quando aplicável; cenário que provoca o defeito; consequência; direção recomendada para a correção. Diferencie defeitos confirmados de suspeitas que precisam de verificação.

Finalize com os bloqueios para conclusão da etapa e as limitações da revisão. Se não encontrar problemas relevantes, informe isso objetivamente. Não escreva código de correção.
