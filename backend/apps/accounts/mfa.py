import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import totp
from .models import RecoveryCode, TotpDevice

PENDING_SECONDS = 300
MAX_PENDING_ATTEMPTS = 5


def _keys():
    for secret in [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]:
        yield hashlib.sha256(b"noxora-mfa-v1:" + secret.encode()).digest()


def _aad(user_id) -> bytes:
    return f"noxora-mfa:{user_id}".encode()


def _encrypt(user_id, secret: str):
    nonce = os.urandom(12)
    return nonce, AESGCM(next(_keys())).encrypt(nonce, secret.encode(), _aad(user_id))


def _decrypt(device) -> str | None:
    for key in _keys():
        try:
            return (
                AESGCM(key)
                .decrypt(bytes(device.nonce), bytes(device.ciphertext), _aad(device.user_id))
                .decode()
            )
        except InvalidTag:
            continue
    return None


def _recovery_hash(user_id, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"noxora-recovery:{user_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def enabled(user) -> bool:
    return TotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def start_setup(user) -> str:
    """(Re)cria o segredo NÃO confirmado. Com MFA já ativo, exige desativar antes."""
    with transaction.atomic():
        if enabled(user):
            raise ValueError("O segundo fator já está ativo.")
        TotpDevice.objects.filter(user=user).delete()
        secret = totp.new_secret()
        nonce, ciphertext = _encrypt(user.pk, secret)
        TotpDevice.objects.create(user=user, nonce=nonce, ciphertext=ciphertext)
    return secret


def confirm_setup(user, code) -> list[str] | None:
    """Confirma com um código válido e devolve 10 códigos de recuperação (mostrados uma única vez)."""
    with transaction.atomic():
        device = TotpDevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=True).first()
        secret = _decrypt(device) if device else None
        step = totp.verify(secret, code) if secret else None
        if step is None:
            return None
        device.confirmed_at, device.last_step = timezone.now(), step
        device.save(update_fields=["confirmed_at", "last_step"])
        RecoveryCode.objects.filter(user=user).delete()
        codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
        RecoveryCode.objects.bulk_create(
            RecoveryCode(user=user, code_hash=_recovery_hash(user.pk, c)) for c in codes
        )
        return codes


def check(user, code) -> bool:
    """Código TOTP (sem reuso) ou código de recuperação (uso único)."""
    if not isinstance(code, str):
        return False
    code = code.strip()
    with transaction.atomic():
        device = TotpDevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
        if device is None:
            return False
        secret = _decrypt(device)
        step = totp.verify(secret, code, last_step=device.last_step) if secret else None
        if step is not None:
            device.last_step = step
            device.save(update_fields=["last_step"])
            return True
        recovery = (
            RecoveryCode.objects.select_for_update()
            .filter(user=user, code_hash=_recovery_hash(user.pk, code.lower()), used_at__isnull=True)
            .first()
        )
        if recovery is not None:
            recovery.used_at = timezone.now()
            recovery.save(update_fields=["used_at"])
            return True
    return False


def disable(user):
    TotpDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
