# Etapa 06 — Revisão (Reconhecimento facial)

> Divisão vigente: o Codex apenas revisa; o Claude analisa, corrige e valida. Não consta aprovação do Codex para correções que ele não revisou.

## Apontamentos originais do Codex (relatório bruto, não editado) — 2026-10-22 11:45

Encontrei **dois defeitos confirmados por leitura do código** e **uma suspeita de concorrência que exige reprodução dirigida em PostgreSQL**.

1. **Alta — Tablet fica preso a uma autorização expirada após falha de comunicação.**  
   **Arquivo:** [device_controller.dart:265](/D:/projetos/visualcode/noxora-ponto/tablet/lib/device_controller.dart:265), também linhas 303–306.  
   **Cenário:** a primeira marcação não chega ao servidor e termina em timeout. O código de exceção expira ou é substituído pelo responsável. O funcionário informa o novo código e tenta novamente.  
   **Consequência:** `putIfAbsent` reutiliza todo o payload anterior, inclusive a identificação vencida, ignorando o novo código. O servidor responde 400, mas o tablet mantém a pendência indefinidamente porque `wasUnconfirmed` é verdadeiro. Essa matrícula não consegue concluir outra marcação nessa sessão. O mesmo problema se aplica ao token facial expirado.  
   **Direção da correção:** permitir renovar a identificação preservando o mesmo `client_event_id` e os dados do evento. O backend deve continuar devolvendo primeiro a marcação existente, quando houver, para evitar duplicidade. Não basta descartar a pendência e gerar outro evento.

2. **Média — Marcações válidas esgotam a cota compartilhada de exceção.**  
   **Arquivo:** [services.py:364](/D:/projetos/visualcode/noxora-ponto/backend/apps/biometrics/services.py:364), `reserve_exception_attempt`; chamada em `backend/apps/timeclock/views.py:32`.  
   **Cenário:** dez funcionários registram corretamente por exceção no mesmo tablet dentro de um minuto. O próximo funcionário apresenta matrícula e código válidos.  
   **Consequência:** recebe 429 antes da validação do código. A cota contabiliza sucessos e não é liberada após a marcação. No cenário atual — empresa em modo facial, sem motor real — isso limita a única alternativa disponível a dez marcações por minuto por aparelho, mesmo sem qualquer tentativa inválida.  
   **Direção da correção:** separar a proteção contra adivinhação de códigos da capacidade de atendimento legítimo, preservando a contagem de falhas após rollback e a proteção concorrente. Validar explicitamente uma sequência de códigos válidos de funcionários diferentes.

3. **Alta, se reproduzida — Possível deadlock entre verificação facial e marcação. Suspeita pendente de confirmação.**  
   **Arquivos:** [services.py:183](/D:/projetos/visualcode/noxora-ponto/backend/apps/biometrics/services.py:183), `_attempt` no mesmo arquivo; [services.py:99](/D:/projetos/visualcode/noxora-ponto/backend/apps/timeclock/services.py:99).  
   **Cenário:** uma verificação bloqueia o funcionário. Simultaneamente, uma marcação do mesmo funcionário bloqueia o dispositivo e espera pelo funcionário. A verificação insere `VerificationAttempt`, cuja chave estrangeira referencia o dispositivo bloqueado.  
   **Consequência possível:** a validação da chave estrangeira fecha o ciclo de espera, e o PostgreSQL aborta uma das transações. Isso pode transformar uma operação válida em 500. Os testes existentes de consumo concorrente de token e de falhas faciais concorrentes não demonstram esse cruzamento específico.  
   **Verificação recomendada:** em banco descartável, coordenar duas conexões com barreiras nesses pontos e observar a inserção/commit da tentativa.  
   **Direção da correção, se confirmado:** uniformizar a ordem dos bloqueios e considerar também os bloqueios adquiridos pelas chaves estrangeiras.

Sobre os demais pontos: o 500 genérico de `process_exception` é **intencional no código**; a ausência de traceback, isoladamente, não constitui defeito de privacidade. Não identifiquei um vazamento concreto nesse caminho. O consumo de face/exceção participa da mesma transação da marcação, e o backend consulta o evento existente antes de consumir novamente o token. Também não encontrei contorno concreto das restrições do simulador com `DEBUG=False`.

**Bloqueios para conclusão:** corrigir a recuperação do tablet, resolver o impacto da cota sobre marcações válidas e esclarecer a suspeita de deadlock. Permanecem os bloqueios já declarados: motor real indisponível por decisão de produto, captura de câmera ausente e Flutter não compilado. O simulador não permite concluir eficácia ou vivacidade real.

**Limitações:** revisão estática do diff e das dependências relevantes; não executei a suíte, não reproduzi concorrência nem alterei arquivos. Não validei infraestrutura de logs/proxy, backups ou eliminação física de cópias antigas. Retenção e base jurídica continuam dependendo de validação especializada.

## Análise e correções do Claude

Correção implementada e validada pelo Claude após apontamento do Codex (o Codex ainda não revisou estas correções; ver última seção).

**Apontamento 1 (Alta, Dart): tablet preso a identificação vencida após falha de comunicação — CONFIRMADO por leitura do código.**
- `putIfAbsent` reutilizava o payload inteiro, inclusive a identificação vencida, e 400/404 após tentativa sem confirmação mantinha a pendência para sempre.
- Correção: a nova tentativa **renova a identificação** (código de exceção ou token facial) **mantendo o mesmo `client_event_id`**, `declared_kind` e `device_reported_at`. Além disso, 400/404 em reenvio agora **encerra a tentativa**, porque o servidor consulta o evento existente *antes* de validar matrícula, identificação ou política: um 400/404 prova que o evento não foi gravado. Esse contrato foi fixado por teste no backend (`test_evento_gravado_e_devolvido_antes_de_validar_identificacao_ou_matricula`: reenvio com matrícula inexistente, código inválido, token falso e método proibido pela política devolve 200 com a marcação original). 401 continua conservador (a credencial pode ter sido revogada antes de qualquer verificação).
- Arquivos: `tablet/lib/device_controller.dart`, `tablet/test/device_controller_test.dart` (testes Dart ajustados/novos, **não executados**: Flutter ausente).

**Apontamento 2 (Média): marcações válidas esgotam a cota de exceção — CONFIRMADO.**
- `reserve_exception_attempt` contava toda tentativa; dez funcionários com código válido no mesmo aparelho em um minuto bloqueavam o décimo primeiro. No modo facial sem motor real, a exceção é a única via.
- Correção: reserva antes (mantém a proteção concorrente contra adivinhação) e **devolução da tentativa quando a marcação é gravada** (`refund_exception_attempt`). Falhas (código errado, rollback, erro interno, 429) não são devolvidas. A reserva continua atômica por `select_for_update`, então rajadas de palpites não excedem o limite.
- Arquivos: `apps/biometrics/services.py`, `apps/timeclock/views.py`.

**Apontamento 3 (Alta, suspeita): deadlock entre verificação facial e marcação — CONFIRMADO por reprodução em PostgreSQL 17.5.**
- Teste dirigido com barreiras (`test_verificacao_e_marcacao_concorrentes_nao_geram_deadlock`) provocou `psycopg.errors.DeadlockDetected` antes da correção: a verificação segurava o funcionário e inseria a tentativa (a FK pede `FOR KEY SHARE` no dispositivo), enquanto a marcação segurava o dispositivo com `FOR UPDATE` e pedia o funcionário.
- Correção: todos os `select_for_update()` do código de aplicação passaram a `select_for_update(no_key=True)` (`FOR NO KEY UPDATE`), que não conflita com a verificação de chave estrangeira; nenhum bloqueio altera chave primária. Efeito colateral aceito: nenhum (SQLite ignora a cláusula). O teste passa em PostgreSQL após a correção.
- Arquivos: `apps/biometrics/{services,views}.py`, `apps/devices/{services,views}.py`, `apps/operations/services.py`, `apps/timeclock/{services,views}.py`, `apps/companies/permissions.py`.

**Demais pontos do Codex:** o 500 genérico de `process_exception` é intencional; antes da revisão o Claude havia refutado, por teste, a suspeita de log perdido (o `django.request` registra o erro; só o traceback é omitido por desenho nas rotas de biometria). Sem contorno do simulador com `DEBUG=False` (nenhuma ação).

## Testes executados e resultados

| Verificação | Resultado |
|---|---|
| Backend, SQLite em memória (suíte completa) | 328 passam, 9 ignorados |
| Backend, PostgreSQL 17.5 real (suíte completa, inclui concorrência) | **336 passam**, 1 ignorado (específico do SQLite) |
| Teste do deadlock, antes da correção | falhou com `DeadlockDetected` (reproduzido) |
| Teste do deadlock, depois da correção | passa |
| `ruff check`, `ruff format --check`, `makemigrations --check` | limpos |
| Dart (analyze/test) | **não executado**: Flutter ausente |

## Pendências

- Motor biométrico real e captura por câmera no tablet: **bloqueados** (decisão de produto; ver docs/avaliacao-motor-biometrico.md). O aceite da etapa 6 permanece bloqueado por isso.
- Testes Dart escritos mas não executados.
- Gestão de chaves biométricas em KMS/HSM, crypto-shredding e eliminação física de cópias antigas: etapa 14/15.
- Base legal (LGPD art. 11), RIPD e prazo de retenção: validação especializada.

## Revisão complementar necessária?

**Sim**, restrita às correções: mexem em ordem de bloqueios e transações das marcações (integridade/duplicação) e em limite de tentativas de código de exceção (segurança). Será enviada apenas a lista de correções, sem repetir a revisão inteira. O resultado será registrado abaixo, em "Revisão complementar".

