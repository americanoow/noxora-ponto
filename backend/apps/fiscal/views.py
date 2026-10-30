import hashlib

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance import services as att
from apps.attendance.models import ClosingStatus, PeriodClosing
from apps.attendance.views import _date
from apps.audit import services as audit
from apps.operations.models import Unit
from apps.operations.views import Pagination, admin_company
from apps.reports.views import _file
from apps.timeclock.models import TimeRecord

from . import afd, payroll
from .models import PAYROLL_EVENTS, GeneratedFile, PayrollExportProfile


def _log(request, company, kind, content, start, end, version, unit=None, **meta):
    item = GeneratedFile.objects.create(
        company=company,
        kind=kind,
        unit=unit,
        start=start,
        end=end,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        generator_version=version,
        generated_by=request.user,
        metadata=meta,
    )
    audit.record(request, f"fiscal.{kind}_generated", company=company, target=item, sha256=item.sha256)
    return item


class AfdView(APIView):
    """GET ?unit=&from=&to=: AFD de um estabelecimento (somente administrador). Sem assinatura CAdES."""

    def get(self, request, company_id):
        company = admin_company(request, company_id)
        p = request.query_params
        start, end = att.parse_period(_date(p.get("from"), "from"), _date(p.get("to"), "to"))
        unit_id = p.get("unit", "")
        unit = Unit.objects.filter(company=company, pk=int(unit_id)).first() if unit_id.isdigit() else None
        if unit is None:
            raise ValidationError({"unit": "Informe a unidade (estabelecimento)."})
        records = TimeRecord.objects.filter(
            unit=unit, occurred_local_date__gte=start, occurred_local_date__lte=end
        ).order_by("nsr")
        content, meta = afd.build_afd(
            company=company, unit=unit, records=records.iterator(), start=start, end=end
        )
        item = _log(
            request, company, "afd", content, start, end, afd.AFD_GENERATOR_VERSION, unit=unit, **meta
        )
        response = _file(
            content, f"AFD_{unit.pk}_{start:%Y%m%d}_{end:%Y%m%d}.txt", "text/plain; charset=iso-8859-1"
        )
        response["X-Noxora-Sha256"] = item.sha256
        response["X-Noxora-Pending"] = str(len(meta["pending"]))
        return response


def profile_dict(p):
    return {
        "id": p.pk,
        "name": p.name,
        "file_format": p.file_format,
        "event_codes": p.event_codes,
        "is_active": p.is_active,
    }


def _validate_codes(codes):
    if not isinstance(codes, dict) or set(codes) - set(PAYROLL_EVENTS):
        raise ValidationError({"event_codes": f"Eventos válidos: {', '.join(PAYROLL_EVENTS)}."})
    for value in codes.values():
        if not isinstance(value, str) or not value.strip() or len(value) > 6 or not value.isalnum():
            raise ValidationError({"event_codes": "Códigos alfanuméricos de até 6 caracteres."})
    return {k: v.strip() for k, v in codes.items()}


class PayrollProfileListView(APIView):
    def get(self, request, company_id):
        company = admin_company(request, company_id)
        return Response(
            {
                "events": PAYROLL_EVENTS,
                "profiles": [profile_dict(p) for p in PayrollExportProfile.objects.filter(company=company)],
            }
        )

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        name = request.data.get("name", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValidationError({"name": "Informe o nome (até 80 caracteres)."})
        fmt = request.data.get("file_format", "csv")
        if fmt not in ("csv", "fixed"):
            raise ValidationError({"file_format": "Use csv ou fixed."})
        with transaction.atomic():
            profile = PayrollExportProfile.objects.create(
                company=company,
                name=name.strip(),
                file_format=fmt,
                event_codes=_validate_codes(request.data.get("event_codes", {})),
                created_by=request.user,
            )
            audit.record(request, "fiscal.payroll_profile_created", company=company, target=profile)
        return Response(profile_dict(profile), status=201)


class PayrollExportView(APIView):
    """GET ?profile=&closing=: exporta os totais de um período FECHADO (instantâneo) para a folha."""

    def get(self, request, company_id):
        company = admin_company(request, company_id)
        p = request.query_params
        profile = PayrollExportProfile.objects.filter(
            company=company, pk=int(p.get("profile", "0") or 0) if p.get("profile", "").isdigit() else 0
        ).first()
        closing = (
            PeriodClosing.objects.filter(
                company=company, pk=int(p["closing"]), status=ClosingStatus.CLOSED
            ).first()
            if p.get("closing", "").isdigit()
            else None
        )
        if profile is None or closing is None:
            raise Http404
        rows = [
            (e["employee"]["registration"], e["employee"]["name"], e["totals"])
            for e in closing.snapshot.get("employees", [])
        ]
        try:
            content = payroll.build(profile, rows, start=closing.start, end=closing.end)
        except payroll.PayrollFormatError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        ext = "txt" if profile.file_format == "fixed" else "csv"
        _log(
            request,
            company,
            "payroll",
            content,
            closing.start,
            closing.end,
            payroll.PAYROLL_GENERATOR_VERSION,
            closing=closing.pk,
            closing_sha256=closing.snapshot_sha256,
            profile=profile.pk,
        )
        return _file(content, f"folha-{closing.start}-{closing.end}.{ext}", "text/plain; charset=utf-8")


class GeneratedFileListView(APIView):
    def get(self, request, company_id):
        company = admin_company(request, company_id)
        paginator = Pagination()
        page = paginator.paginate_queryset(
            GeneratedFile.objects.filter(company=company)
            .select_related("generated_by")
            .order_by("-generated_at", "-id"),
            request,
        )
        return paginator.get_paginated_response(
            [
                {
                    "id": f.pk,
                    "kind": f.kind,
                    "unit_id": f.unit_id,
                    "start": f.start,
                    "end": f.end,
                    "sha256": f.sha256,
                    "size": f.size,
                    "generator_version": f.generator_version,
                    "generated_at": f.generated_at,
                    "generated_by": f.generated_by.email,
                    "metadata": f.metadata,
                }
                for f in page
            ]
        )
