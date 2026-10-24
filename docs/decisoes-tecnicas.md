# Decisões técnicas

| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D1 | Modelo de usuário Django customizado (`accounts.User`) criado na etapa 1, com login por e-mail | Evita migração difícil depois | Etapa 2 estende com empresas e papéis |
| D2 | Backend monolítico modular | Simplicidade | Sem microsserviços/filas até haver necessidade |
| D3 | Codex acionado por `tools/codex_handoff.ps1` com `codex exec --sandbox workspace-write` | CLI local disponível | Script verifica pausa antes de chamar |
| D4 | Commits pelo Claude; Codex não comita | Evitar histórico concorrente | Commit após cada etapa/checkpoint de segurança |
| D5 | Docker/Flutter ausentes no ambiente | Não instalar sem necessidade | Validações marcadas pendentes; testes do backend usam SQLite apenas quando `DATABASE_URL` ausente, nunca como prova de PostgreSQL |

## Pendências de validação especializada
- Requisitos REP-P/Portaria 671/2021 (etapa 5), LGPD para biometria (etapa 6), regras de apuração (etapa 8).

## Etapa 2 — identidade e isolamento
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D6 | Usuário global + `Membership(usuário, empresa, papel)`; papel vale por empresa | Uma pessoa pode atuar em mais de uma empresa sem duplicar identidade | Toda consulta de dados de empresa passa por `resolve_company()`; ids de empresa vêm da URL e são verificados contra o vínculo |
| D7 | Empresa inexistente e sem vínculo respondem 404 | Não revelar existência de outros clientes | Testes de acesso cruzado cobrem os três papéis |
| D8 | `User.is_platform_admin` separado de `is_staff/is_superuser` | Equipe Noxora não herda acesso a dados de clientes | Plataforma só cria/ativa empresas e lê auditoria; cada acesso a empresa gera `platform.company_access`. Não lê membros nem dados operacionais |
| D9 | Auditoria somente de inclusão (`AuditLog`), sem senha/token/biometria | Rastreabilidade administrativa | Update/delete levantam `AppendOnlyError` (no ORM; a proteção no banco, por permissões/trigger, é pendência da etapa 14) |
| D10 | Sessão por cookie (SessionAuthentication + CSRF), ociosa 1 h deslizante e absoluta 12 h | Frontend web mesmo domínio; tablets usarão credencial própria (etapa 4) | Login/logout/reset exigem CSRF; frontend busca novo token após login/logout |
| D11 | Escopo por unidade/setor adiado para a etapa 3 | Entidades ainda não existem | `Membership` ganhará escopo quando houver unidades/setores; hoje o gestor tem o mesmo alcance de empresa e nenhum endpoint de dados operacionais |
| D12 | Admin da empresa não altera o próprio vínculo | Impede autoelevação e o último administrador se desativar | Mudança do próprio papel exige outro administrador |

Pendências: throttling usa cache local (trocar por cache compartilhado em produção multi-processo); IP de auditoria vem de REMOTE_ADDR (proxy confiável na etapa 15); MFA não implementado (avaliar para administradores).

## Notas da revisão da etapa 2 (21/10/2026)
- D8: contas da plataforma não recebem papel operacional mesmo que possuam vínculo; acessos pela listagem e alteração também são auditados.
- D9: limpeza recursiva de metadados e bloqueio de upsert no ORM; a proteção no banco continua pendente.
- Nomes exibidos em vínculos pertencem à empresa (`Membership.name`), sem consulta ao nome global de convidados. Migration aditiva; nomes legados ficam vazios.
- E-mail console proibido por imprimir tokens; SMTP é o padrão. Falhas de transporte retornam mensagem pública uniforme, com log genérico.
- **Proposta ainda não aprovada:** outbox/processamento assíncrono para reduzir enumeração temporal em reset/convites e garantir retry. Exige decisão de arquitetura/operação frente a D2; detalhes e validações em [etapas/02-revisao.md](etapas/02-revisao.md). Não implementado nesta revisão.

## Decisões após revisão da etapa 2
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D13 | Enumeração por tempo no reset/convite aceita como risco residual; outbox assíncrona de e-mails adiada para a etapa 14/15 | Resposta, status e erros já são uniformes e há throttling (5/h); outbox exige worker e operação (contraria D2 sem necessidade hoje) | Reavaliar na etapa 14 junto com retry de e-mail e cache compartilhado |
| D14 | Backend de e-mail console permitido só com `DJANGO_DEBUG=true`; fora de debug é recusado na configuração | Ver link de convite no desenvolvimento sem expor tokens em logs de produção | Padrão continua SMTP |
| D15 | Nome do membro é local (`Membership.name`), não o nome global do usuário | Evita vazar identidade entre empresas | Tela usa e-mail como fallback |

## Etapa 3 — cadastros da operação
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D16 | Jornada (`WorkSchedule`) não muda depois de atribuída; mudar = nova jornada + atribuição com vigência | Mudança não reescreve o passado | `replace_schedule_days` recusa jornada com atribuições |
| D17 | Lotação e jornada do funcionário: intervalos `valid_from/valid_to`; nova vigência exige data posterior à mais recente e fecha o intervalo anterior na véspera; serialização por `select_for_update` no funcionário + unicidade `(employee, valid_from)` | Sem sobreposição e sem reescrever linhas passadas | Constraint de exclusão no PostgreSQL (btree_gist) fica como endurecimento pendente; concorrência real não validada (sem PostgreSQL) |
| D18 | Escopo do gestor em `Membership.scope_units/scope_sectors` pela lotação **atual**; escopo vazio não concede acesso; administrador não usa escopo; gestor só lê | Fecha D11 | Quando a lotação muda, o funcionário sai do escopo do gestor anterior (histórico permanece no banco) |
| D19 | CPF opcional, só dígitos, validado por dígito verificador, mascarado em listagens e para gestores; nunca vai para auditoria | Minimização (LGPD) | Obrigatoriedade/uso do CPF em registros do REP-P a confirmar na etapa 5/12 (validação especializada) |
| D20 | "Hoje" para vigência usa a data UTC do servidor (`TIME_ZONE=UTC`) | Simplicidade | Pode divergir da data local da unidade por horas; tratar com fuso da unidade na apuração (etapa 8) |
| D21 | Importação CSV é tudo ou nada, só cria funcionários (não atualiza), até 2000 linhas / 1 MB, com prévia obrigatória por `commit=false` | Erros compreensíveis por linha e nenhuma gravação parcial | Atualização em massa fica como melhoria |
| D22 | Funcionário nunca é apagado: inativação mantém lotações e jornadas | Preserva histórico | Contagem de ativos para cobrança usa `is_active` (etapa 13) |

## Notas da revisão da etapa 3 (21/10/2026)
- D16/D17: atribuição também bloqueia a jornada, compartilhando a serialização com a edição de dias. Inativação dos destinos é revalidada sob bloqueio. Concorrência real segue pendente no PostgreSQL.
- D18: catálogo e detalhe de jornadas do gestor se limitam às jornadas atribuídas aos funcionários atualmente visíveis, incluindo seus históricos. Escopo vazio não libera o catálogo.
- D21: prévia obrigatória do mesmo CSV/sessão/empresa, identificada por hash sem armazenar seu conteúdo na sessão; gravação revalida os dados. Limite de 1 MB em bytes UTF-8, parser estrito e rejeição de prefixos de fórmula. Detalhes em [03-revisao.md](etapas/03-revisao.md).

## Etapa 4 — autorização e gestão dos tablets
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D23 | Ativação por código temporário de 10 caracteres (alfabeto sem ambíguos), 15 min, uso único; só o SHA-256 é guardado; exibido uma vez ao administrador | Entrada manual no tablet com segredo de curta vida | Novo código invalida os anteriores; limite de 10 tentativas/min por IP em `/api/device/activate/` |
| D24 | Credencial individual `id.segredo` (256 bits, hash SHA-256 no banco), validade de 30 dias, rotação com janela de 10 min para a anterior | Credencial por aparelho, revogável; resposta perdida na rotação não tranca o tablet | Tablet rotaciona após 20 dias; limite offline = validade da credencial (tratar na etapa 7) |
| D25 | Autenticação do dispositivo (`Authorization: Device …`) separada da sessão de usuário; sem CSRF; escopo (empresa/unidade) vem sempre do dispositivo | Evita confusão de credenciais e IDOR via corpo da requisição | Sessão de usuário não acessa `/api/device/*` e credencial de dispositivo não acessa a API de usuários |
| D26 | Revogação/renovação: derruba todas as credenciais na hora (efeito no próximo acesso online); renovação volta o cadastro a "aguardando ativação" com código novo | Perda/roubo do aparelho | Revogação offline não é possível: documentado para a etapa 7 |
| D27 | Consulta de matrícula pelo tablet: só correspondência exata, funcionário ativo lotado hoje na unidade do aparelho, sem CPF, sem listagem | Terminal compartilhado precisa identificar por matrícula sem expor o cadastro | Base para o 1:1 da etapa 6; limite 120 req/min por dispositivo |
| D28 | Localização opt-in: só é gravada se o administrador ligar `collect_location` com justificativa (constraint no banco); tratada como indício, não prova; identificação de hardware informada pelo aparelho é só dica de inventário | Minimização e transparência (LGPD) | Retenção/descarte das evidências de localização a definir (validação jurídica) |
| D29 | Tentativas de uso por dispositivo revogado são auditadas no máximo 1 vez a cada 10 min por dispositivo | Evita inundar a auditoria | Cache local no throttle/dedupe; trocar por cache compartilhado em produção multiprocesso |

## Notas da revisão da etapa 4 (21/10/2026)
- D23: throttle usa `REMOTE_ADDR`, sem confiar em `X-Forwarded-For`; leitura/escrita do contador é serializada entre threads locais. Ativação, renovação e revogação bloqueiam primeiro o dispositivo, depois códigos/credenciais. Teste de ativação simultânea incluído, pendente no PostgreSQL.
- D24: rotação mantém uma única sucessora. Retry com a anterior durante a janela devolve o mesmo token, sem estender validade. Sucessoras só podem gerar outra credencial após 20 dias; a primeira rotação permanece disponível. O segredo sucessor usa HMAC-SHA-256 com `SECRET_KEY`, domínio específico e segredo apresentado, persistindo apenas seu hash. `SECRET_KEY_FALLBACKS` permite recuperar retries durante troca de chave. Sem chave anterior, credenciais já emitidas continuam autenticando pelo hash, mas o retry da rotação antiga exige renovar a ativação. Não se pode calcular a cadeia offline conhecendo apenas um token antigo.
- D26: rotação revalida validade/revogação sob bloqueio; ativação e rotação incluem auditoria na mesma transação. Respostas com código/token enviam `Cache-Control: no-store`.
- D27/D29: cota usa o ID do dispositivo, compartilhada entre credenciais, e não muda com rotação ou cabeçalhos. A serialização local não substitui cache e operação atômica compartilhados em produção multiprocesso.
- D28: constraint rejeita também justificativa composta apenas por espaços; localização revalida consentimento e credencial sob bloqueio do dispositivo. Migration aditiva `0002` e substituição da constraint em `0003`; conferir dados legados antes de migrar banco persistente.
- Flutter: operações de credencial serializadas, heartbeat a cada minuto enquanto a tela está montada e token/data em um único registro seguro. Falhas de armazenamento não equivalem a ausência de credencial. Código ainda não compilado; SDK, Android real e política offline permanecem pendentes.

## Etapa 5 — núcleo de marcação (requisitos em docs/requisitos-rep-p.md)
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D30 | NSR por **unidade** (`NsrCounter`), alocado com `select_for_update` na mesma transação da marcação | Anexo IX, item 6: sequência por estabelecimento, de 1 em 1 | Unidade ≡ estabelecimento é suposição a validar; rollback devolve o número, sem lacuna pelo fluxo transacional. Escrita direta continua sendo uma lacuna de proteção |
| D31 | Horário oficial da marcação = relógio do **servidor**; o horário do tablet é guardado (`device_reported_at`, `clock_skew_seconds`) sem bloquear | Anexo IX, 2 e 8.2: hora confiável / Hora Legal Brasileira | Sincronismo NTP do servidor e política de divergência (±30 s) são operação (etapas 7 e 14/15) |
| D32 | Sem API de alteração; ORM bloqueia alteração/exclusão; gatilhos bloqueiam UPDATE/DELETE e TRUNCATE PostgreSQL; SQLite também bloqueia REPLACE de linhas existentes | Anexo IX, 7: "não apagados ou alterados, direta ou indiretamente" | INSERT arbitrário e contador ainda não protegidos. Quem tem DDL pode remover gatilhos. Testes transacionais PostgreSQL desabilitam gatilhos somente no flush do banco descartável; ativos durante as asserções |
| D33 | Hash SHA-256 encadeado por unidade (hash do registro anterior), versionado (`v1-anexo-v-historico`), com verificação (`verify_timeclock`) | Anexo V histórico / Anexo IX | O layout vigente está no portal gov.br: **conferir** (pendência 1). Nova versão não reescreve registros antigos |
| D34 | Idempotência por `(dispositivo, client_event_id)`; reenvio devolve o original (200) sem consumir NSR; mesmo id com dados diferentes devolve o original | Falhas de rede não podem duplicar nem perder | O tablet reutiliza o id enquanto não houver resposta definitiva. Duas marcações legítimas próximas têm ids diferentes e ambas são gravadas |
| D35 | Marcação **nunca** é recusada por escala, jornada, disponibilidade, horário, CPF ausente ou unidade inativada depois da ativação | Portaria 671, art. 74; não perder marcação | Falta de CPF é sinalizada no comprovante (`pending_fields`) e deverá ser tratada no AFD (etapa 12) |
| D36 | Identificação por provedor (`PROVIDERS`); hoje só `registration` (matrícula), permitido por `TIMECLOCK_ALLOW_REGISTRATION_ONLY` (padrão ligado) | Contrato para a verificação facial (etapa 6) | Matrícula isolada **não é identificação forte**; desligar em produção quando houver facial |
| D37 | Comprovante entregue como JSON informativo (campos do art. 79, CPF mascarado no terminal, campos faltantes listados) | Terminal compartilhado; o PDF assinado depende de certificado ICP-Brasil | PDF/PAdES, INPI e Atestado Técnico: externos (etapas 11–12 e pendências) |
| D38 | `declared_kind` (entrada/intervalo/saída informado no terminal) é informativo e fica fora do hash; a apuração decide | O REP-P não registra tipo; evita decidir semântica trabalhista no registro | A etapa 8 usa a ordem das marcações e as regras vigentes |
| D39 | Só marcações (tipo 7) consomem NSR; registros de empregador/relógio/empregado/eventos sensíveis (ARP 6.1–6.4) ficam na auditoria append-only | A interpretação do NSR compartilhado é jurídica | Pendência 3 de requisitos-rep-p.md |
| D40 | `occurred_local_date` (data no fuso da unidade) gravada com a marcação | Filtros e apuração por dia local, não UTC | Imutável como o resto do registro |

## Notas da revisão da etapa 5 (22/10/2026)
- D33: AFD 004 consultado no portal oficial; DH e campos comparados. Preenchimento com zeros versus espaços e vetor exato do hash seguem pendentes. Nenhum hash histórico reescrito.
- D34: serviço revalida dispositivo/credencial sob bloqueio. Flutter guarda payload pendente por matrícula em memória; alternância de trabalhadores não descarta a tentativa. Reinício do app ainda perde esses eventos (persistência na etapa 7). Recusa após resposta perdida não prova ausência do registro anterior.
- D37: comprovante informativo novo usa snapshot imutável de empregador/local/INPI. Linhas antigas sem snapshot sinalizam ausência histórica; não se preenchem com dados atuais. CPF do empregador mascarado para gestor/terminal e omitido da auditoria; disponível ao administrador para cadastro.
- D40 não muda D20: lotação vigente ainda segue data UTC. A diferença entre data local do ponto e data UTC da lotação precisa de decisão de produto antes de mudar o comportamento das etapas 3–4.
- Proposta de rotina exclusiva de append no PostgreSQL e permissões restritas em [05-revisao.md](etapas/05-revisao.md). Não implementada: muda a autoridade de gravação e o provisionamento do banco. Etapa não aprovada para avanço.

## Decisão do Claude sobre a proposta da revisão da etapa 5
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D41 | **Rotina exclusiva de append no PostgreSQL** (EXECUTE only, aplicação sem INSERT/UPDATE/DELETE direto na ARP e no contador, dono de migrations separado) fica como **item obrigatório da etapa 14** (revisão de segurança) e é provisionada na etapa 15; não é implementada agora | Muda a autoridade de gravação e o provisionamento do banco: só faz sentido junto com os papéis reais de produção, e só pode ser provada com PostgreSQL e o papel real da aplicação | Até lá, a garantia é: aplicação não escreve fora do serviço (sem API), ORM/gatilhos bloqueiam alteração, e `verify_timeclock` **detecta** cadeia quebrada (detecção ≠ prevenção). A etapa 5 não é declarada pronta para produção |
| D42 | Data de vigência de lotação continua em UTC (D20) mesmo com `occurred_local_date` local (D40) | Mudar afeta etapas 3–4 e é decisão de produto | Divergência de até algumas horas perto da meia-noite local; tratar na apuração (etapa 8) |

## Etapa 6 — reconhecimento facial (avaliação em docs/avaliacao-motor-biometrico.md)
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D43 | Template biométrico guardado **criptografado com AES-256-GCM** (nonce aleatório, AAD = empresa+funcionário+motor), chaves identificadas por id com rotação; **imagem nunca é persistida**; nenhuma API devolve template, chave ou imagem | Dado sensível (LGPD); template copiado para outro registro não decifra | Chave em variável de ambiente (`BIOMETRIC_KEYS`); KMS/HSM, backup sem material em claro e crypto-shredding por registro: etapa 14/15. Exclusão zera o conteúdo; cópias antigas podem sobreviver em páginas não vacuumadas/backups |
| D44 | **Motor real BLOQUEADO** (decisão do produto: custo/fornecedor/licença). Contrato `BiometricEngine` + adaptador por configuração; **simulador** só com `DJANGO_DEBUG=true` (configuração recusa iniciar em produção com ele; tentativas gravam `engine=simulator`; marcação com verificação simulada é recusada se `BIOMETRIC_ALLOW_SIMULATOR` for falso) | Não desenvolver algoritmo próprio nem contratar serviço pago; não vender teste de simulador como antifraude | O aceite da etapa 6 fica **bloqueado** até haver motor real com vivacidade validada |
| D45 | Fluxo em dois passos: verificação 1:1 devolve **token de uso único** (60 s, preso ao dispositivo e ao funcionário) consumido **na mesma transação** da marcação; reenvio do mesmo evento devolve a marcação original mesmo com token já consumido | Auditoria por tentativa e sem perder marcação em falha | Falha na gravação não consome o token |
| D46 | Bloqueio da verificação facial do funcionário após 5 falhas (`no_match`/`liveness_failed`) em 10 min; qualidade ruim não conta; sucesso zera a contagem | Dificultar tentativa repetida de fraude | Risco de negação de serviço contra um colega: mitigado pela exceção autorizada |
| D47 | **Exceção autorizada**: código de 8 dígitos, só o hash guardado, amarrado ao funcionário, uso único, 15 min, criado por administrador ou gestor do escopo, com motivo, auditado; marcação grava `authorized_exception` | Alternativa de identificação para falha de câmera, rosto não cadastrado ou bloqueio | Visível no histórico de marcações; revisão posterior (etapa 9) |
| D48 | `Company.identification_mode`: `registration` (só matrícula, não é identificação forte) ou `face` (exige face com `liveness=passed` ou exceção). Tablet recebe o modo no escopo | Política por empresa | No modo `face` sem motor real nenhum tablet marca, exceto por código de exceção |
| D49 | Consentimento registrado pelo administrador (versão da política e referência do termo); revogar **exclui** o template | LGPD: base legal e consentimento | Base legal definitiva (art. 11), RIPD e política: validação jurídica |
| D50 | Retenção: `purge_biometrics --inactive-days N` e exclusão manual; **sem prazo padrão** | Prazo é decisão jurídica | Agendar a rotina na etapa 15 quando houver prazo |
| D51 | **Não se promete reconhecimento facial offline** | Nenhum candidato foi validado em Android; template no aparelho amplia a exposição | A etapa 7 define a alternativa offline e suas condições |

## Etapa 7 — operação offline e sincronização (só Claude Code; sem revisão do Codex)
| # | Decisão | Justificativa | Consequência |
|---|---------|---------------|--------------|
| D52 | Marcação offline **só por matrícula** e **só** com `Company.offline_policy = registration_only` (padrão `disabled`). Face e exceção autorizada não funcionam offline | Nenhum motor facial foi validado em Android; template no aparelho amplia a exposição; exceção depende do servidor | Registro gravado como `registration_offline` e sinalizado para revisão; vale também para empresa em modo `face` (rebaixamento deliberado e visível). Sem a política, o tablet sem conexão não registra |
| D53 | Sincronização em **lote** (`POST /api/device/punches/batch/`, até 50) com **resultado por evento**: `confirmed`, `duplicate` ou `rejected` (+ motivo). Cada evento em transação própria; falha de autenticação interrompe o lote (401/403) e os já gravados permanecem | Lote parcialmente recebido e reenvio sem duplicar | O tablet trata cada evento; o que não recebe resposta definitiva volta a `pending`; sem progresso, o envio para |
| D54 | Horário: o tablet envia o horário **original** e o último desvio medido (servidor − aparelho) com o horário do servidor da medição. O servidor grava `occurred_at` corrigido, `recorded_at` = recebimento, `clock_skew_seconds` = aparelho − servidor e sinalizações (`clock_unverified`, `clock_skew_large` >30 s, `clock_offset_stale` >24 h, `time_in_future`, `before_device_activation`). Mais antigo que 35 dias é recusado; futuro é limitado ao recebimento | O relógio do tablet não é confiável; não se perde marcação por relógio errado | A correção estima o horário; **não** prova a Hora Legal Brasileira (pendência de requisitos) |
| D55 | O NSR segue a **ordem de recebimento**, não a cronológica | NSR é a sequência de gravação na ARP | O horário real está em `occurred_at`; a apuração (etapa 8) ordena por ele |
| D56 | Funcionário **inativo** ou **sem lotação** na unidade na data do evento é aceito e sinalizado (`employee_inactive`, `not_assigned_to_unit`); matrícula inexistente na empresa é recusada e fica visível | Não perder marcação; o terminal offline não valida a matrícula | **Risco aceito:** quem tem a credencial do tablet pode lançar marcações offline de qualquer funcionário da empresa dentro de 35 dias (todas sinalizadas). Mitigações: política desligada por padrão, flags e revisão (etapa 9), revogação, auditoria do lote. Limite diário de eventos por aparelho **não** implementado |
| D57 | Credencial revogada/expirada: 401 e a **fila permanece** no tablet; reativando o mesmo cadastro (novo código), a fila é enviada. Sem tolerância de credencial expirada | A reativação é o ato de autorização do administrador | Offline por mais de 30 dias exige reativação; nada é apagado no aparelho |
| D58 | Fila do tablet: armazenamento seguro do Android, estados `pending → sent → confirmed | rejected | acknowledged`, recuperação após reinício (`sent` → `pending`), JSON ilegível vai para **quarentena** (nunca descartado), limite de 2000 eventos, escopo e desvio de relógio persistidos | Sobreviver a fechamento/reinício e operar sem conexão após reabrir | Proteção em repouso **não** garante integridade em aparelho com root: controles compensatórios são as flags e a revisão no servidor |
| D59 | Confirmação offline é **provisória** (horário do aparelho, sem NSR/hash). O comprovante com NSR só existe após a sincronização | Impossível emitir NSR sem o servidor | Pendência para validação especializada (Anexo IX itens 4–5; art. 80) |
| D60 | Idempotência ponta a ponta: o tablet enfileira com o **mesmo `client_event_id`** da tentativa que falhou; se o servidor chegou a gravar, o lote devolve `duplicate` | Timeout após commit é indistinguível de falha | Coberto por testes no backend e no Dart |
| D61 | `sync_flags` são informativas e ficam fora do hash. A migration 0005 remove e reinstala os gatilhos de imutabilidade e a guarda contra `REPLACE` ao alterar a tabela | O SQLite reconstrói a tabela e perderia os gatilhos | Padrão para futuras migrations em `timeclock_timerecord` |
