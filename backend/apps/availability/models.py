"""Disponibilidade operacional (etapa 10). SEPARADA do ponto legal: não cria, altera nem valida marcação.

Cada mudança é uma linha nova (histórico só de inclusão); o estado atual é a linha mais recente. Um estado
vence (`expires_at`) ou fica desatualizado após `stale_after_minutes` sem confirmação.
"""

from django.conf import settings
from django.db import models


class Status(models.TextChoices):
    AVAILABLE = "available", "Disponível"
    BUSY = "busy", "Ocupado"
    ON_BREAK = "on_break", "Em pausa"
    AWAY = "away", "Ausente temporariamente"
    EXTERNAL = "external", "Em atividade externa"
    UNAVAILABLE = "unavailable", "Indisponível"


class AvailabilityUpdate(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey("operations.Employee", on_delete=models.PROTECT, related_name="availability")
    status = models.CharField(max_length=12, choices=Status.choices)
    note = models.CharField(max_length=140, blank=True)
    source = models.CharField(max_length=10, choices=[("manager", "Gestor"), ("employee", "Funcionário")])
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    set_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-set_at", "-id"]
        indexes = [models.Index(fields=["employee", "-set_at"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Histórico de disponibilidade não é editado: registre um novo estado.")
        super().save(*args, **kwargs)


class AvailabilitySettings(models.Model):
    company = models.OneToOneField(
        "companies.Company", primary_key=True, on_delete=models.PROTECT, related_name="+"
    )
    # Módulo opcional, desligado por padrão. Desligado, nada é exibido nem gravado (o histórico fica).
    enabled = models.BooleanField(default=False)
    stale_after_minutes = models.PositiveIntegerField(default=120)
    show_punch_hint = models.BooleanField(default=True)  # mostrar "entrou às 08:02" (só leitura do ponto)
