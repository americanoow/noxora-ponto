from django.db import models


class AppendOnlyError(Exception):
    pass


class TimeRecordQuerySet(models.QuerySet):
    """Marcações são imutáveis. Além disto, gatilhos no banco bloqueiam UPDATE/DELETE/TRUNCATE."""

    def update(self, **kwargs):
        raise AppendOnlyError("Marcações de ponto não podem ser alteradas.")

    def delete(self):
        raise AppendOnlyError("Marcações de ponto não podem ser apagadas.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AppendOnlyError("Marcações de ponto não podem ser alteradas.")

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise AppendOnlyError("Marcações de ponto não podem ser alteradas.")
        return super().bulk_create(objs, **kwargs)


class NsrCounter(models.Model):
    """Sequência do NSR por unidade (estabelecimento) e último hash da cadeia.

    A linha é bloqueada (`select_for_update`) durante a gravação da marcação, o que serializa a
    alocação do NSR e do encadeamento por unidade.
    """

    unit = models.OneToOneField(
        "operations.Unit", primary_key=True, on_delete=models.PROTECT, related_name="+"
    )
    last_nsr = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, blank=True)


class DeclaredKind(models.TextChoices):
    NONE = "", "Não informado"
    ENTRY = "entry", "Entrada"
    BREAK_START = "break_start", "Início de intervalo"
    BREAK_END = "break_end", "Fim de intervalo"
    EXIT = "exit", "Saída"


class TimeRecord(models.Model):
    """Marcação de ponto (registro tipo 7 do REP-P). Imutável; correções são registros separados (etapa 9)."""

    nsr = models.BigIntegerField()
    unit = models.ForeignKey("operations.Unit", on_delete=models.PROTECT, related_name="+")
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey("operations.Employee", on_delete=models.PROTECT, related_name="time_records")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, related_name="time_records")
    # Identificador gerado pelo tablet por tentativa de marcação: torna o reenvio idempotente.
    client_event_id = models.UUIDField()

    occurred_at = models.DateTimeField()  # data/hora da marcação (UTC); fuso em occurred_offset_minutes
    occurred_offset_minutes = models.SmallIntegerField()
    occurred_local_date = models.DateField()  # data da marcação no fuso da unidade (filtros e apuração)
    recorded_at = models.DateTimeField()  # data/hora da gravação (UTC)
    recorded_offset_minutes = models.SmallIntegerField()
    offline = models.BooleanField(default=False)
    collector_code = models.CharField(max_length=2, default="01")
    # Informações do aparelho, preservadas como foram enviadas. O horário oficial é o do servidor.
    device_reported_at = models.DateTimeField(null=True, blank=True)
    clock_skew_seconds = models.IntegerField(null=True, blank=True)

    # Instantâneos no momento da marcação (cadastro pode mudar depois; o registro não).
    cpf = models.CharField(max_length=11, blank=True)
    employee_name = models.CharField(max_length=200)
    registration = models.CharField(max_length=30)

    # Informativo, fora do hash: o que o trabalhador indicou no terminal. A apuração (etapa 8) decide.
    declared_kind = models.CharField(max_length=12, blank=True, choices=DeclaredKind.choices)
    identification_method = models.CharField(max_length=24)
    identification_ref = models.CharField(
        max_length=64, blank=True
    )  # p.ex. id da verificação facial (etapa 6)

    hash_version = models.CharField(max_length=32)
    prev_hash = models.CharField(max_length=64, blank=True)
    record_hash = models.CharField(max_length=64)

    objects = TimeRecordQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["unit", "nsr"], name="uniq_timerecord_unit_nsr"),
            models.UniqueConstraint(
                fields=["device", "client_event_id"], name="uniq_timerecord_device_event"
            ),
        ]
        indexes = [
            models.Index(fields=["company", "-occurred_at"]),
            models.Index(fields=["employee", "-occurred_at"]),
            models.Index(fields=["company", "-occurred_local_date"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError("Marcações de ponto não podem ser alteradas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Marcações de ponto não podem ser apagadas.")
