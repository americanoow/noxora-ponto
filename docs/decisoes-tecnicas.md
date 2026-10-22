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
