# Etapa 4 — Autorização e gestão dos tablets: implementação

## Entregue
- App `devices`: Device, ActivationCode, DeviceCredential, LocationEvidence (migration 0001).
- Painel (`/api/companies/{id}/devices/`): criar (retorna código uma vez), listar com situação/conectividade/versão, editar nome/unidade/localização, `revoke/`, `activation-code/` (renovação), `locations/`. Administrador escreve; gestor só lê as unidades do seu escopo; funcionário não acessa.
- API do tablet (`/api/device/`): `activate/`, `me/`, `heartbeat/`, `rotate-credential/`, `location/`, `employees/?registration=`.
- Frontend: aba "Tablets" (cadastro, código exibido uma vez, revogar, renovar, localização com justificativa).
- Flutter: `SecureTokenStore` (Keystore/EncryptedSharedPreferences), `DeviceController` (ativação, heartbeat, rotação, revogação), painel de ativação na tela inicial, testes. **Não compilado** (sem SDK).
- Decisões D23–D29.

## Verificações executadas
- Backend: 182 testes (SQLite) incluindo acesso cruzado em todos os endpoints do painel, código único/expirado/uniforme, throttle, credencial adulterada/revogada/expirada, escopo da consulta de matrícula, rotação, renovação, localização (liga/desliga, validações, constraint), auditoria sem segredos. Ruff e `makemigrations --check` limpos.
- Frontend: 38 testes, lint, typecheck, build, prettier.

## Pendências
- Flutter não compilado/testado (inclui flutter_secure_storage em Android real) e Docker/PostgreSQL ausentes.
- Revogação offline impossível por natureza: limite = validade de 30 dias (etapa 7).
- Retenção e descarte de evidências de localização dependem de validação jurídica.
- Limites de requisição e dedupe usam cache local (trocar em produção multiprocesso).
