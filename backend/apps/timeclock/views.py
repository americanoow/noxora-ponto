from django.db import transaction
from django.http import Http404
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.companies.models import Company
from apps.devices.views import DeviceView
from apps.operations import services as ops_services
from apps.operations.views import Pagination, admin_company, is_admin, reader_company

from . import services
from .models import TimeRecord
from .receipt import build_receipt
from .serializers import EmployerSerializer, PunchSerializer, employer_dict, record_dict

# ---------- API do tablet ----------


class PunchView(DeviceView):
    """POST: registra a marcação. 201 = nova; 200 = reenvio do mesmo evento (devolve o original)."""

    def post(self, request):
        data = PunchSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        record, created = services.record_punch(
            device=request.device,
            registration=v["registration"],
            client_event_id=v["client_event_id"],
            declared_kind=v["declared_kind"],
            device_reported_at=v["device_reported_at"],
            identification=v["identification"],
            credential=request.auth,
        )
        return Response(
            {"duplicate": not created, "record": record_dict(record), "receipt": build_receipt(record)},
            status=201 if created else 200,
        )


class PunchReceiptView(DeviceView):
    """Comprovante de uma marcação feita por ESTE dispositivo."""

    def get(self, request, record_id):
        record = (
            TimeRecord.objects.select_related("company", "unit", "device")
            .filter(pk=record_id, device=request.device)
            .first()
        )
        if record is None:
            raise Http404
        return Response(build_receipt(record))


# ---------- Painel (somente leitura) ----------


def _visible_records(request, company):
    employees = ops_services.visible_employees(request, company)
    return TimeRecord.objects.filter(company=company, employee__in=employees)


class TimeRecordListView(APIView):
    """Histórico de marcações. Não há escrita: nenhum método além de GET é aceito."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, company_id):
        company = reader_company(request, company_id)
        qs = _visible_records(request, company).select_related("unit", "device")
        p = request.query_params
        for param, field in (("employee", "employee_id"), ("unit", "unit_id")):
            if value := p.get(param, ""):
                if not (value.isascii() and value.isdigit() and len(value) < 19):
                    raise ValidationError({param: "Identificador inválido."})
                qs = qs.filter(**{field: int(value)})
        for param, lookup in (("from", "occurred_local_date__gte"), ("to", "occurred_local_date__lte")):
            if value := p.get(param, ""):
                try:
                    parsed = parse_date(value)
                except ValueError:
                    parsed = None
                if parsed is None:
                    raise ValidationError({param: "Use o formato AAAA-MM-DD."})
                qs = qs.filter(**{lookup: parsed})
        paginator = Pagination()
        page = paginator.paginate_queryset(qs.order_by("-occurred_at", "-id"), request)
        return paginator.get_paginated_response([record_dict(r) for r in page])


class TimeRecordDetailView(APIView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, company_id, record_id):
        company = reader_company(request, company_id)
        record = (
            _visible_records(request, company)
            .select_related("company", "unit", "device")
            .filter(pk=record_id)
            .first()
        )
        if record is None:
            raise Http404
        return Response({"record": record_dict(record), "receipt": build_receipt(record)})


# ---------- Dados do empregador ----------


class EmployerView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        return Response(employer_dict(company, mask_document=not is_admin(request)))

    @transaction.atomic
    def patch(self, request, company_id):
        company = admin_company(request, company_id)
        company = Company.objects.select_for_update().get(pk=company.pk)
        data = EmployerSerializer(data=request.data, context={"company": company})
        data.is_valid(raise_exception=True)
        changes = data.validated_data
        before = {k: getattr(company, k) for k in changes}
        before_kind = company.tax_id_type
        with transaction.atomic():
            for field, value in changes.items():
                setattr(company, field, value)
            if changes:
                company.save(update_fields=list(changes))
            after = {k: getattr(company, k) for k in changes}
            # CPF do empregador também é dado pessoal. Nunca persistir o número na auditoria.
            for values, kind in ((before, before_kind), (after, company.tax_id_type)):
                if kind == "CPF" and "tax_id" in values:
                    values["tax_id"] = "[omitido]"
            audit.record(
                request,
                "employer.updated",
                company=company,
                target=company,
                before=before,
                after=after,
            )
        return Response(employer_dict(company))
