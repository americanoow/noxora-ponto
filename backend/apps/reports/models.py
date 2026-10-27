from django.conf import settings
from django.db import models


class TimesheetAcknowledgement(models.Model):
    """Ciência do funcionário sobre o espelho de um período fechado (instantâneo identificado pelo hash).

    Registro de ciência, não assinatura eletrônica qualificada: a forma exigida (se houver) depende de
    validação especializada.
    """

    closing = models.ForeignKey(
        "attendance.PeriodClosing", on_delete=models.PROTECT, related_name="acknowledgements"
    )
    employee = models.ForeignKey("operations.Employee", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    employee_snapshot_sha256 = models.CharField(max_length=64)
    acknowledged_at = models.DateTimeField(auto_now_add=True)
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["closing", "employee"], name="uniq_ack_closing_employee"),
        ]
