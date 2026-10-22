import datetime
import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import ActivationCode, DeviceCredential, DeviceStatus

# Sem caracteres ambíguos (0/O, 1/I/L): o código é digitado à mão no tablet.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
INVALID_CODE = "Código inválido ou expirado."


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


def format_code(code: str) -> str:
    return f"{code[:5]}-{code[5:]}"


def new_activation_code(device) -> tuple[str, ActivationCode]:
    """Invalida códigos anteriores ainda não usados e gera um novo (retornado uma única vez)."""
    now = timezone.now()
    device.activation_codes.filter(used_at__isnull=True).update(used_at=now)
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    record = ActivationCode.objects.create(
        device=device,
        code_hash=_hash(code),
        expires_at=now + datetime.timedelta(minutes=settings.DEVICE_ACTIVATION_TTL_MINUTES),
    )
    return format_code(code), record


def issue_credential(device) -> str:
    secret = secrets.token_urlsafe(32)
    credential = DeviceCredential.objects.create(
        device=device,
        secret_hash=_hash(secret),
        expires_at=timezone.now() + datetime.timedelta(days=settings.DEVICE_CREDENTIAL_TTL_DAYS),
    )
    return f"{credential.pk}.{secret}"


def find_credential(token: str):
    """Retorna a credencial se o segredo confere, senão None. Não avalia validade."""
    cred_id, _, secret = token.partition(".")
    if not cred_id.isascii() or not cred_id.isdigit() or not secret or len(token) > 200:
        return None
    credential = (
        DeviceCredential.objects.select_related("device", "device__company").filter(pk=cred_id).first()
    )
    if credential is None or not hmac.compare_digest(credential.secret_hash, _hash(secret)):
        return None
    return credential


def activate(raw_code: str, *, app_version: str = "", hardware_hint: str = ""):
    """Troca o código temporário por uma credencial. Retorna (device, token)."""
    code = normalize_code(raw_code)
    if len(code) != CODE_LENGTH:
        raise ValidationError({"detail": INVALID_CODE})
    now = timezone.now()
    with transaction.atomic():
        record = (
            ActivationCode.objects.select_for_update()
            .select_related("device", "device__company", "device__unit")
            .filter(code_hash=_hash(code))
            .first()
        )
        device = record.device if record else None
        if (
            record is None
            or record.used_at is not None
            or record.expires_at <= now
            or device.status != DeviceStatus.PENDING
            or not device.company.is_active
            or not device.unit.is_active
        ):
            raise ValidationError({"detail": INVALID_CODE})
        record.used_at = now
        record.save(update_fields=["used_at"])
        device.status = DeviceStatus.ACTIVE
        device.activated_at = now
        device.revoked_at = None
        device.last_seen_at = now
        device.app_version = app_version[:32]
        device.hardware_hint = hardware_hint[:128]
        device.save()
        token = issue_credential(device)
    return device, token


def revoke(device):
    now = timezone.now()
    device.credentials.filter(revoked_at__isnull=True).update(revoked_at=now)
    device.activation_codes.filter(used_at__isnull=True).update(used_at=now)
    device.status = DeviceStatus.REVOKED
    device.revoked_at = now
    device.save(update_fields=["status", "revoked_at"])


def reissue(device):
    """Renovação: derruba as credenciais atuais e volta a aguardar ativação com código novo."""
    now = timezone.now()
    device.credentials.filter(revoked_at__isnull=True).update(revoked_at=now)
    device.status = DeviceStatus.PENDING
    device.revoked_at = None
    device.save(update_fields=["status", "revoked_at"])
    return new_activation_code(device)[0]


def rotate(credential):
    """Emite credencial nova; a anterior segue válida só por uma janela curta (resposta perdida)."""
    grace = timezone.now() + datetime.timedelta(minutes=settings.DEVICE_ROTATION_GRACE_MINUTES)
    with transaction.atomic():
        locked = DeviceCredential.objects.select_for_update().get(pk=credential.pk)
        if locked.revoked_at is not None:
            raise ValidationError({"detail": "Credencial revogada."})
        if locked.expires_at > grace:
            locked.expires_at = grace
            locked.save(update_fields=["expires_at"])
        return issue_credential(credential.device)


def connectivity(device) -> str:
    if device.status != DeviceStatus.ACTIVE or device.last_seen_at is None:
        return "never" if device.last_seen_at is None else "offline"
    age = (timezone.now() - device.last_seen_at).total_seconds()
    return "online" if age <= settings.DEVICE_ONLINE_SECONDS else "stale"
