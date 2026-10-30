"""Operações sensíveis da conta (MFA, reautenticação): limite de tentativas e login recente.

- Falhas por usuário e operação (não por IP) com espera crescente: 3 falhas → 30 s, 5 → 5 min,
  8 ou mais → 30 min. Acerto zera. O contador vive no cache (Redis em produção).
- Antes de configurar, confirmar ou desativar o MFA, o login precisa ser recente (`login_at` ou `auth_at`
  na sessão,
  gravados em todo login e renovados por `POST /api/auth/reauth/` com a senha).
"""

import time

from django.core.cache import cache
from rest_framework.exceptions import APIException, PermissionDenied

REAUTH_SECONDS = 15 * 60
_STEPS = ((8, 30 * 60), (5, 5 * 60), (3, 30))  # (falhas, espera em segundos), da mais severa para a menor
_KEEP = 24 * 3600


class TooManyAttempts(APIException):
    status_code = 429
    default_code = "too_many_attempts"

    def __init__(self, wait):
        super().__init__(
            {"detail": f"Muitas tentativas. Aguarde {wait} s e tente de novo.", "code": "throttled"}
        )
        self.wait = wait


def _key(user, operation):
    return f"sensitive:{operation}:{user.pk}"


def wait_seconds(user, operation) -> int:
    state = cache.get(_key(user, operation))
    return max(0, int(state["until"] - time.time())) if state else 0


def guard(user, operation):
    """Recusa (429) enquanto a espera da operação não terminou."""
    wait = wait_seconds(user, operation)
    if wait:
        raise TooManyAttempts(wait)


def register_failure(user, operation):
    key = _key(user, operation)
    state = cache.get(key) or {"fails": 0, "until": 0}
    state["fails"] += 1
    for fails, wait in _STEPS:
        if state["fails"] >= fails:
            state["until"] = time.time() + wait
            break
    cache.set(key, state, _KEEP)


def reset(user, operation):
    cache.delete(_key(user, operation))


def require_recent_login(request):
    # `login_at` é gravado em todo login; `auth_at`, na reautenticação por senha. Vale o mais recente.
    stamps = [request.session.get(k) for k in ("login_at", "auth_at")]
    at = max((v for v in stamps if isinstance(v, (int, float))), default=None)
    if at is None or time.time() - at > REAUTH_SECONDS:
        error = PermissionDenied("Por segurança, confirme sua senha para continuar.")
        error.detail = {
            "detail": "Por segurança, confirme sua senha para continuar.",
            "code": "reauth_required",
        }
        raise error
