# Etapa 2 — Empresas, autenticação e permissões: implementação

## Entregue
- Apps `companies` (Company, Membership, papéis), `audit` (AuditLog append-only) e extensão de `accounts` (login/logout/me, recuperação de acesso, sessões, `is_platform_admin`).
- API: `/api/auth/{csrf,login,logout,me,password-reset,password-reset/confirm}/`, `/api/companies/`, `/api/companies/{id}/`, `.../members/`, `.../members/{id}/`, `.../audit/`.
- Isolamento: `resolve_company()` (único ponto de entrada) + `require_role()`. Detalhes em decisoes-tecnicas.md (D6–D12).
- Sessões: ociosa 1 h deslizante, absoluta 12 h (middleware), troca de senha encerra sessões. Login com throttle (10/min) e recuperação (5/h), resposta idêntica para e-mail existente ou não.
- Frontend: login, recuperação/definição de senha, painel de acessos (admin da empresa) e de empresas (plataforma); CSRF.

## Verificações executadas
- Backend: 64 testes (SQLite): acesso cruzado por papel, escalada, vínculo duplicado, plataforma, sessão (ociosa/absoluta/troca de senha), recuperação, auditoria. Ruff e `makemigrations --check` limpos.
- Frontend: 19 testes, lint, typecheck, build.

## Pendências
- Sem PostgreSQL/Docker nem Flutter (herdado). MFA e escopo por unidade/setor não implementados (ver D11).
- Convites enviam link por e-mail via backend console em desenvolvimento; SMTP real não configurado.
