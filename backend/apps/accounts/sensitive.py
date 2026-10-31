"""Operações sensíveis da conta (login, MFA, reautenticação): limite de tentativas e login recente.

- Falhas por conta e operação (não só por IP) com espera crescente: 3 falhas → 30 s, 5 → 5 min,
  8 ou mais → 30 min. Acerto zera. O contador vive no cache (Redis em produção).
- Login por senha: contado pelo e-mail digitado (exista ou não a conta, para não revelar cadastros), com
  espera mais branda (10 → 1 min, 20 → 15 min) para que um terceiro não tranque a conta de alguém.
- Antes de configurar, confirmar ou desativar o MFA, o login precisa ser recente (`login_at` ou `auth_at`
  na sessão, gravados em todo login e renovados por `POST /api/auth/reauth/` com a senha).
"""

import hashlib
import time

from django.core.cache import cache
from rest_framework.exceptions import APIException, PermissionDenied

REAUTH_SECONDS = 15 * 60
_STEPS = ((8, 30 * 60), (5, 5 * 60), (3, 30))  # (falhas, espera em segundos), da mais severa para a menor
LOGIN_STEPS = ((20, 15 * 60), (10, 60))
MFA_LOGIN_STEPS = ((20, 30 * 60), (10, 5 * 60))  # por conta, somando os logins (cada login aceita 5)
_KEEP = 24 * 3600


class TooManyAttempts(APIException):
    status_code = 429
    default_code = "too_many_attempts"

    def __init__(self, wait):
        super().__init__(
            {"detail": f"Muitas tentativas. Aguarde {wait} s e tente de novo.", "code": "throttled"}
        )
        self.wait = wait


def email_subject(email) -> str:
    """Chave do e-mail digitado no login (resumo, sem guardar o e-mail em claro no cache)."""
    normalized = (email or "").strip().lower() if isinstance(email, str) else ""
    return hashlib.sha256(normalized.encode()).hexdigest()


def _key(subject, operation):
    ident = subject if isinstance(subject, str) else subject.pk
    return f"sensitive:{operation}:{ident}"


def wait_seconds(subject, operation) -> int:
    state = cache.get(_key(subject, operation))
    return max(0, int(state["until"] - time.time())) if state else 0


def guard(subject, operation):
    """Recusa (429) enquanto a espera da operação não terminou."""
    wait = wait_seconds(subject, operation)
    if wait:
        raise TooManyAttempts(wait)


def register_failure(subject, operation, steps=_STEPS):
    key = _key(subject, operation)
    state = cache.get(key) or {"fails": 0, "until": 0}
    state["fails"] += 1
    for fails, wait in steps:
        if state["fails"] >= fails:
            state["until"] = time.time() + wait
            break
    cache.set(key, state, _KEEP)


def reset(subject, operation):
    cache.delete(_key(subject, operation))


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
