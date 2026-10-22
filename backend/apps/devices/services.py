import datetime
import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import ActivationCode, Device, DeviceCredential, DeviceStatus

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


@transaction.atomic
def new_activation_code(device) -> tuple[str, ActivationCode]:
    """Invalida códigos anteriores ainda não usados e gera um novo (retornado uma única vez)."""
    device = Device.objects.select_for_update(no_key=True).get(pk=device.pk)
    now = timezone.now()
    device.activation_codes.filter(used_at__isnull=True).update(used_at=now)
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    record = ActivationCode.objects.create(
        device=device,
        code_hash=_hash(code),
        expires_at=now + datetime.timedelta(minutes=settings.DEVICE_ACTIVATION_TTL_MINUTES),
    )
    return format_code(code), record


def issue_credential(device, *, secret=None) -> str:
    secret = secret or secrets.token_urlsafe(32)
    credential = DeviceCredential.objects.create(
        device=device,
        secret_hash=_hash(secret),
        expires_at=timezone.now() + datetime.timedelta(days=settings.DEVICE_CREDENTIAL_TTL_DAYS),
    )
    return f"{credential.pk}.{secret}"


def find_credential(token: str):
    """Retorna a credencial se o segredo confere, senão None. Não avalia validade."""
    cred_id, _, secret = token.partition(".")
    if (
        len(token) > 200
        or not cred_id.isascii()
        or not cred_id.isdigit()
        or len(cred_id) > 19
        or not 0 < int(cred_id) <= 2**63 - 1
        or not secret
    ):
        return None
    credential = (
        DeviceCredential.objects.select_related("device", "device__company").filter(pk=cred_id).first()
    )
    if credential is None or not hmac.compare_digest(credential.secret_hash, _hash(secret)):
        return None
    credential._presented_secret = secret
    return credential


def activate(raw_code: str, *, app_version: str = "", hardware_hint: str = ""):
    """Troca o código temporário por uma credencial. Retorna (device, token)."""
    code = normalize_code(raw_code)
    if len(code) != CODE_LENGTH:
        raise ValidationError({"detail": INVALID_CODE})
    with transaction.atomic():
        # Ordem única: dispositivo antes de códigos/credenciais em todos os escritores.
        candidate = ActivationCode.objects.filter(code_hash=_hash(code)).first()
        if candidate is None:
            raise ValidationError({"detail": INVALID_CODE})
        device = Device.objects.select_for_update(no_key=True).get(pk=candidate.device_id)
        record = ActivationCode.objects.select_for_update(no_key=True).get(pk=candidate.pk)
        now = timezone.now()
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


@transaction.atomic
def revoke(device):
    device.refresh_from_db(from_queryset=Device.objects.select_for_update(no_key=True))
    now = timezone.now()
    device.credentials.filter(revoked_at__isnull=True).update(revoked_at=now)
    device.activation_codes.filter(used_at__isnull=True).update(used_at=now)
    device.status = DeviceStatus.REVOKED
    device.revoked_at = now
    device.save(update_fields=["status", "revoked_at"])


@transaction.atomic
def reissue(device):
    """Renovação: derruba as credenciais atuais e volta a aguardar ativação com código novo."""
    device.refresh_from_db(from_queryset=Device.objects.select_for_update(no_key=True))
    now = timezone.now()
    device.credentials.filter(revoked_at__isnull=True).update(revoked_at=now)
    device.status = DeviceStatus.PENDING
    device.revoked_at = None
    device.save(update_fields=["status", "revoked_at"])
    return new_activation_code(device)[0]


def rotate(credential):
    """Retry retorna a mesma sucessora, sem prolongar a janela nem multiplicar tokens."""
    with transaction.atomic():
        device = Device.objects.select_for_update(no_key=True).get(pk=credential.device_id)
        locked = DeviceCredential.objects.select_for_update(no_key=True).get(pk=credential.pk)
        now = timezone.now()
        if (
            locked.revoked_at is not None
            or locked.expires_at <= now
            or device.status != DeviceStatus.ACTIVE
            or not device.company.is_active
        ):
            raise ValidationError({"detail": "Credencial sem autorização."})
        # HMAC com chave do servidor: conhecer o token antigo não permite calcular
        # sucessores offline depois que a janela de tolerância terminar.
        # O banco continua contendo apenas hashes, nunca o token recuperável.
        message = b"noxora:device-rotation:v1:" + credential._presented_secret.encode()
        secret = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()
        if locked.rotated_to_id:
            successor = locked.rotated_to
            if successor.revoked_at is not None or successor.expires_at <= now:
                raise ValidationError({"detail": "Credencial sem autorização."})
            for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
                retry_secret = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
                if hmac.compare_digest(successor.secret_hash, _hash(retry_secret)):
                    return f"{successor.pk}.{retry_secret}"
            raise ValidationError({"detail": "Não foi possível recuperar a rotação. Renove a ativação."})
        if (
            DeviceCredential.objects.filter(rotated_to=locked).exists()
            and locked.created_at + datetime.timedelta(days=20) > now
        ):
            raise ValidationError({"detail": "Credencial ainda não precisa de rotação."})
        token = issue_credential(device, secret=secret)
        locked.rotated_to_id = int(token.partition(".")[0])
        grace = now + datetime.timedelta(minutes=settings.DEVICE_ROTATION_GRACE_MINUTES)
        locked.expires_at = min(locked.expires_at, grace)
        locked.save(update_fields=["expires_at", "rotated_to"])
        return token


def connectivity(device) -> str:
    if device.status != DeviceStatus.ACTIVE or device.last_seen_at is None:
        return "never" if device.last_seen_at is None else "offline"
    age = (timezone.now() - device.last_seen_at).total_seconds()
    return "online" if age <= settings.DEVICE_ONLINE_SECONDS else "stale"
