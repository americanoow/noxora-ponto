# Referência da API (resumo)

Base: `/api`. Painel e portal usam sessão por cookie + CSRF (`GET /api/auth/csrf/` → cabeçalho `X-CSRFToken`). Tablets usam `Authorization: Device <token>`. Erros: JSON `{"detail": ...}` ou `{campo: mensagem}`. Empresa inexistente ou sem vínculo: 404. Papéis: **A** administrador da empresa, **G** gestor (escopo por unidade/setor), **F** funcionário (portal), **P** plataforma Noxora.

## Autenticação (`/api/auth/`)
| Método e rota | Quem | Observações |
|---|---|---|
| GET `csrf/` | público | token CSRF |
| POST `login/` `{email,password}` | público | devolve `me`, ou `{"mfa_required": true}` |
| POST `mfa/verify/` `{code}` | público (sessão pendente) | código TOTP ou de recuperação; 5 tentativas |
| POST/PUT/DELETE `mfa/` | autenticado | iniciar (segredo + `otpauth_uri`), confirmar (`recovery_codes`), desativar (`password`+`code`) |
| POST `logout/`, GET `me/` | autenticado | `me` inclui vínculos e `mfa_enabled` |
| POST `password-reset/`, `password-reset/confirm/` | público | e-mail via outbox |

## Empresa (`/api/companies/{id}/`)
| Recurso | Métodos e papéis |
|---|---|
| `members/`, `members/{id}/`, `audit/` | A |
| `units/`, `sectors/`, `schedules/` | GET A/G; escrita A |
| `employees/`, `employees/{id}/`, `.../assignments/`, `.../schedules/`, `employees/import/` | GET A/G (escopo); escrita A |
| `employer/`, `identification/` (modo, política offline, `face_liveness_policy`, motor) | GET A/G; PATCH A |
| `devices/…` (criar, revogar, `activation-code/`, `locations/`) | A (leitura também G) |
| `employees/{id}/biometric/` (+`consent/`, `enroll/`) | A |
| `employees/{id}/identification-exceptions/` | A/G (escopo): código de exceção de uso único |
| `time-records/`, `time-records/{id}/`, `time-records/{id}/receipt.pdf` | A/G (escopo); somente leitura |
| `attendance/rules/` | GET A/G (padrões + referências legais + versões); POST A (nova versão com `valid_from`) |
| `attendance/holidays/`, `attendance/holidays/{id}/` | GET A/G; POST/DELETE A |
| `attendance/timesheet/?employee=&from=&to=` | A/G: dias com passos explicativos, totais, versões de regra, fechamentos (`divergent`) |
| `attendance/summary/?from=&to=&unit=&sector=` | A/G: totais por funcionário (paginado) |
| `attendance/requests/` | GET A/G (`status`, `employee`); POST A/G: ajuste `{employee_id, kind: include|disregard, occurred_at|record_id, reason}` ou abono `{type: "justification", employee_id, date, kind, minutes?, reason, document_ref?}` |
| `attendance/{adjustments|justifications}/{id}/decision/` | A/G (escopo) `{approve, note}`; quem pediu ou o próprio funcionário não decide |
| `attendance/closings/` | GET A/G; POST A `{start,end}` |
| `attendance/closings/{id}/`, `.../reopen/` `{reason}`, `.../acknowledgements/` | GET A/G; reabrir A |
| `availability/` (GET painel `?unit=&sector=`; POST `{employee_id,status,note,expires_minutes}`), `availability/settings/`, `availability/employees/{id}/` | A/G |
| `reports/timesheet/?employee=&from=&to=&format=pdf|csv`, `reports/summary.csv`, `reports/time-records.csv` | A/G (auditado; CPF completo só A) |
| `fiscal/afd/?unit=&from=&to=`, `fiscal/payroll-profiles/`, `fiscal/payroll-export/?profile=&closing=`, `fiscal/files/` | A |
| `billing/`, `billing/plan/` `{plan_code}`, `billing/cancel/` `{cancel}` | A |
| `me/timesheet/`, `me/timesheet.pdf`, `me/punches/` (48 h por padrão), `me/punches/{id}/receipt/?format=pdf`, `me/requests/`, `me/{kind}/{id}/cancel/`, `me/closings/`, `me/closings/{id}/acknowledge/`, `me/availability/` | F (qualquer papel vinculado a um cadastro de funcionário) |

## Plataforma (`/api/platform/`, P)
`plans/` (GET/POST), `subscriptions/`, `companies/{id}/subscription/` (POST `{plan_code, trial_days}`), `billing/run/`, `invoices/{id}/simulate/` (`{event: paid|failed}`, só sandbox). Empresas: `POST /api/companies/` `{name, admin_email, admin_name}`, `PATCH /api/companies/{id}/`.

## Tablet (`/api/device/`)
`activate/`, `me/`, `heartbeat/` (escopo, `server_time`, políticas), `rotate-credential/`, `location/`, `employees/?registration=`, `punches/` (`{registration, client_event_id, declared_kind?, identification?}`), `punches/batch/` (até 50 eventos offline), `punches/{id}/receipt/`, `face/verify/` (`{registration, image, frames[]}`).

## Webhooks
`POST /api/billing/webhooks/{gateway}/` com `X-Noxora-Signature: sha256=<hmac>`; idempotente por `id` do evento.
