from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.companies.models import Role
from apps.companies.permissions import require_role, resolve_company
from apps.operations import services as ops_services
from apps.operations.models import Employee, Unit
from apps.operations.views import Pagination, admin_company, reader_company
from apps.timeclock.models import TimeRecord

from . import calculation as calc
from . import services
from .models import (
    AdjustmentKind,
    CalculationRuleSet,
    ClosingStatus,
    DayJustification,
    Holiday,
    HourBankEntry,
    JustificationKind,
    PeriodClosing,
    PunchAdjustment,
    RequestStatus,
)


def _date(value, field):
    try:
        parsed = parse_date(value or "")
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValidationError({field: "Use o formato AAAA-MM-DD."})
    return parsed


def _period(request):
    p = request.query_params
    return services.parse_period(_date(p.get("from"), "from"), _date(p.get("to"), "to"))


def _positive(value, field, default, maximum):
    if value in (None, ""):
        return default
    number = _int_param(value, field)
    if not 1 <= number <= maximum:
        raise ValidationError({field: f"Informe um número entre 1 e {maximum}."})
    return number


def _int_param(value, field):
    if not (isinstance(value, str) and value.isascii() and value.isdigit() and len(value) < 19):
        raise ValidationError({field: "Identificador inválido."})
    return int(value)


def _visible_employee(request, company, employee_id):
    employee = ops_services.visible_employees(request, company).filter(pk=employee_id).first()
    if employee is None:
        raise Http404
    return employee


def own_employee(request, company):
    """Funcionário vinculado ao usuário logado nesta empresa (portal do funcionário)."""
    employee = Employee.objects.filter(company=company, access_user=request.user).first()
    if employee is None:
        raise PermissionDenied("Seu acesso não está vinculado a um cadastro de funcionário.")
    return employee


def _user(user):
    return {"id": user.pk, "email": user.email} if user else None


def adjustment_dict(a: PunchAdjustment) -> dict:
    return {
        "id": a.pk,
        "type": "adjustment",
        "employee": {
            "id": a.employee_id,
            "name": a.employee.full_name,
            "registration": a.employee.registration,
        },
        "kind": a.kind,
        "kind_label": a.get_kind_display(),
        "record_id": a.record_id,
        "record_occurred_at": a.record.occurred_at if a.record_id else None,
        "occurred_at": a.occurred_at,
        "reference_date": a.reference_date,
        "reason": a.reason,
        "status": a.status,
        "requested_by": _user(a.requested_by),
        "requested_at": a.requested_at,
        "decided_by": _user(a.decided_by),
        "decided_at": a.decided_at,
        "decision_note": a.decision_note,
    }


def justification_dict(j: DayJustification) -> dict:
    return {
        "id": j.pk,
        "type": "justification",
        "employee": {
            "id": j.employee_id,
            "name": j.employee.full_name,
            "registration": j.employee.registration,
        },
        "date": j.date,
        "kind": j.kind,
        "kind_label": j.get_kind_display(),
        "minutes": j.minutes,
        "reason": j.reason,
        "document_ref": j.document_ref,
        "status": j.status,
        "requested_by": _user(j.requested_by),
        "requested_at": j.requested_at,
        "decided_by": _user(j.decided_by),
        "decided_at": j.decided_at,
        "decision_note": j.decision_note,
    }


def closing_dict(c: PeriodClosing, *, include_snapshot=False) -> dict:
    body = {
        "id": c.pk,
        "start": c.start,
        "end": c.end,
        "status": c.status,
        "snapshot_sha256": c.snapshot_sha256,
        "engine_version": c.engine_version,
        "employees": len(c.snapshot.get("employees", [])),
        "closed_by": _user(c.closed_by),
        "closed_at": c.closed_at,
        "reopened_by": _user(c.reopened_by),
        "reopened_at": c.reopened_at,
        "reopen_reason": c.reopen_reason,
        "exceptions": c.snapshot.get("exceptions"),
    }
    if include_snapshot:
        body["snapshot"] = c.snapshot
    return body


def ruleset_dict(r: CalculationRuleSet) -> dict:
    return {
        "id": r.pk,
        "version": r.version,
        "valid_from": r.valid_from,
        "params": r.params,
        "note": r.note,
        "created_by": _user(r.created_by),
        "created_at": r.created_at,
    }


# ---------- Regras ----------


class RuleSetListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        return Response(
            {
                "defaults": calc.DEFAULT_PARAMS,
                "references": calc.DEFAULT_PARAMS_REFS,
                "engine_version": calc.RULES_ENGINE_VERSION,
                "notice": (
                    "Parâmetros padrão são hipóteses baseadas na CLT e precisam ser conferidos com "
                    "especialista e com a convenção coletiva aplicável."
                ),
                "versions": [
                    ruleset_dict(r)
                    for r in CalculationRuleSet.objects.filter(company=company).select_related("created_by")
                ],
            }
        )

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        params = request.data.get("params", {})
        if not isinstance(params, dict):
            raise ValidationError({"params": "Envie um objeto."})
        valid_from = _date(request.data.get("valid_from"), "valid_from")
        note = request.data.get("note", "")
        if not isinstance(note, str):
            raise ValidationError({"note": "Texto inválido."})
        with transaction.atomic():
            rs = services.create_rule_set(
                company=company, user=request.user, params=params, valid_from=valid_from, note=note
            )
            audit.record(request, "attendance.rules_created", company=company, target=rs, version=rs.version)
        return Response(ruleset_dict(rs), status=201)


# ---------- Feriados ----------


def holiday_dict(h):
    return {"id": h.pk, "date": h.date, "name": h.name, "unit_id": h.unit_id}


class HolidayListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        qs = Holiday.objects.filter(company=company)
        if year := request.query_params.get("year"):
            qs = qs.filter(date__year=_int_param(year, "year"))
        return Response([holiday_dict(h) for h in qs])

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        date = _date(request.data.get("date"), "date")
        name = request.data.get("name", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValidationError({"name": "Informe o nome do feriado (até 120 caracteres)."})
        unit = None
        if (unit_id := request.data.get("unit_id")) is not None:
            unit = (
                Unit.objects.filter(company=company, pk=unit_id).first() if isinstance(unit_id, int) else None
            )
            if unit is None:
                raise ValidationError({"unit_id": "Unidade inválida."})
        try:
            with transaction.atomic():
                services.ensure_open(company, date)
                holiday = Holiday.objects.create(company=company, unit=unit, date=date, name=name.strip())
                audit.record(
                    request, "attendance.holiday_created", company=company, target=holiday, date=str(date)
                )
        except IntegrityError:
            raise ValidationError({"date": "Já existe feriado nesta data."}) from None
        return Response(holiday_dict(holiday), status=201)


class HolidayDetailView(APIView):
    def delete(self, request, company_id, holiday_id):
        company = admin_company(request, company_id)
        holiday = Holiday.objects.filter(company=company, pk=holiday_id).first()
        if holiday is None:
            raise Http404
        with transaction.atomic():
            services.ensure_open(company, holiday.date)
            audit.record(
                request, "attendance.holiday_deleted", company=company, target=holiday, date=str(holiday.date)
            )
            holiday.delete()
        return Response(status=204)


# ---------- Espelho / apuração ----------


def _timesheet(company, employee, start, end):
    body = services.compute_employee(employee, start, end)
    closings = PeriodClosing.objects.filter(
        company=company, status=ClosingStatus.CLOSED, start__lte=end, end__gte=start
    )
    body["closings"] = [
        {
            **closing_dict(c),
            "divergent": services.closing_divergence(c, employee),
        }
        for c in closings
    ]
    return body


class TimesheetView(APIView):
    """Apuração de um funcionário (com explicação por dia). Somente leitura."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        start, end = _period(request)
        employee = _visible_employee(
            request, company, _int_param(request.query_params.get("employee"), "employee")
        )
        return Response(_timesheet(company, employee, start, end))


class SummaryView(APIView):
    """Totais por funcionário no período (para o gestor), filtráveis por unidade e setor."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        start, end = _period(request)
        employees = services.employees_in_period(ops_services.visible_employees(request, company), start, end)
        p = request.query_params
        if unit := p.get("unit"):
            employees = employees.filter(assignments__unit_id=_int_param(unit, "unit"))
        if sector := p.get("sector"):
            employees = employees.filter(assignments__sector_id=_int_param(sector, "sector"))
        employees = employees.distinct().order_by("full_name", "id")
        paginator = Pagination()
        page = paginator.paginate_queryset(employees, request)
        rows = []
        for e in page:
            data = services.compute_employee(e, start, end)
            rows.append(
                {
                    "employee": data["employee"],
                    "totals": data["totals"],
                    "pending_requests": data["pending_requests"],
                }
            )
        return paginator.get_paginated_response(rows)


# ---------- Pedidos ----------


def _create_adjustment(request, company, employee):
    kind = request.data.get("kind")
    record = None
    occurred_at = None
    occurred_local = None
    if kind == AdjustmentKind.DISREGARD:
        rid = request.data.get("record_id")
        record = (
            TimeRecord.objects.filter(pk=rid, company=company, employee=employee).first()
            if isinstance(rid, int)
            else None
        )
        if record is None:
            raise ValidationError({"record_id": "Marcação inválida."})
    elif kind == AdjustmentKind.INCLUDE:
        raw_local = request.data.get("occurred_local")
        if raw_local is not None:
            # Data e hora da unidade do funcionário (sem fuso): o servidor aplica a lotação vigente na data.
            occurred_local = parse_datetime(raw_local) if isinstance(raw_local, str) else None
            if occurred_local is None or occurred_local.tzinfo is not None:
                raise ValidationError(
                    {"occurred_local": "Informe data e hora da unidade (AAAA-MM-DDTHH:MM)."}
                )
        else:
            raw = request.data.get("occurred_at")
            occurred_at = parse_datetime(raw) if isinstance(raw, str) else None
            if occurred_at is None or occurred_at.tzinfo is None:
                raise ValidationError({"occurred_at": "Informe data e hora com fuso (ISO 8601)."})
    with transaction.atomic():
        item = services.request_adjustment(
            company=company,
            employee=employee,
            user=request.user,
            kind=kind,
            reason=request.data.get("reason"),
            record=record,
            occurred_at=occurred_at,
            occurred_local=occurred_local,
        )
        audit.record(request, "attendance.adjustment_requested", company=company, target=item, kind=item.kind)
    return item


def _create_justification(request, company, employee):
    kind = request.data.get("kind")
    if kind not in JustificationKind.values:
        raise ValidationError({"kind": "Tipo de abono inválido."})
    document_ref = request.data.get("document_ref", "")
    if not isinstance(document_ref, str):
        raise ValidationError({"document_ref": "Texto inválido."})
    with transaction.atomic():
        item = services.request_justification(
            company=company,
            employee=employee,
            user=request.user,
            date=_date(request.data.get("date"), "date"),
            kind=kind,
            reason=request.data.get("reason"),
            minutes=request.data.get("minutes"),
            document_ref=document_ref,
        )
        audit.record(
            request, "attendance.justification_requested", company=company, target=item, kind=item.kind
        )
    return item


def _requests_payload(request, adjustments, justifications):
    status = request.query_params.get("status", "")
    if status:
        if status not in RequestStatus.values:
            raise ValidationError({"status": "Situação inválida."})
        adjustments, justifications = adjustments.filter(status=status), justifications.filter(status=status)
    p = request.query_params
    if p.get("from") or p.get("to"):
        start, end = _date(p.get("from"), "from"), _date(p.get("to"), "to")
        adjustments = adjustments.filter(reference_date__gte=start, reference_date__lte=end)
        justifications = justifications.filter(date__gte=start, date__lte=end)
    page = _positive(p.get("page"), "page", 1, 10_000)
    size = _positive(p.get("page_size"), "page_size", 50, 200)
    total = adjustments.count() + justifications.count()
    need = page * size  # cada lado precisa trazer no máximo o que cabe até o fim da página pedida
    adjustments = adjustments.select_related("employee", "record", "requested_by", "decided_by").order_by(
        "-requested_at", "-id"
    )[:need]
    justifications = justifications.select_related("employee", "requested_by", "decided_by").order_by(
        "-requested_at", "-id"
    )[:need]
    items = [adjustment_dict(a) for a in adjustments] + [justification_dict(j) for j in justifications]
    items.sort(key=lambda x: x["requested_at"], reverse=True)
    return {
        "count": total,
        "next": f"?page={page + 1}" if page * size < total else None,
        "previous": f"?page={page - 1}" if page > 1 else None,
        "results": items[(page - 1) * size : page * size],
    }


class RequestListView(APIView):
    """Pedidos (ajustes e abonos) dos funcionários visíveis. POST cria em nome do funcionário."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        employees = ops_services.visible_employees(request, company)
        adjustments = PunchAdjustment.objects.filter(company=company, employee__in=employees)
        justifications = DayJustification.objects.filter(company=company, employee__in=employees)
        if employee := request.query_params.get("employee"):
            eid = _int_param(employee, "employee")
            adjustments, justifications = (
                adjustments.filter(employee_id=eid),
                justifications.filter(employee_id=eid),
            )
        return Response(_requests_payload(request, adjustments, justifications))

    def post(self, request, company_id):
        company = reader_company(request, company_id)
        if request.membership.role == Role.MANAGER and not request.membership.can_request_adjustments:
            raise PermissionDenied("Seu acesso permite consultar solicitações, mas não fazê-las.")
        employee_id = request.data.get("employee_id")
        if not isinstance(employee_id, int):
            raise ValidationError({"employee_id": "Informe o funcionário."})
        employee = _visible_employee(request, company, employee_id)
        if request.data.get("type") == "justification":
            return Response(justification_dict(_create_justification(request, company, employee)), status=201)
        return Response(adjustment_dict(_create_adjustment(request, company, employee)), status=201)


class DecisionView(APIView):
    """POST {approve: bool, note}: decide um pedido pendente (administrador ou gestor do escopo)."""

    MODELS = {
        "adjustments": (PunchAdjustment, adjustment_dict),
        "justifications": (DayJustification, justification_dict),
    }

    def post(self, request, company_id, kind, item_id):
        company = resolve_company(request, company_id)
        require_role(request, Role.COMPANY_ADMIN, Role.MANAGER)
        if kind not in self.MODELS:
            raise Http404
        model, to_dict = self.MODELS[kind]
        approve = request.data.get("approve")
        if not isinstance(approve, bool):
            raise ValidationError({"approve": "Informe verdadeiro (aprovar) ou falso (recusar)."})
        note = request.data.get("note", "")
        if not isinstance(note, str):
            raise ValidationError({"note": "Texto inválido."})
        with transaction.atomic():
            item = services.decide(
                model=model,
                pk=item_id,
                company=company,
                membership=request.membership,
                user=request.user,
                approve=approve,
                note=note,
                visible_employees=ops_services.visible_employees(request, company),
            )
            audit.record(
                request,
                f"attendance.{kind[:-1]}_{'approved' if approve else 'rejected'}",
                company=company,
                target=item,
            )
        return Response(to_dict(item))


# ---------- Fechamento ----------


class ClosingListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        queryset = PeriodClosing.objects.filter(company=company).select_related("closed_by", "reopened_by")
        paginator = Pagination()
        page = paginator.paginate_queryset(queryset.order_by("-start", "-id"), request)
        return paginator.get_paginated_response([closing_dict(c) for c in page])

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        start = _date(request.data.get("start"), "start")
        end = _date(request.data.get("end"), "end")
        accept = request.data.get("accept_incomplete", False)
        reason = request.data.get("exception_reason", "")
        if not isinstance(accept, bool) or not isinstance(reason, str):
            raise ValidationError({"accept_incomplete": "Informe verdadeiro ou falso e o motivo em texto."})
        employees = services.employees_in_period(
            Employee.objects.filter(company=company), start, end
        ).order_by("full_name", "id")
        with transaction.atomic():
            closing = services.close_period(
                company=company,
                user=request.user,
                start=start,
                end=end,
                employees=employees,
                accept_incomplete=accept,
                exception_reason=reason,
            )
            exception = closing.snapshot.get("exceptions")
            audit.record(
                request,
                "attendance.period_closed_with_exception" if exception else "attendance.period_closed",
                company=company,
                target=closing,
                start=str(start),
                end=str(end),
                sha256=closing.snapshot_sha256,
                **({"exception_reason": exception["reason"]} if exception else {}),
            )
        return Response(closing_dict(closing), status=201)


class ClosingDetailView(APIView):
    def get(self, request, company_id, closing_id):
        company = reader_company(request, company_id)
        closing = PeriodClosing.objects.filter(company=company, pk=closing_id).first()
        if closing is None:
            raise Http404
        body = closing_dict(closing, include_snapshot=True)
        if request.membership.role != Role.COMPANY_ADMIN:
            visible = set(ops_services.visible_employees(request, company).values_list("pk", flat=True))
            body["snapshot"] = {
                "employees": [
                    e for e in closing.snapshot.get("employees", []) if e["employee"]["id"] in visible
                ]
            }
        return Response(body)


class ClosingReopenView(APIView):
    def post(self, request, company_id, closing_id):
        company = admin_company(request, company_id)
        closing = PeriodClosing.objects.filter(company=company, pk=closing_id).first()
        if closing is None:
            raise Http404
        with transaction.atomic():
            closing = services.reopen_period(
                closing=closing, user=request.user, reason=request.data.get("reason")
            )
            audit.record(
                request,
                "attendance.period_reopened",
                company=company,
                target=closing,
                reason=closing.reopen_reason,
            )
        return Response(closing_dict(closing))


# ---------- Portal do funcionário (próprios dados) ----------


class MyTimesheetView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        employee = own_employee(request, company)
        start, end = _period(request)
        return Response(_timesheet(company, employee, start, end))


class MyRequestsView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        employee = own_employee(request, company)
        return Response(
            _requests_payload(
                request,
                PunchAdjustment.objects.filter(company=company, employee=employee),
                DayJustification.objects.filter(company=company, employee=employee),
            )
        )

    def post(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        employee = own_employee(request, company)
        if request.data.get("type") == "justification":
            return Response(justification_dict(_create_justification(request, company, employee)), status=201)
        return Response(adjustment_dict(_create_adjustment(request, company, employee)), status=201)


class MyRequestCancelView(APIView):
    def post(self, request, company_id, kind, item_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        model = {"adjustments": PunchAdjustment, "justifications": DayJustification}.get(kind)
        if model is None:
            raise Http404
        item = (
            model.objects.filter(company=company, pk=item_id, requested_by=request.user)
            .select_related("employee")
            .first()
        )
        if item is None:
            raise Http404
        with transaction.atomic():
            item = services.cancel(item=item, user=request.user)
            audit.record(request, f"attendance.{kind[:-1]}_cancelled", company=company, target=item)
        return Response({"id": item.pk, "status": item.status})


# ---------- Banco de horas ----------


class HourBankView(APIView):
    """GET: saldo e lançamentos (funcionário no escopo). POST (administrador): novo lançamento."""

    def get(self, request, company_id, employee_id):
        company = reader_company(request, company_id)
        employee = _visible_employee(request, company, employee_id)
        return Response(services.hour_bank(employee))

    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = Employee.objects.filter(company=company, pk=employee_id).first()
        if employee is None:
            raise Http404
        entry = services.add_hour_bank_entry(
            company=company,
            employee=employee,
            user=request.user,
            kind=request.data.get("kind"),
            date=_date(request.data.get("date"), "date"),
            minutes=request.data.get("minutes"),
            reason=request.data.get("reason"),
        )
        audit.record(
            request,
            "attendance.hour_bank_entry",
            company=company,
            target=entry,
            kind=entry.kind,
            minutes=entry.minutes,
            employee=employee.pk,
        )
        return Response(services.hour_bank(employee), status=201)


class HourBankReverseView(APIView):
    def post(self, request, company_id, employee_id, entry_id):
        company = admin_company(request, company_id)
        entry = HourBankEntry.objects.filter(company=company, employee_id=employee_id, pk=entry_id).first()
        if entry is None:
            raise Http404
        reversal = services.reverse_hour_bank_entry(
            company=company, entry=entry, user=request.user, reason=request.data.get("reason")
        )
        audit.record(
            request,
            "attendance.hour_bank_reversal",
            company=company,
            target=reversal,
            reverses=entry.pk,
            minutes=reversal.minutes,
        )
        return Response(services.hour_bank(entry.employee), status=201)


class MyHourBankView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        return Response(services.hour_bank(own_employee(request, company)))
