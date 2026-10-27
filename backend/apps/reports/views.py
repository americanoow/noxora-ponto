"""Portal do funcionário (próprios registros e comprovantes), espelho em PDF/CSV e exportações auditadas."""

import datetime as dt

from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance import services as att
from apps.attendance.models import ClosingStatus, PeriodClosing
from apps.attendance.views import _int_param, _period, _visible_employee, closing_dict, own_employee
from apps.audit import services as audit
from apps.companies.models import Role
from apps.companies.permissions import resolve_company
from apps.operations import services as ops_services
from apps.operations.views import Pagination, reader_company
from apps.timeclock.models import TimeRecord
from apps.timeclock.receipt import build_receipt
from apps.timeclock.serializers import record_dict

from . import exports
from .models import TimesheetAcknowledgement

RECENT_RECEIPTS_HOURS = 48  # Portaria 671, art. 80: extração pelo trabalhador das últimas 48 h


def _file(content: bytes, filename: str, content_type: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


def _member(request, company_id):
    company = resolve_company(request, company_id)
    if request.membership is None:
        raise PermissionDenied("Você não tem permissão para esta operação.")
    return company


def _receipt_for(record, *, full_cpf: bool):
    receipt = build_receipt(record)
    if full_cpf and record.cpf:
        receipt["worker"]["cpf"] = f"{record.cpf[:3]}.{record.cpf[3:6]}.{record.cpf[6:9]}-{record.cpf[9:]}"
    return receipt


# ---------- Portal do funcionário ----------


class MyPunchesView(APIView):
    """Marcações do próprio funcionário (padrão: últimas 48 h)."""

    def get(self, request, company_id):
        company = _member(request, company_id)
        employee = own_employee(request, company)
        qs = TimeRecord.objects.filter(company=company, employee=employee).select_related("unit", "device")
        if request.query_params.get("from") or request.query_params.get("to"):
            start, end = _period(request)
            qs = qs.filter(occurred_local_date__gte=start, occurred_local_date__lte=end)
        else:
            qs = qs.filter(occurred_at__gte=timezone.now() - dt.timedelta(hours=RECENT_RECEIPTS_HOURS))
        paginator = Pagination()
        page = paginator.paginate_queryset(qs.order_by("-occurred_at", "-id"), request)
        return paginator.get_paginated_response([record_dict(r) for r in page])


class MyReceiptView(APIView):
    def get(self, request, company_id, record_id):
        company = _member(request, company_id)
        employee = own_employee(request, company)
        record = (
            TimeRecord.objects.select_related("company", "unit", "device")
            .filter(company=company, employee=employee, pk=record_id)
            .first()
        )
        if record is None:
            raise Http404
        receipt = _receipt_for(record, full_cpf=True)
        if request.query_params.get("format") == "pdf":
            return _file(exports.receipt_pdf(receipt), f"comprovante-nsr-{record.nsr}.pdf", "application/pdf")
        return Response(receipt)


class MyClosingsView(APIView):
    """Períodos fechados do funcionário e a situação da ciência."""

    def get(self, request, company_id):
        company = _member(request, company_id)
        employee = own_employee(request, company)
        acks = {
            a.closing_id: a.acknowledged_at
            for a in TimesheetAcknowledgement.objects.filter(employee=employee)
        }
        out = []
        for c in PeriodClosing.objects.filter(company=company).order_by("-start")[:36]:
            if not any(e["employee"]["id"] == employee.pk for e in c.snapshot.get("employees", [])):
                continue
            out.append(
                {
                    "id": c.pk,
                    "start": c.start,
                    "end": c.end,
                    "status": c.status,
                    "acknowledged_at": acks.get(c.pk),
                }
            )
        return Response(out)


def _employee_snapshot(closing, employee):
    for item in closing.snapshot.get("employees", []):
        if item["employee"]["id"] == employee.pk:
            return item
    return None


class MyClosingAckView(APIView):
    """Registra a ciência do funcionário sobre o espelho fechado (uma vez por fechamento)."""

    def post(self, request, company_id, closing_id):
        company = _member(request, company_id)
        employee = own_employee(request, company)
        closing = PeriodClosing.objects.filter(
            company=company, pk=closing_id, status=ClosingStatus.CLOSED
        ).first()
        item = _employee_snapshot(closing, employee) if closing else None
        if item is None:
            raise Http404
        comment = request.data.get("comment", "")
        if not isinstance(comment, str) or len(comment) > 500:
            raise ValidationError({"comment": "Comentário de até 500 caracteres."})
        try:
            with transaction.atomic():
                ack = TimesheetAcknowledgement.objects.create(
                    closing=closing,
                    employee=employee,
                    user=request.user,
                    employee_snapshot_sha256=att.snapshot_hash(item),
                    comment=comment.strip(),
                )
                audit.record(request, "timesheet.acknowledged", company=company, target=closing)
        except IntegrityError:
            raise ValidationError({"detail": "Ciência já registrada para este período."}) from None
        return Response({"closing_id": closing.pk, "acknowledged_at": ack.acknowledged_at}, status=201)


class MyTimesheetPdfView(APIView):
    def get(self, request, company_id):
        company = _member(request, company_id)
        employee = own_employee(request, company)
        start, end = _period(request)
        return _timesheet_file(request, company, employee, start, end, "pdf")


# ---------- Gestor/administrador ----------


def _closing_covering(company, start, end):
    return PeriodClosing.objects.filter(
        company=company, status=ClosingStatus.CLOSED, start=start, end=end
    ).first()


def _timesheet_file(request, company, employee, start, end, fmt):
    closing = _closing_covering(company, start, end)
    sheet = _employee_snapshot(closing, employee) if closing else None
    if sheet is None:
        sheet = att.compute_employee(employee, start, end)
        closing = None
    audit.record(
        request,
        "report.timesheet_exported",
        company=company,
        target=employee,
        format=fmt,
        start=str(start),
        end=str(end),
    )
    name = f"espelho-{employee.registration}-{start}-{end}"
    if fmt == "pdf":
        content = exports.timesheet_pdf(
            sheet,
            company_name=company.legal_name or company.name,
            closing=closing_dict(closing) if closing else None,
        )
        return _file(content, f"{name}.pdf", "application/pdf")
    header = [
        "data",
        "marcacoes",
        "previsto_min",
        "trabalhado_min",
        "extra_min",
        "extra_percentual",
        "debito_min",
        "abonado_min",
        "noturno_min",
        "noturno_reduzido_min",
        "intervalo_suprimido_min",
        "situacao",
        "ocorrencias",
    ]
    rows = [
        [
            d["date"],
            " ".join(m["local"][11:16] + ("*" if m["origin"] == "included" else "") for m in d["marks"]),
            d["expected_minutes"],
            d["worked_minutes"],
            d["overtime_minutes"],
            d["overtime_rate_percent"] or "",
            d["deficit_minutes"],
            d["justified_minutes"],
            d["night_minutes"],
            d["night_reduced_minutes"],
            d["break_suppressed_minutes"],
            d["status"],
            " | ".join(d["issues"]),
        ]
        for d in sheet["days"]
    ]
    return _file(exports.csv_bytes(header, rows), f"{name}.csv", "text/csv; charset=utf-8")


class TimesheetExportView(APIView):
    """GET ?employee=&from=&to=&format=pdf|csv. Usa o instantâneo se o período exato estiver fechado."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        start, end = _period(request)
        employee = _visible_employee(
            request, company, _int_param(request.query_params.get("employee"), "employee")
        )
        fmt = request.query_params.get("format", "pdf")
        if fmt not in ("pdf", "csv"):
            raise ValidationError({"format": "Use pdf ou csv."})
        return _timesheet_file(request, company, employee, start, end, fmt)


class SummaryExportView(APIView):
    """Totais do período por funcionário visível (CSV), base para conferência e folha."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        start, end = _period(request)
        employees = ops_services.visible_employees(request, company).filter(is_active=True)
        if unit := request.query_params.get("unit"):
            employees = employees.filter(assignments__unit_id=_int_param(unit, "unit")).distinct()
        header = [
            "matricula",
            "nome",
            "previsto_min",
            "trabalhado_min",
            "extras_50_min",
            "extras_100_min",
            "outras_extras_min",
            "debito_min",
            "abonado_min",
            "noturno_min",
            "noturno_reduzido_min",
            "intervalo_suprimido_min",
            "faltas",
            "dias_inconsistentes",
            "saldo_min",
        ]
        rows = []
        for e in employees.order_by("full_name", "id")[:2000]:
            t = att.compute_employee(e, start, end)["totals"]
            by_rate = dict(t["overtime_by_rate"])
            rows.append(
                [
                    e.registration,
                    e.full_name,
                    t["expected_minutes"],
                    t["worked_minutes"],
                    by_rate.pop("50", 0),
                    by_rate.pop("100", 0),
                    sum(by_rate.values()),
                    t["deficit_minutes"],
                    t["justified_minutes"],
                    t["night_minutes"],
                    t["night_reduced_minutes"],
                    t["break_suppressed_minutes"],
                    t["absences"],
                    t["inconsistent_days"],
                    t["balance_minutes"],
                ]
            )
        audit.record(
            request,
            "report.summary_exported",
            company=company,
            start=str(start),
            end=str(end),
            rows=len(rows),
        )
        return _file(exports.csv_bytes(header, rows), f"resumo-{start}-{end}.csv", "text/csv; charset=utf-8")


class TimeRecordsExportView(APIView):
    """Marcações originais (CSV) no período. CPF mascarado para gestor; completo só para administrador."""

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        start, end = _period(request)
        employees = ops_services.visible_employees(request, company)
        qs = TimeRecord.objects.filter(
            company=company,
            employee__in=employees,
            occurred_local_date__gte=start,
            occurred_local_date__lte=end,
        ).select_related("unit", "device")
        if unit := request.query_params.get("unit"):
            qs = qs.filter(unit_id=_int_param(unit, "unit"))
        if employee := request.query_params.get("employee"):
            qs = qs.filter(employee_id=_int_param(employee, "employee"))
        full_cpf = request.membership.role == Role.COMPANY_ADMIN
        header = [
            "nsr",
            "unidade",
            "matricula",
            "nome",
            "cpf",
            "data_hora_marcacao",
            "data_hora_gravacao",
            "offline",
            "identificacao",
            "tipo_informado",
            "sinalizacoes",
            "hash_sha256",
        ]
        rows = []
        for r in qs.order_by("unit_id", "nsr")[:50000]:
            offset = dt.timezone(dt.timedelta(minutes=r.occurred_offset_minutes))
            rows.append(
                [
                    r.nsr,
                    r.unit.name,
                    r.registration,
                    r.employee_name,
                    r.cpf if full_cpf else ops_services.mask_cpf(r.cpf),
                    r.occurred_at.astimezone(offset).isoformat(timespec="seconds"),
                    r.recorded_at.astimezone(
                        dt.timezone(dt.timedelta(minutes=r.recorded_offset_minutes))
                    ).isoformat(timespec="seconds"),
                    "sim" if r.offline else "nao",
                    r.identification_method,
                    r.declared_kind,
                    ",".join(r.sync_flags or []),
                    r.record_hash,
                ]
            )
        audit.record(
            request,
            "report.time_records_exported",
            company=company,
            start=str(start),
            end=str(end),
            rows=len(rows),
        )
        return _file(
            exports.csv_bytes(header, rows), f"marcacoes-{start}-{end}.csv", "text/csv; charset=utf-8"
        )


class ReceiptPdfView(APIView):
    def get(self, request, company_id, record_id):
        company = reader_company(request, company_id)
        record = (
            TimeRecord.objects.select_related("company", "unit", "device")
            .filter(
                company=company, employee__in=ops_services.visible_employees(request, company), pk=record_id
            )
            .first()
        )
        if record is None:
            raise Http404
        receipt = _receipt_for(record, full_cpf=request.membership.role == Role.COMPANY_ADMIN)
        audit.record(request, "report.receipt_exported", company=company, target=record)
        return _file(exports.receipt_pdf(receipt), f"comprovante-nsr-{record.nsr}.pdf", "application/pdf")


class AcknowledgementListView(APIView):
    """Quem já deu ciência no espelho de um fechamento."""

    def get(self, request, company_id, closing_id):
        company = reader_company(request, company_id)
        closing = PeriodClosing.objects.filter(company=company, pk=closing_id).first()
        if closing is None:
            raise Http404
        visible = set(ops_services.visible_employees(request, company).values_list("pk", flat=True))
        acks = {a.employee_id: a for a in TimesheetAcknowledgement.objects.filter(closing=closing)}
        rows = []
        for item in closing.snapshot.get("employees", []):
            eid = item["employee"]["id"]
            if eid not in visible:
                continue
            ack = acks.get(eid)
            rows.append(
                {
                    "employee": item["employee"],
                    "acknowledged_at": ack.acknowledged_at if ack else None,
                    "comment": ack.comment if ack else "",
                    "matches_snapshot": (ack.employee_snapshot_sha256 == att.snapshot_hash(item))
                    if ack
                    else None,
                }
            )
        return Response(rows)
