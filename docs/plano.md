# Plano do Noxora Ponto

SaaS multiempresa de ponto eletrônico (REP-P, Portaria MTP 671/2021) e gestão operacional, com tablets e reconhecimento facial 1:1. Stack: Django + DRF + PostgreSQL, React + TypeScript + Vite, Flutter (Android). Detalhes da visão original no prompt do projeto; regras em [CLAUDE.md](../CLAUDE.md).

## Etapas e critérios de aceite (resumo)
| # | Etapa | Aceite essencial |
|---|-------|------------------|
| 1 | Estrutura inicial | Backend+banco sobem, saúde/prontidão, frontend consulta API, Flutter compila (ou pendente), CI |
| 2 | Empresas, autenticação, permissões | Dois clientes isolados, sem escalada, sessões expiradas negadas |
| 3 | Cadastros da operação | Funcionários, unidades, setores, jornadas com histórico e importação validada |
| 4 | Gestão de tablets | Ativação, credencial por dispositivo, revogação online |
| 5 | Núcleo de marcação | Idempotência, imutabilidade, comprovantes validados, concorrência |
| 6 | Reconhecimento facial | Motor via interface, 1:1, antifraude integrado, dados protegidos |
| 7 | Offline e sincronização | Fila persistente, reenvio idempotente, divergência de relógio |
| 8 | Apuração | Cenários de referência, regras versionadas, explicação do cálculo |
| 9 | Ajustes e fechamento | Fluxo completo, fechamento e reabertura auditados |
| 10 | Disponibilidade por setor | Painel, informação desatualizada, independente do ponto |
| 11 | Portal e relatórios | Acesso só ao autorizado, exportação autorizada |
| 12 | Arquivos técnicos e folha | Formatos versionados, integração real com um sistema |
| 13 | Assinaturas | Ciclo em testes, webhooks idempotentes |
| 14 | Segurança, desempenho, recuperação | Isolamento demonstrado, restore executado |
| 15 | Implantação e validação | Fluxo ponta a ponta, docs de operação, produção só com autorização |

Critérios completos: seção 10 do prompt original (guardado pelo usuário). Adaptações aprovadas: ver [decisoes-tecnicas.md](decisoes-tecnicas.md).

## Níveis de status
Implementado, Testado, Revisado pelo Codex, Validado externamente, Implantado: registrar separadamente em [progresso.md](progresso.md).
