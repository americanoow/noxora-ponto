from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower


class Unit(models.Model):
    """Unidade (filial/loja) da empresa. Nunca é apagada: apenas inativada."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="units")
    name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    # Local da prestação do serviço / endereço do estabelecimento (comprovante, art. 79, IV).
    address = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(Lower("name"), "company", name="uniq_unit_company_name")]


class Sector(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="sectors")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="sectors")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(Lower("name"), "unit", name="uniq_sector_unit_name")]


class Employee(models.Model):
    """Pessoa que registra jornada. Diferente do usuário de acesso (`access_user`, opcional)."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="employees")
    registration = models.CharField("matrícula", max_length=30)  # imutável após criação
    full_name = models.CharField(max_length=200)
    cpf = models.CharField(max_length=11, blank=True)  # só dígitos; dado pessoal, mascarado nas listagens
    access_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    admission_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    inactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["company", "registration"], name="uniq_employee_registration"),
            models.UniqueConstraint(
                fields=["company", "cpf"], condition=~Q(cpf=""), name="uniq_employee_cpf_company"
            ),
            models.UniqueConstraint(
                fields=["company", "access_user"],
                condition=Q(access_user__isnull=False),
                name="uniq_employee_access_user",
            ),
        ]


class Assignment(models.Model):
    """Lotação com vigência. Linhas passadas nunca são reescritas; só o fim do intervalo aberto."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="assignments")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    sector = models.ForeignKey(Sector, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valid_from", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="assignment_valid_range",
            ),
            models.UniqueConstraint(fields=["employee", "valid_from"], name="uniq_assignment_start"),
        ]


class WorkSchedule(models.Model):
    """Jornada semanal. Imutável depois de atribuída: para mudar, crie outra e atribua com vigência."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="schedules")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(Lower("name"), "company", name="uniq_schedule_company_name")]


class ScheduleDay(models.Model):
    """Dia da jornada. Se `end_time` <= `start_time`, o turno atravessa a meia-noite."""

    schedule = models.ForeignKey(WorkSchedule, on_delete=models.CASCADE, related_name="days")
    weekday = models.PositiveSmallIntegerField()  # 0 = segunda ... 6 = domingo
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(fields=["schedule", "weekday"], name="uniq_schedule_weekday"),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="scheduleday_weekday_range"),
            models.CheckConstraint(condition=~Q(start_time=F("end_time")), name="scheduleday_nonzero"),
        ]


class EmployeeSchedule(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="schedule_assignments")
    schedule = models.ForeignKey(WorkSchedule, on_delete=models.PROTECT, related_name="assignments")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valid_from", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="employeeschedule_valid_range",
            ),
            models.UniqueConstraint(fields=["employee", "valid_from"], name="uniq_employeeschedule_start"),
        ]
