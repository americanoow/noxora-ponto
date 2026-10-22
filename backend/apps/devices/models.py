from django.db import models
from django.db.models import Q


class DeviceStatus(models.TextChoices):
    PENDING = "pending", "Aguardando ativação"
    ACTIVE = "active", "Ativo"
    REVOKED = "revoked", "Revogado"


class Device(models.Model):
    """Tablet autorizado a operar em uma unidade. Nunca é apagado: apenas revogado."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="devices")
    unit = models.ForeignKey("operations.Unit", on_delete=models.PROTECT, related_name="devices")
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=10, choices=DeviceStatus.choices, default=DeviceStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Informado pelo próprio aparelho: dica de apoio ao inventário, NÃO é prova de identidade.
    hardware_hint = models.CharField(max_length=128, blank=True)
    app_version = models.CharField(max_length=32, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Localização só é coletada se ligada explicitamente, com justificativa registrada.
    collect_location = models.BooleanField(default=False)
    location_justification = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(collect_location=False) | Q(location_justification__regex=r"\S"),
                name="device_location_requires_justification",
            )
        ]


class ActivationCode(models.Model):
    """Código temporário de uso único para ativar um tablet. Só o hash é guardado."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="activation_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DeviceCredential(models.Model):
    """Credencial individual do dispositivo. Só o hash do segredo é guardado."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="credentials")
    rotated_to = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="predecessor"
    )
    secret_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class LocationEvidence(models.Model):
    """Evidência de localização informada pelo tablet. Indício, não prova."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="locations")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    captured_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
