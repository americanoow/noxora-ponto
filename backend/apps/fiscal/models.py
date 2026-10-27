from django.conf import settings
from django.db import models

PAYROLL_EVENTS = {
    "worked": "Horas trabalhadas",
    "overtime_50": "Horas extras 50%",
    "overtime_100": "Horas extras 100%",
    "overtime_other": "Horas extras (outros percentuais)",
    "night": "Horas noturnas (reduzidas)",
    "deficit": "Horas faltantes / atrasos",
    "absences": "Faltas (dias)",
    "justified": "Horas abonadas",
    "break_suppressed": "Intervalo suprimido",
}


class PayrollExportProfile(models.Model):
    """Mapeamento de eventos da apuração para códigos de rubrica do sistema de folha da empresa.

    Formatos genéricos (CSV e TXT de largura fixa). A integração com um sistema específico depende da
    especificação oficial desse fornecedor (pendente de escolha).
    """

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=80)
    file_format = models.CharField(
        max_length=10, choices=[("csv", "CSV genérico"), ("fixed", "TXT largura fixa")], default="csv"
    )
    event_codes = models.JSONField(default=dict)  # {"overtime_50": "150", ...}
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]


class GeneratedFile(models.Model):
    """Registro de cada arquivo técnico gerado (sem guardar o conteúdo): quem, quando, hash e período."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20)  # afd | payroll
    unit = models.ForeignKey(
        "operations.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    start = models.DateField()
    end = models.DateField()
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    generator_version = models.CharField(max_length=30)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    generated_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-generated_at", "-id"]
