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
    HourBankEntry,
    HourBankKind,
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
        lock_company(company)
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


def lock_company(company):
    """Bloqueio transacional comum de empresa, na mesma ordem em toda operação (empresa e depois
    funcionário/pedido). Fechamento, criação e decisão de pedidos, feriados e regras passam por ele:
    quem chega depois enxerga o resultado de quem chegou antes e a verificação de período fechado
    (`ensure_open`) nunca roda com um fechamento ainda por confirmar."""
    return Company.objects.select_for_update(no_key=True).get(pk=company.pk)


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


def _tz_resolver(employee):
    """Função `data -> fuso` pela lotação vigente em cada data (uma transferência não reescreve o passado).

    Sem lotação na data, vale a mais recente iniciada antes dela; sem nenhuma anterior, a primeira.
    """
    rows = list(Assignment.objects.select_related("unit").filter(employee=employee).order_by("valid_from"))
    zones: dict[str, ZoneInfo] = {}

    def zone(name):
        return zones.setdefault(name, ZoneInfo(name))

    def tz_for(day):
        covering = [r for r in rows if r.valid_from <= day and (r.valid_to is None or r.valid_to >= day)]
        if covering:
            row = covering[-1]
        else:
            before = [r for r in rows if r.valid_from <= day]
            row = before[-1] if before else (rows[0] if rows else None)
        return zone(row.unit.timezone if row else DEFAULT_TZ)

    return tz_for


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
    tz_for = _tz_resolver(employee)
    tz = tz_for(end)
    ctx = calc.EmployeeContext(
        tz=tz,
        schedule_for=_schedule_lookup(employee, start, end),
        holiday_for=_holiday_lookup(employee, start, end),
        tz_for=tz_for,
    )
    marks = effective_marks(employee, start, end)
    results, versions = [], []
    for r_start, r_end, version, params in rule_ranges(employee.company, start, end):
        results += calc.compute_period(
            start=r_start, end=r_end, marks=marks, ctx=ctx, params=params, now=timezone.now()
        )
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


def employees_in_period(queryset, start, end):
    """Funcionários que fazem parte da apuração do período, **independentemente do estado atual**.

    Entram: os ativos; os inativados durante ou depois do início do período; os inativos sem data de
    inativação com lotação no período; e quem tem registro de ponto, ajuste ou abono no período. Assim,
    desativar alguém antes de fechar o mês não tira suas horas já trabalhadas do fechamento nem da folha.
    """
    window_start = start - dt.timedelta(days=1)
    window_end = end + dt.timedelta(days=1)
    in_assignment = Q(assignments__valid_from__lte=end) & (
        Q(assignments__valid_to__isnull=True) | Q(assignments__valid_to__gte=start)
    )
    return queryset.filter(
        Q(is_active=True)
        | Q(inactivated_at__date__gte=start)
        | (Q(inactivated_at__isnull=True) & in_assignment)
        | Q(
            time_records__occurred_local_date__gte=window_start,
            time_records__occurred_local_date__lte=window_end,
        )
        | Q(punch_adjustments__reference_date__gte=start, punch_adjustments__reference_date__lte=end)
        | Q(justifications__date__gte=start, justifications__date__lte=end)
    ).distinct()


def snapshot_hash(snapshot) -> str:
    raw = json.dumps(snapshot, sort_keys=True, cls=DjangoJSONEncoder, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def incomplete_days(snapshot) -> list[dict]:
    """Funcionários com dias de registro incompleto (número ímpar de registros) no instantâneo."""
    out = []
    for item in snapshot["employees"]:
        dates = [d["date"] for d in item["days"] if d["status"] == "inconsistent"]
        if dates:
            out.append({**item["employee"], "dates": dates})
    return out


def close_period(*, company, user, start, end, employees, accept_incomplete=False, exception_reason=""):
    """Fecha o período. Registros incompletos exigem resolução (ajuste aprovado) **ou** uma autorização
    explícita, justificada e auditada: `accept_incomplete=True` com `exception_reason`. A exceção fica
    gravada no instantâneo (e, portanto, no código de verificação) e nos metadados da exportação."""
    parse_period(start, end)
    if end >= timezone.localdate():
        raise ValidationError({"end": "Só é possível fechar períodos já encerrados (fim antes de hoje)."})
    reason = (exception_reason or "").strip() if isinstance(exception_reason, str) else ""
    with transaction.atomic():
        lock_company(company)
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
        incomplete = incomplete_days(snapshot)
        if incomplete:
            total = sum(len(i["dates"]) for i in incomplete)
            if not accept_incomplete:
                raise ValidationError(
                    {
                        "detail": (
                            f"Há {total} dia(s) com registro incompleto em {len(incomplete)} funcionário(s). "
                            "Resolva com um ajuste aprovado ou autorize o fechamento com exceção, "
                            "informando o motivo."
                        ),
                        "code": "incomplete_marks",
                    }
                )
            if len(reason) < 10:
                raise ValidationError(
                    {"exception_reason": "Informe o motivo da exceção (mínimo de 10 caracteres)."}
                )
            snapshot["exceptions"] = {
                "kind": "incomplete_marks",
                "reason": reason[:500],
                "authorized_by": {"id": user.pk, "email": user.email},
                "authorized_at": timezone.now().isoformat(),
                "employees": incomplete,
            }
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


def _plain(days):
    """Dias sem o campo `timezone`, acrescentado depois dos primeiros fechamentos."""
    return [{k: v for k, v in d.items() if k != "timezone"} for d in days]


def closing_divergence(closing, employee) -> bool:
    """Verdadeiro se a apuração atual difere do instantâneo (p.ex. marcação offline chegou depois)."""
    for item in closing.snapshot.get("employees", []):
        if item["employee"]["id"] == employee.pk:
            current = json.loads(
                json.dumps(compute_employee(employee, closing.start, closing.end), cls=DjangoJSONEncoder)
            )
            return current["totals"] != item["totals"] or _plain(current["days"]) != _plain(item["days"])
    return True


# ---------- Pedidos: ajustes e abonos ----------


def _clean_reason(value, field="reason"):
    if not isinstance(value, str) or len(value.strip()) < 5:
        raise ValidationError({field: "Informe a justificativa (mínimo de 5 caracteres)."})
    return value.strip()[:500]


def local_to_aware(employee, local: dt.datetime) -> dt.datetime:
    """Interpreta data e hora **da unidade** do funcionário (lotação vigente naquela data), sem usar o fuso
    de quem digita. Horário inexistente ou repetido por mudança de horário de verão é recusado."""
    if local.tzinfo is not None:
        raise ValidationError({"occurred_local": "Informe data e hora sem fuso."})
    tz = _tz_resolver(employee)(local.date())
    aware = local.replace(tzinfo=tz)
    roundtrip = aware.astimezone(dt.UTC).astimezone(tz).replace(tzinfo=None)
    if roundtrip != local or aware.replace(fold=1).utcoffset() != aware.utcoffset():
        raise ValidationError({"occurred_local": "Horário inexistente ou repetido na mudança de horário."})
    return aware


def request_adjustment(
    *, company, employee, user, kind, reason, record=None, occurred_at=None, occurred_local=None
):
    reason = _clean_reason(reason)
    if kind == AdjustmentKind.INCLUDE and occurred_at is None and occurred_local is not None:
        occurred_at = local_to_aware(employee, occurred_local)
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
        reference = occurred_at.astimezone(
            _tz_resolver(employee)(occurred_at.astimezone(dt.UTC).date())
        ).date()
        record = None
    else:
        raise ValidationError({"kind": "Use 'include' ou 'disregard'."})
    with transaction.atomic():
        lock_company(company)
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
        lock_company(company)
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
    if membership.role == Role.MANAGER and not membership.can_decide_requests:
        raise PermissionDenied("Seu acesso permite consultar solicitações, mas não decidi-las.")
    with transaction.atomic():
        lock_company(company)
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


# ---------- Banco de horas (livro-razão separado da apuração) ----------

# Sinal exigido por tipo: abatimento e pagamento só reduzem o saldo; saldo inicial e ajuste aceitam os dois.
_BANK_SIGN = {HourBankKind.OFFSET: -1, HourBankKind.PAYOUT: -1}


def hour_bank(employee) -> dict:
    """Saldo do banco de horas: movimentações lançadas + saldo dos períodos **fechados** a partir do saldo
    inicial. O saldo do período mostrado na folha de ponto não é o banco: ele só entra aqui depois do
    fechamento, e só se houver saldo inicial lançado (sem ele, não há data de partida)."""
    entries = list(HourBankEntry.objects.filter(employee=employee).select_related("created_by", "reverses"))
    opening = min(
        (e.date for e in entries if e.kind == HourBankKind.OPENING and not hasattr(e, "reversed_by")),
        default=None,
    )
    accrued, periods = 0, []
    if opening is not None:
        for closing in PeriodClosing.objects.filter(
            company_id=employee.company_id, status=ClosingStatus.CLOSED, start__gte=opening
        ).order_by("start"):
            item = next(
                (i for i in closing.snapshot.get("employees", []) if i["employee"]["id"] == employee.pk), None
            )
            if item:
                minutes = item["totals"]["balance_minutes"]
                accrued += minutes
                periods.append({"start": closing.start, "end": closing.end, "balance_minutes": minutes})
    ledger = sum(e.minutes for e in entries)
    return {
        "employee": {"id": employee.pk, "registration": employee.registration, "name": employee.full_name},
        "ledger_minutes": ledger,
        "accrued_closed_minutes": accrued,
        "balance_minutes": ledger + accrued,
        "opening_date": opening,
        "closed_periods": periods,
        "notice": (
            "O saldo soma os lançamentos abaixo e o saldo dos períodos já fechados "
            "a partir do saldo inicial. "
            "Regras de compensação, prazo e pagamento dependem de acordo ou convenção coletiva "
            "e precisam ser "
            "conferidas com especialista; o sistema não vence nem zera saldos sozinho."
        ),
        "entries": [
            {
                "id": e.pk,
                "kind": e.kind,
                "kind_label": e.get_kind_display(),
                "date": e.date,
                "minutes": e.minutes,
                "reason": e.reason,
                "created_by": e.created_by.email,
                "created_at": e.created_at,
                "reverses": e.reverses_id,
                "reversed": hasattr(e, "reversed_by"),
            }
            for e in entries
        ],
    }


def add_hour_bank_entry(*, company, employee, user, kind, date, minutes, reason):
    if kind not in HourBankKind.values or kind == HourBankKind.REVERSAL:
        raise ValidationError({"kind": "Tipo de lançamento inválido."})
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes == 0 or abs(minutes) > 100_000:
        raise ValidationError({"minutes": "Informe os minutos (diferentes de zero), com sinal."})
    sign = _BANK_SIGN.get(kind)
    if sign and minutes * sign < 0:
        raise ValidationError({"minutes": "Abatimentos e pagamentos reduzem o saldo: use minutos negativos."})
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if len(reason) < 5:
        raise ValidationError({"reason": "Informe o motivo (mínimo de 5 caracteres)."})
    with transaction.atomic():
        lock_company(company)
        if (
            HourBankEntry.objects.filter(
                employee=employee, kind=HourBankKind.OPENING, reversed_by__isnull=True
            ).exists()
            and kind == HourBankKind.OPENING
        ):
            raise ValidationError({"kind": "Já existe um saldo inicial: estorne-o antes de lançar outro."})
        return HourBankEntry.objects.create(
            company=company,
            employee=employee,
            kind=kind,
            date=date,
            minutes=minutes,
            reason=reason[:300],
            created_by=user,
        )


def reverse_hour_bank_entry(*, company, entry, user, reason):
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if len(reason) < 5:
        raise ValidationError({"reason": "Informe o motivo do estorno (mínimo de 5 caracteres)."})
    with transaction.atomic():
        lock_company(company)
        original = HourBankEntry.objects.select_for_update(of=("self",)).get(pk=entry.pk)
        if original.kind == HourBankKind.REVERSAL:
            raise ValidationError({"detail": "Um estorno não pode ser estornado."})
        if HourBankEntry.objects.filter(reverses=original).exists():
            raise ValidationError({"detail": "Este lançamento já foi estornado."})
        return HourBankEntry.objects.create(
            company=company,
            employee=original.employee,
            kind=HourBankKind.REVERSAL,
            date=original.date,
            minutes=-original.minutes,
            reason=reason[:300],
            reverses=original,
            created_by=user,
        )
