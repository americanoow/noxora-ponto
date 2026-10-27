"""Apuração (etapa 8) e tratamento (etapa 9): regras versionadas, feriados, ajustes, abonos e fechamento.

Nada aqui altera marcação (`timeclock.TimeRecord`). Ajustes são registros separados, com justificativa,
decisão e auditoria; a apuração usa as marcações originais mais os ajustes aprovados.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ImmutableError(Exception):
    pass


class CalculationRuleSet(models.Model):
    """Versão das regras de apuração da empresa, válida a partir de `valid_from`. Nunca é editada."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()
    valid_from = models.DateField()
    params = models.JSONField()
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valid_from", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["company", "version"], name="uniq_ruleset_version"),
            models.UniqueConstraint(fields=["company", "valid_from"], name="uniq_ruleset_valid_from"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ImmutableError("Regras de apuração não são editadas: crie uma nova versão.")
        super().save(*args, **kwargs)


class Holiday(models.Model):
    """Feriado da empresa (todas as unidades) ou de uma unidade. Cadastro da empresa: o produto não
    presume calendário municipal/estadual."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    unit = models.ForeignKey(
        "operations.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    date = models.DateField()
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "date"], condition=Q(unit__isnull=True), name="uniq_holiday_company_date"
            ),
            models.UniqueConstraint(
                fields=["company", "unit", "date"],
                condition=Q(unit__isnull=False),
                name="uniq_holiday_unit_date",
            ),
        ]


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    APPROVED = "approved", "Aprovado"
    REJECTED = "rejected", "Recusado"
    CANCELLED = "cancelled", "Cancelado"


class AdjustmentKind(models.TextChoices):
    INCLUDE = "include", "Inclusão de marcação"
    DISREGARD = "disregard", "Desconsiderar marcação"


class PunchAdjustment(models.Model):
    """Pedido de ajuste: incluir uma marcação esquecida ou desconsiderar uma marcação na apuração.

    A marcação original continua intacta e visível; o ajuste só muda a apuração depois de aprovado.
    """

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="punch_adjustments"
    )
    kind = models.CharField(max_length=10, choices=AdjustmentKind.choices)
    record = models.ForeignKey(
        "timeclock.TimeRecord", null=True, blank=True, on_delete=models.PROTECT, related_name="adjustments"
    )
    occurred_at = models.DateTimeField(null=True, blank=True)  # inclusão: instante informado
    reference_date = models.DateField()  # data local da jornada afetada (fechamento de período)
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        indexes = [models.Index(fields=["company", "status", "-requested_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="include", occurred_at__isnull=False, record__isnull=True))
                | (Q(kind="disregard", record__isnull=False, occurred_at__isnull=True)),
                name="adjustment_kind_fields",
            ),
            models.UniqueConstraint(
                fields=["record"],
                condition=Q(kind="disregard", status__in=["pending", "approved"]),
                name="uniq_open_disregard_per_record",
            ),
        ]


class JustificationKind(models.TextChoices):
    MEDICAL = "medical", "Atestado médico"
    JUSTIFIED_ABSENCE = "justified_absence", "Falta justificada"
    EXTERNAL_WORK = "external_work", "Trabalho externo"
    COMPENSATION = "compensation", "Compensação"
    OTHER = "other", "Outro"


class DayJustification(models.Model):
    """Abono de um dia (ou parte dele): reduz o saldo negativo na apuração depois de aprovado."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="justifications"
    )
    date = models.DateField()
    kind = models.CharField(max_length=20, choices=JustificationKind.choices)
    minutes = models.PositiveIntegerField(
        null=True, blank=True
    )  # vazio = dia inteiro (todo o saldo negativo)
    reason = models.CharField(max_length=500)
    document_ref = models.CharField(max_length=200, blank=True)  # nº/identificação do documento, sem anexo
    status = models.CharField(max_length=10, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(minutes__isnull=True) | Q(minutes__gt=0), name="justification_minutes"
            ),
        ]


class ClosingStatus(models.TextChoices):
    CLOSED = "closed", "Fechado"
    REOPENED = "reopened", "Reaberto"


class PeriodClosing(models.Model):
    """Fechamento de período: congela o resultado da apuração (instantâneo + hash) para folha e espelho.

    Reabrir não apaga: muda o status para `reopened` com motivo; um novo fechamento cria outra linha.
    """

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    start = models.DateField()
    end = models.DateField()
    status = models.CharField(max_length=10, choices=ClosingStatus.choices, default=ClosingStatus.CLOSED)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    engine_version = models.CharField(max_length=20)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(auto_now_add=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-start", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(end__gte=F("start")), name="closing_range"),
        ]
