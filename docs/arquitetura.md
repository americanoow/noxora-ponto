# Arquitetura

```
tablet (Flutter/Android) ──HTTPS──┐                         ┌── PostgreSQL (dados, gatilhos de integridade)
painel (React/Vite)      ──HTTPS──┼─> Caddy (TLS, estáticos) ─> backend Django+DRF (gunicorn) ─┼── Redis (limites de taxa)
                                  │                                   │                      └── SMTP (via outbox)
                                  │                          worker (run_worker): e-mails, cobrança, verificação da cadeia
```

Monólito modular (D2). Toda regra de negócio fica no backend; o banco reforça as garantias críticas.

## Backend (`backend/apps/`)
| App | Responsabilidade |
|-----|------------------|
| `core` | saúde/prontidão, limite de taxa atômico, IP por proxy confiável, X-Request-ID, logs JSON, `preflight`, `run_worker`, verificações de implantação |
| `accounts` | usuário por e-mail, sessão, recuperação de senha, MFA TOTP opcional, `create_platform_admin`, `reset_mfa` |
| `companies` | empresas, vínculos e papéis (administrador, gestor com escopo, funcionário), `resolve_company` (isolamento) |
| `operations` | unidades, setores, funcionários, lotações e jornadas com vigência (sem sobreposição no PostgreSQL), importação CSV |
| `devices` | tablets: ativação por código, credencial individual com rotação/revogação, heartbeat, localização opt-in |
| `timeclock` | **ARP**: marcações imutáveis, NSR por unidade, hash encadeado, comprovante, sincronização offline em lote |
| `biometrics` | consentimento, template cifrado (AES-256-GCM), verificação 1:1 (OpenCV YuNet+SFace ou simulador), exceção autorizada |
| `attendance` | apuração explicável com regras versionadas, feriados, ajustes/abonos com aprovação, fechamento/reabertura |
| `availability` | disponibilidade operacional por unidade/setor, separada do ponto |
| `reports` | portal do funcionário, espelho PDF/CSV, comprovante PDF, exportações auditadas, ciência do espelho |
| `fiscal` | AFD por estabelecimento, perfis de rubricas e exportação para folha, registro de arquivos gerados |
| `billing` | planos, assinaturas, faturas, gateway sandbox, webhooks idempotentes, limites de plano |
| `notifications` | outbox de e-mails (cifrado em repouso, novas tentativas) |
| `audit` | trilha somente de inclusão (também no banco) |

## Garantias no banco (PostgreSQL)
- `timeclock_timerecord`: UPDATE/DELETE/TRUNCATE bloqueados; INSERT só continua a cadeia (NSR+1, hash anterior, SHA-256 recalculado no banco).
- `timeclock_nsrcounter`: só avança junto com uma marcação gravada; não é apagado.
- `audit_auditlog`: somente inclusão. `attendance_periodclosing`: instantâneo imutável. `attendance_calculationruleset`: imutável.
- Lotações e jornadas: constraint de exclusão (btree_gist) contra vigências sobrepostas.
- Em produção a aplicação usa um papel **sem** ser dono das tabelas (não pode desligar gatilhos nem truncar); só o `migrate` usa o dono.

## Frontend (`frontend/`)
React + TypeScript + Vite. Painel atual cobre autenticação, acessos, cadastros, tablets, biometria e histórico de marcações. As telas das etapas 8–13 (apuração, pedidos, fechamento, disponibilidade, portal, relatórios, arquivos, cobrança) **aguardam as instruções do usuário** para o redesenho; as APIs estão prontas (ver [api.md](api.md)).

## Tablet (`tablet/`)
Flutter (Android): ativação, heartbeat/rotação, marcação online com idempotência, fila offline persistente com sincronização em lote, captura facial pela câmera com desafio de movimento, código de exceção.

## Implantação
`deploy/docker-compose.prod.yml` (db, redis, migrate, backend, worker, edge/Caddy). Ver [operacao.md](operacao.md).
