import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.companies.models import Role

from .models import Assignment, Employee, EmployeeSchedule, ScheduleDay, Sector, Unit, WorkSchedule


def validate_cpf(raw: str) -> str:
    """Retorna só os dígitos do CPF ou levanta ValueError. Vazio é aceito (campo opcional)."""
    raw = raw.strip()
    if not raw:
        return ""
    if any(not (ch.isascii() and ch.isdigit()) and ch not in ".- " for ch in raw):
        raise ValueError("CPF inválido.")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 11 or len(set(digits)) == 1:
        raise ValueError("CPF inválido.")
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        if int(digits[size]) != (total * 10 % 11) % 10:
            raise ValueError("CPF inválido.")
    return digits


def mask_cpf(cpf: str) -> str:
    return f"***.***.***-{cpf[-2:]}" if cpf else ""


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("Fuso horário inválido.") from exc
    return name


def today():
    return timezone.localdate()


def current_q(prefix=""):
    """Filtro de vigência para hoje, para modelos com valid_from/valid_to."""
    d = today()
    return Q(**{f"{prefix}valid_from__lte": d}) & (
        Q(**{f"{prefix}valid_to__isnull": True}) | Q(**{f"{prefix}valid_to__gte": d})
    )


def current_assignment(employee):
    """Lotação vigente hoje, ou None. Usa as lotações já carregadas quando houver prefetch."""
    d = today()
    for a in employee.assignments.all():
        if a.valid_from <= d and (a.valid_to is None or a.valid_to >= d):
            return a
    return None


def visible_employees(request, company):
    """Funcionários que o vínculo atual pode ver. Administrador: todos; gestor: apenas o seu escopo."""
    membership = request.membership
    employees = Employee.objects.filter(company=company)
    if membership.role == Role.COMPANY_ADMIN:
        return employees
    if membership.role == Role.MANAGER:
        in_scope = (
            Assignment.objects.filter(employee=OuterRef("pk"))
            .filter(current_q())
            .filter(Q(unit__in=membership.scope_units.all()) | Q(sector__in=membership.scope_sectors.all()))
        )
        return employees.filter(Exists(in_scope))
    raise PermissionDenied("Você não tem permissão para esta operação.")


def visible_unit_ids(membership):
    """Ids de unidades visíveis ao gestor (escopo direto + unidade dos setores de escopo)."""
    ids = set(membership.scope_units.values_list("pk", flat=True))
    ids |= set(membership.scope_sectors.values_list("unit_id", flat=True))
    return ids


def _validate_interval_start(model_qs, valid_from, field):
    last = model_qs.order_by("-valid_from").first()
    if last and valid_from <= last.valid_from:
        raise ValidationError({field: "A nova vigência deve começar depois da vigência mais recente."})
    return last


def _close_previous(last, valid_from):
    if last and (last.valid_to is None or last.valid_to >= valid_from):
        last.valid_to = valid_from - datetime.timedelta(days=1)
        last.save(update_fields=["valid_to"])


def assign_unit(employee, company, unit, sector, valid_from):
    """Muda a lotação a partir de `valid_from` sem reescrever o passado."""
    if unit.company_id != company.pk or not unit.is_active:
        raise ValidationError({"unit": "Unidade inválida."})
    if sector is not None and (
        sector.company_id != company.pk or sector.unit_id != unit.pk or not sector.is_active
    ):
        raise ValidationError({"sector": "Setor inválido para a unidade."})
    with transaction.atomic():
        unit = Unit.objects.select_for_update().get(pk=unit.pk, company=company)
        if not unit.is_active:
            raise ValidationError({"unit": "Unidade inválida."})
        if sector is not None:
            sector = Sector.objects.select_for_update().get(pk=sector.pk, company=company, unit=unit)
            if not sector.is_active:
                raise ValidationError({"sector": "Setor inválido para a unidade."})
        locked = Employee.objects.select_for_update().get(pk=employee.pk, company=company)
        last = _validate_interval_start(locked.assignments, valid_from, "valid_from")
        _close_previous(last, valid_from)
        return Assignment.objects.create(employee=locked, unit=unit, sector=sector, valid_from=valid_from)


def assign_schedule(employee, company, schedule, valid_from):
    if schedule.company_id != company.pk or not schedule.is_active:
        raise ValidationError({"schedule": "Jornada inválida."})
    with transaction.atomic():
        schedule = WorkSchedule.objects.select_for_update().get(pk=schedule.pk, company=company)
        if not schedule.is_active:
            raise ValidationError({"schedule": "Jornada inválida."})
        locked = Employee.objects.select_for_update().get(pk=employee.pk, company=company)
        last = _validate_interval_start(locked.schedule_assignments, valid_from, "valid_from")
        _close_previous(last, valid_from)
        return EmployeeSchedule.objects.create(employee=locked, schedule=schedule, valid_from=valid_from)


def replace_schedule_days(schedule, days):
    """Troca os dias da jornada. Só permitido enquanto nenhuma atribuição a usa (preserva o histórico)."""
    with transaction.atomic():
        locked = WorkSchedule.objects.select_for_update().get(pk=schedule.pk)
        if locked.assignments.exists():
            raise ValidationError(
                {"days": "Esta jornada já foi atribuída e não pode ser alterada. Crie uma nova jornada."}
            )
        locked.days.all().delete()
        ScheduleDay.objects.bulk_create([ScheduleDay(schedule=locked, **day) for day in days])


def employee_for_device(device, registration):
    """Funcionário ativo, de matrícula exata, lotado hoje na unidade do dispositivo (ou None).

    Fonte única do escopo do terminal: consulta de matrícula e marcação usam a mesma regra.
    """
    current = Assignment.objects.filter(employee=OuterRef("pk"), unit_id=device.unit_id).filter(current_q())
    return (
        Employee.objects.filter(company_id=device.company_id, registration=registration, is_active=True)
        .filter(Exists(current))
        .first()
    )
