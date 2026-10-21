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
