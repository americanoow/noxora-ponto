"""Monta a apuração a partir do banco e aplica o fluxo de ajustes, abonos e fechamento."""

import datetime as dt
import hashlib
import json
from zoneinfo import ZoneInfo

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.companies.models import Company, Role
from apps.operations.models import Assignment, Employee, EmployeeSchedule
from apps.timeclock.models import TimeRecord

from . import calculation as calc
from .models import (
    AdjustmentKind,
    CalculationRuleSet,
    ClosingStatus,
    DayJustification,
    Holiday,
    PeriodClosing,
    PunchAdjustment,
    RequestStatus,
)

MAX_PERIOD_DAYS = 62
DEFAULT_TZ = "America/Sao_Paulo"


def parse_period(start, end) -> tuple[dt.date, dt.date]:
    if start is None or end is None:
        raise ValidationError({"detail": "Informe o período (from e to, AAAA-MM-DD)."})
    if end < start:
        raise ValidationError({"to": "O fim do período deve ser igual ou posterior ao início."})
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValidationError({"detail": f"Período máximo de {MAX_PERIOD_DAYS} dias."})
    return start, end


# ---------- Regras ----------


def rule_sets(company):
    return list(CalculationRuleSet.objects.filter(company=company).order_by("valid_from"))


def rule_ranges(company, start, end):
    """[(início, fim, versão, params)] cobrindo o período, pela vigência das versões."""
    sets = rule_sets(company)
    ranges = []
    day = start
    while day <= end:
        current = None
        for rs in sets:
            if rs.valid_from <= day:
                current = rs
        nxt = next((rs.valid_from for rs in sets if rs.valid_from > day), None)
        stop = min(end, nxt - dt.timedelta(days=1)) if nxt else end
        if current is None:
            ranges.append((day, stop, 0, calc.validate_params({})))
        else:
            ranges.append((day, stop, current.version, calc.validate_params(current.params)))
        day = stop + dt.timedelta(days=1)
    return ranges


def create_rule_set(*, company, user, params, valid_from, note=""):
    try:
        merged = calc.validate_params(params)
    except ValueError as exc:
        raise ValidationError({"params": str(exc)}) from None
    with transaction.atomic():
        Company.objects.select_for_update(no_key=True).get(pk=company.pk)
        ensure_open(company, valid_from, field="valid_from", through_future=True)
        last = CalculationRuleSet.objects.filter(company=company).order_by("-version").first()
        if CalculationRuleSet.objects.filter(company=company, valid_from=valid_from).exists():
            raise ValidationError({"valid_from": "Já existe uma versão com esta vigência."})
        return CalculationRuleSet.objects.create(
            company=company,
            version=(last.version + 1) if last else 1,
            valid_from=valid_from,
            params=merged,
            note=note[:300],
            created_by=user,
        )


# ---------- Fechamento ----------


def closed_period_for(company, date):
    return PeriodClosing.objects.filter(
        company=company, status=ClosingStatus.CLOSED, start__lte=date, end__gte=date
    ).first()


def ensure_open(company, date, *, field="date", through_future=False):
    """Recusa alteração que afete período fechado. `through_future`: a mudança vale de `date` em diante."""
    closings = PeriodClosing.objects.filter(company=company, status=ClosingStatus.CLOSED)
    blocked = (
        closings.filter(end__gte=date).exists()
        if through_future
        else closings.filter(start__lte=date, end__gte=date).exists()
    )
    if blocked:
        raise ValidationError({field: "Período fechado. Reabra o fechamento para alterar."})


# ---------- Montagem da apuração ----------


def _employee_tz(employee, end) -> ZoneInfo:
    assignment = (
        Assignment.objects.select_related("unit")
        .filter(employee=employee, valid_from__lte=end)
        .order_by("-valid_from")
        .first()
    )
    return ZoneInfo(assignment.unit.timezone if assignment else DEFAULT_TZ)


def _unit_ids_by_date(employee, start, end):
    rows = list(
        Assignment.objects.filter(employee=employee, valid_from__lte=end)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=start))
        .values("unit_id", "valid_from", "valid_to")
    )

    def unit_for(day):
        for r in rows:
            if r["valid_from"] <= day and (r["valid_to"] is None or r["valid_to"] >= day):
                return r["unit_id"]
        return None

    return unit_for


def _schedule_lookup(employee, start, end):
    assignments = list(
        EmployeeSchedule.objects.filter(employee=employee, valid_from__lte=end + dt.timedelta(days=1))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=start - dt.timedelta(days=1)))
        .prefetch_related("schedule__days")
    )

    def schedule_for(day):
        for a in assignments:
            if a.valid_from <= day and (a.valid_to is None or a.valid_to >= day):
                for d in a.schedule.days.all():
                    if d.weekday == day.weekday():
                        return d
                return None
        return None

    return schedule_for


def _holiday_lookup(employee, start, end):
    unit_for = _unit_ids_by_date(employee, start, end)
    rows = list(
        Holiday.objects.filter(company_id=employee.company_id, date__gte=start, date__lte=end).values(
            "date", "unit_id", "name"
        )
    )

    def holiday_for(day):
        unit = unit_for(day)
        for r in rows:
            if r["date"] == day and (r["unit_id"] is None or r["unit_id"] == unit):
                return r["name"]
        return ""

    return holiday_for


def effective_marks(employee, start, end) -> list[calc.Mark]:
    """Marcações originais (menos as desconsideradas por ajuste aprovado) e inclusões aprovadas."""
    window_start = dt.datetime.combine(start - dt.timedelta(days=2), dt.time(), tzinfo=dt.UTC)
    window_end = dt.datetime.combine(end + dt.timedelta(days=3), dt.time(), tzinfo=dt.UTC)
    approved = PunchAdjustment.objects.filter(employee=employee, status=RequestStatus.APPROVED)
    disregarded = set(approved.filter(kind=AdjustmentKind.DISREGARD).values_list("record_id", flat=True))
    marks = [
        calc.Mark(at=r.occurred_at, record_id=r.pk, flags=tuple(r.sync_flags or ()))
        for r in TimeRecord.objects.filter(
            employee=employee, occurred_at__gte=window_start, occurred_at__lt=window_end
        ).only("id", "occurred_at", "sync_flags")
        if r.pk not in disregarded
    ]
    marks += [
        calc.Mark(at=a.occurred_at, origin="included")
        for a in approved.filter(
            kind=AdjustmentKind.INCLUDE, occurred_at__gte=window_start, occurred_at__lt=window_end
        )
    ]
    return marks


def _apply_justifications(employee, results):
    by_date = {}
    for j in DayJustification.objects.filter(
        employee=employee,
        status=RequestStatus.APPROVED,
        date__gte=results[0].date,
        date__lte=results[-1].date,
    ).order_by("id"):
        by_date.setdefault(j.date, []).append(j)
    for r in results:
        for j in by_date.get(r.date, []):
            if r.deficit_minutes <= 0:
                break
            credit = r.deficit_minutes if j.minutes is None else min(j.minutes, r.deficit_minutes)
            r.deficit_minutes -= credit
            r.justified_minutes += credit
            r.steps.append(f"Abono aprovado ({j.get_kind_display()}): {credit} min.")
            if r.status == "absent" and r.deficit_minutes == 0:
                r.status = "justified"


def compute_employee(employee, start, end) -> dict:
    """Apuração de um funcionário no período, com regras vigentes em cada dia."""
    tz = _employee_tz(employee, end)
    ctx = calc.EmployeeContext(
        tz=tz,
        schedule_for=_schedule_lookup(employee, start, end),
        holiday_for=_holiday_lookup(employee, start, end),
    )
    marks = effective_marks(employee, start, end)
    results, versions = [], []
    for r_start, r_end, version, params in rule_ranges(employee.company, start, end):
        results += calc.compute_period(start=r_start, end=r_end, marks=marks, ctx=ctx, params=params)
        versions.append({"from": r_start.isoformat(), "to": r_end.isoformat(), "version": version})
    _apply_justifications(employee, results)
    return {
        "employee": {"id": employee.pk, "registration": employee.registration, "name": employee.full_name},
        "timezone": str(tz),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "engine_version": calc.RULES_ENGINE_VERSION,
        "rule_versions": versions,
        "days": [r.as_dict() for r in results],
        "totals": calc.totals(results),
        "pending_requests": PunchAdjustment.objects.filter(
            employee=employee, status=RequestStatus.PENDING
        ).count()
        + DayJustification.objects.filter(employee=employee, status=RequestStatus.PENDING).count(),
    }


def snapshot_hash(snapshot) -> str:
    raw = json.dumps(snapshot, sort_keys=True, cls=DjangoJSONEncoder, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def close_period(*, company, user, start, end, employees):
    parse_period(start, end)
    with transaction.atomic():
        Company.objects.select_for_update(no_key=True).get(pk=company.pk)
        overlap = PeriodClosing.objects.filter(
            company=company, status=ClosingStatus.CLOSED, start__lte=end, end__gte=start
        )
        if overlap.exists():
            raise ValidationError({"detail": "Já existe fechamento ativo que cobre parte deste período."})
        pending = (
            PunchAdjustment.objects.filter(
                company=company,
                status=RequestStatus.PENDING,
                reference_date__gte=start,
                reference_date__lte=end,
            ).count()
            + DayJustification.objects.filter(
                company=company, status=RequestStatus.PENDING, date__gte=start, date__lte=end
            ).count()
        )
        if pending:
            raise ValidationError(
                {"detail": f"Há {pending} pedido(s) pendente(s) no período. Decida antes de fechar."}
            )
        snapshot = {"employees": [compute_employee(e, start, end) for e in employees]}
        return PeriodClosing.objects.create(
            company=company,
            start=start,
            end=end,
            snapshot=json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder)),
            snapshot_sha256=snapshot_hash(snapshot),
            engine_version=calc.RULES_ENGINE_VERSION,
            closed_by=user,
        )


def reopen_period(*, closing, user, reason):
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if len(reason) < 5:
        raise ValidationError({"reason": "Informe o motivo da reabertura (mínimo de 5 caracteres)."})
    with transaction.atomic():
        locked = PeriodClosing.objects.select_for_update().get(pk=closing.pk)
        if locked.status != ClosingStatus.CLOSED:
            raise ValidationError({"detail": "Este fechamento já foi reaberto."})
        locked.status = ClosingStatus.REOPENED
        locked.reopened_by, locked.reopened_at, locked.reopen_reason = user, timezone.now(), reason[:500]
        locked.save(update_fields=["status", "reopened_by", "reopened_at", "reopen_reason"])
        return locked


def closing_divergence(closing, employee) -> bool:
    """Verdadeiro se a apuração atual difere do instantâneo (p.ex. marcação offline chegou depois)."""
    for item in closing.snapshot.get("employees", []):
        if item["employee"]["id"] == employee.pk:
            current = json.loads(
                json.dumps(compute_employee(employee, closing.start, closing.end), cls=DjangoJSONEncoder)
            )
            return current["totals"] != item["totals"] or current["days"] != item["days"]
    return True


# ---------- Pedidos: ajustes e abonos ----------


def _clean_reason(value, field="reason"):
    if not isinstance(value, str) or len(value.strip()) < 5:
        raise ValidationError({field: "Informe a justificativa (mínimo de 5 caracteres)."})
    return value.strip()[:500]


def request_adjustment(*, company, employee, user, kind, reason, record=None, occurred_at=None):
    reason = _clean_reason(reason)
    if kind == AdjustmentKind.DISREGARD:
        if record is None or record.employee_id != employee.pk or record.company_id != company.pk:
            raise ValidationError({"record": "Marcação inválida."})
        reference = record.occurred_local_date
        occurred_at = None
    elif kind == AdjustmentKind.INCLUDE:
        if occurred_at is None:
            raise ValidationError({"occurred_at": "Informe data e hora da marcação a incluir."})
        if occurred_at > timezone.now():
            raise ValidationError({"occurred_at": "Não é possível incluir marcação no futuro."})
        reference = occurred_at.astimezone(_employee_tz(employee, occurred_at.date())).date()
        record = None
    else:
        raise ValidationError({"kind": "Use 'include' ou 'disregard'."})
    with transaction.atomic():
        Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        ensure_open(company, reference, field="occurred_at" if record is None else "record")
        if (
            record is not None
            and PunchAdjustment.objects.filter(
                record=record,
                kind=AdjustmentKind.DISREGARD,
                status__in=[RequestStatus.PENDING, RequestStatus.APPROVED],
            ).exists()
        ):
            raise ValidationError({"record": "Já existe pedido aberto ou aprovado para esta marcação."})
        return PunchAdjustment.objects.create(
            company=company,
            employee=employee,
            kind=kind,
            record=record,
            occurred_at=occurred_at,
            reference_date=reference,
            reason=reason,
            requested_by=user,
        )


def request_justification(*, company, employee, user, date, kind, reason, minutes=None, document_ref=""):
    reason = _clean_reason(reason)
    if minutes is not None and (
        isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 < minutes <= 1440
    ):
        raise ValidationError(
            {"minutes": "Informe minutos entre 1 e 1440, ou deixe vazio para o dia inteiro."}
        )
    with transaction.atomic():
        Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        ensure_open(company, date)
        return DayJustification.objects.create(
            company=company,
            employee=employee,
            date=date,
            kind=kind,
            minutes=minutes,
            reason=reason,
            document_ref=(document_ref or "")[:200],
            requested_by=user,
        )


def decide(*, model, pk, company, membership, user, approve, note="", visible_employees):
    """Aprova ou recusa um pedido pendente. Quem pediu não decide o próprio pedido."""
    if membership is None or membership.role not in (Role.COMPANY_ADMIN, Role.MANAGER):
        raise PermissionDenied("Você não tem permissão para esta operação.")
    with transaction.atomic():
        item = (
            model.objects.select_for_update(of=("self",))
            .select_related("employee")
            .filter(pk=pk, company=company)
            .first()
        )
        if item is None or not visible_employees.filter(pk=item.employee_id).exists():
            from django.http import Http404

            raise Http404
        if item.status != RequestStatus.PENDING:
            raise ValidationError({"detail": "Este pedido já foi decidido."})
        if item.requested_by_id == user.pk:
            raise PermissionDenied("Quem fez o pedido não pode decidi-lo.")
        if item.employee.access_user_id == user.pk:
            raise PermissionDenied("Ninguém decide pedidos sobre o próprio ponto.")
        reference = item.reference_date if isinstance(item, PunchAdjustment) else item.date
        ensure_open(company, reference)
        if not approve and len((note or "").strip()) < 5:
            raise ValidationError({"note": "Informe o motivo da recusa (mínimo de 5 caracteres)."})
        item.status = RequestStatus.APPROVED if approve else RequestStatus.REJECTED
        item.decided_by, item.decided_at = user, timezone.now()
        item.decision_note = (note or "").strip()[:500]
        item.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        return item


def cancel(*, item, user):
    with transaction.atomic():
        locked = type(item).objects.select_for_update().get(pk=item.pk)
        if locked.requested_by_id != user.pk:
            raise PermissionDenied("Só quem fez o pedido pode cancelá-lo.")
        if locked.status != RequestStatus.PENDING:
            raise ValidationError({"detail": "Só pedidos pendentes podem ser cancelados."})
        locked.status = RequestStatus.CANCELLED
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_at"])
        return locked
