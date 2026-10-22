Revise a etapa 6 (Reconhecimento facial) do Noxora Ponto.

Sua função é somente revisão. Não altere arquivos, não implemente correções, não crie commits e não acione outra IA.

Objetivo: infraestrutura de identificação facial 1:1 em volta de um motor biométrico plugável. O motor real está BLOQUEADO por decisão de produto (custo/licença); o simulador existe só para testes e não comprova eficácia. Não avalie algoritmo biométrico nem proponha serviço pago.

Critérios de aceite (da etapa):
- Cadastro biométrico protegido (consentimento, template criptografado, sem imagem persistida, sem exposição em logs/respostas/auditoria/relatórios/backups indevidos).
- Verificação 1:1 por matrícula, com estados claros de sucesso, falha e indisponibilidade, tratamento de qualidade insuficiente e integração com detecção de apresentação (vivacidade).
- Alternativa autorizada de identificação para exceções.
- Controle de acesso, retenção e exclusão do cadastro biométrico.
- Marcação de ponto com identificação facial ou exceção, sem perder nem duplicar marcações (idempotência).
- Simulador identificado e impedido de funcionar como validação real em produção.

Alterações: `git diff a45d0d6..HEAD` (etapa 6 completa: apps/biometrics, provedores na marcação em apps/timeclock, escopo do dispositivo em apps/devices, settings, frontend BiometricsActions, tablet device_controller). Atenção: o trecho de segurança abaixo foi escrito por uma execução anterior do Codex sob a regra antiga e foi apenas inspecionado pelo Claude, não revisado: `backend/apps/biometrics/security.py` (BoundedJSONParser, filtro de relatório de exceções, middleware com `process_exception`), `checks.py` (checks de deploy), migration `0002_exceptionbudget` e `reserve_exception_attempt` (cota no banco), token de verificação assinado (`verification_token`), HMAC do código de exceção, bloqueios `select_for_update` por funcionário.

Testes já executados pelo Claude: backend 320 passam em SQLite e 327 em PostgreSQL 17.5 real; ruff e `makemigrations --check` limpos; frontend 54 testes, lint, typecheck e build limpos. Dart não compilado (SDK ausente).

Riscos e dúvidas conhecidos:
- `process_exception` em rotas sensíveis devolve 500 genérico (o log registra apenas "Internal Server Error", sem traceback): é intencional? há contorno que vaze dado?
- Contagem de tentativas de exceção e de falhas faciais: contorno por alternar matrícula/aparelho, concorrência, DoS contra um colega.
- Ordem das transações: consumo do token (face/exceção) + gravação da marcação; reenvio do mesmo evento com token já consumido.
- Chave biométrica em variável de ambiente (KMS é etapa 14/15); exclusão zera o conteúdo mas cópias em páginas/backups antigos podem persistir.
- Modo `face` da empresa sem motor real: tablets só marcam por exceção.

Comece pelas alterações e consulte dependências quando necessário. Procure defeitos concretos que comprometam funcionamento, segurança, integridade ou critérios de aceite.

Evite sugestões cosméticas, refatorações opcionais e repetição de pontos equivalentes. Não repita a suíte de testes já executada. Faça apenas verificações pontuais sem escrita quando forem necessárias.

Para cada problema, informe:
- Gravidade.
- Arquivo e linha, quando aplicável.
- Cenário que provoca o defeito.
- Consequência.
- Direção recomendada para a correção.

Diferencie defeitos confirmados de suspeitas que precisam de verificação.

Finalize com os bloqueios para conclusão da etapa e as limitações da revisão. Se não encontrar problemas relevantes, informe isso objetivamente. Não escreva código de correção.
