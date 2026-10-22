from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from apps.audit import services as audit

from . import services
from .models import DeviceStatus

KEYWORD = b"device"


class DeviceForbidden(APIException):
    status_code = 403
    default_code = "device_forbidden"
    default_detail = "Dispositivo sem autorização."


class DeviceAuthentication(BaseAuthentication):
    """`Authorization: Device <id>.<segredo>`. Independente da sessão de usuário (sem CSRF).

    Escopo (empresa/unidade) vem sempre do dispositivo autenticado, nunca do corpo da requisição.
    """

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != KEYWORD:
            return None
        try:
            token = parts[1].decode()
        except UnicodeDecodeError:
            raise AuthenticationFailed("Credencial inválida.") from None
        credential = services.find_credential(token)
        if credential is None:
            raise AuthenticationFailed("Credencial inválida.")
        device = credential.device
        if credential.revoked_at is not None or device.status == DeviceStatus.REVOKED:
            self._note_revoked_attempt(request, device)
            raise AuthenticationFailed("Dispositivo revogado.", code="device_revoked")
        if credential.expires_at <= timezone.now():
            raise AuthenticationFailed("Credencial expirada.", code="credential_expired")
        if device.status != DeviceStatus.ACTIVE:
            raise AuthenticationFailed("Dispositivo não ativado.", code="device_inactive")
        if not device.company.is_active:
            raise DeviceForbidden("Empresa inativa.")
        request.device = device
        return AnonymousUser(), credential

    def authenticate_header(self, request):
        return "Device"

    @staticmethod
    def _note_revoked_attempt(request, device):
        # Um tablet revogado que insiste a cada poucos segundos não pode inundar a auditoria.
        key = f"device-revoked-audit:{device.pk}"
        if cache.add(key, 1, timeout=600):
            audit.record(
                request,
                "device.revoked_access_attempt",
                company=device.company,
                target=device,
                actor_email=f"dispositivo:{device.pk}",
            )


class IsDevice(BasePermission):
    def has_permission(self, request, view):
        return request.auth is not None and hasattr(request, "device")


class DeviceRateThrottle(SimpleRateThrottle):
    scope = "device"

    def get_cache_key(self, request, view):
        auth = request.auth
        return self.cache_format % {
            "scope": self.scope,
            "ident": getattr(auth, "pk", self.get_ident(request)),
        }
