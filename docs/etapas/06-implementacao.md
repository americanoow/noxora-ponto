# Etapa 6 — Reconhecimento facial: implementação

**Status: implementada até o limite possível; ACEITE BLOQUEADO pela ausência de motor biométrico real.** Avaliação, licenças e riscos em [avaliacao-motor-biometrico.md](../avaliacao-motor-biometrico.md).

## Entregue
- App `biometrics`: consentimento (`BiometricConsent`), template criptografado (`BiometricTemplate`, AES-256-GCM com AAD e rotação de chave), tentativas de verificação (`VerificationAttempt`, sem imagem/template), exceção autorizada (`ExceptionAuthorization`).
- Contrato `BiometricEngine` (cadastro e verificação 1:1, qualidade, vivacidade) e `SimulatorEngine` **apenas para testes**.
- Painel (`/api/companies/{id}/…`): status, consentimento (registrar/revogar), cadastro (1–5 imagens, base64 estrito e limite de tamanho), exclusão, exceção autorizada (admin ou gestor do escopo) e política de identificação por empresa.
- Tablet (`/api/device/face/verify/`): verificação 1:1 no escopo da unidade; resultado `success`, `no_match`, `liveness_failed`, `poor_quality`, `no_template`, `no_consent`, `locked` ou `engine_unavailable` (503); token de uso único para a marcação.
- Marcação (`timeclock`): métodos `face` e `authorized_exception` registrados como provedores; política `face` exige vivacidade aprovada; consumo do token na mesma transação da gravação.
- Retenção: `purge_biometrics --inactive-days N [--dry-run]`.
- Frontend: botão "Identificação" por funcionário (consentimento, fotos, exclusão, exceção com código exibido uma vez) e seletor de política na aba Empregador.
- Flutter: `verifyFace`, `punch` com identificação, escopo com `identification_mode`, aviso quando a câmera não existe (não compilado).
- Decisões D43–D51.

## Verificações executadas
- Backend: 285 testes em SQLite (5 ignorados) e **289 em PostgreSQL 17.5 real** (1 ignorado); ruff e `makemigrations --check` limpos. Cobrem: criptografia (AAD, rotação, adulteração), template fora de logs/auditoria/respostas, consentimento, exclusão e substituição, imagens inválidas, resultados de falha, bloqueio por tentativas, token único/expirado/de outro dispositivo ou funcionário, falha sem consumir o token, reenvio idempotente, política facial e vivacidade, recusa do simulador fora de debug, exceção (código, uso único, escopo, expiração), isolamento entre empresas e retenção.
- Frontend: 51 testes, lint, typecheck, build.

## O que NÃO foi demonstrado (bloqueios)
1. **Fluxo real de identificação com rosto**: não há motor real. Os testes usam o simulador e **não comprovam eficácia nem antifraude**.
2. **Captura pela câmera no tablet**: não implementada (e o Flutter não foi compilado). O app só consegue marcar por exceção autorizada no modo facial.
3. Validações jurídicas e de eficácia listadas em avaliacao-motor-biometrico.md.
