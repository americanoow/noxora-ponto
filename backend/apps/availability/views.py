from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attendance.views import own_employee
from apps.audit import services as audit
from apps.companies.permissions import resolve_company
from apps.operations import services as ops_services
from apps.operations.views import admin_company, reader_company

from . import services
from .models import AvailabilitySettings, AvailabilityUpdate, Status


def _id_param(value, field):
    if value in (None, ""):
        return None
    if not (value.isascii() and value.isdigit() and len(value) < 19):
        raise ValidationError({field: "Identificador inválido."})
    return int(value)


def _validated(data):
    status = data.get("status")
    if status not in Status.values:
        raise ValidationError({"status": "Situação inválida."})
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 140:
        raise ValidationError({"note": "Observação de até 140 caracteres."})
    expires = data.get("expires_minutes")
    if expires is not None and (
        isinstance(expires, bool) or not isinstance(expires, int) or not 1 <= expires <= 1440
    ):
        raise ValidationError({"expires_minutes": "Entre 1 e 1440 minutos."})
    return status, note.strip(), expires


def update_dict(u):
    return {
        "id": u.pk,
        "employee_id": u.employee_id,
        "status": u.status,
        "note": u.note,
        "source": u.source,
        "set_at": u.set_at,
        "expires_at": u.expires_at,
    }


def _settings_dict(conf):
    return {
        "enabled": conf.enabled,
        "stale_after_minutes": conf.stale_after_minutes,
        "show_punch_hint": conf.show_punch_hint,
    }


class BoardView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        p = request.query_params
        return Response(
            services.board(
                request=request,
                company=company,
                unit_id=_id_param(p.get("unit"), "unit"),
                sector_id=_id_param(p.get("sector"), "sector"),
            )
        )

    def post(self, request, company_id):
        company = reader_company(request, company_id)
        services.require_enabled(company)
        employee_id = request.data.get("employee_id")
        employee = (
            ops_services.visible_employees(request, company).filter(pk=employee_id, is_active=True).first()
            if isinstance(employee_id, int)
            else None
        )
        if employee is None:
            raise Http404
        status, note, expires = _validated(request.data)
        with transaction.atomic():
            u = services.set_status(
                company=company,
                employee=employee,
                user=request.user,
                status=status,
                note=note,
                expires_minutes=expires,
                source="manager",
            )
            audit.record(request, "availability.updated", company=company, target=employee, status=status)
        return Response(update_dict(u), status=201)


class HistoryView(APIView):
    def get(self, request, company_id, employee_id):
        company = reader_company(request, company_id)
        services.require_enabled(company)
        if not ops_services.visible_employees(request, company).filter(pk=employee_id).exists():
            raise Http404
        rows = AvailabilityUpdate.objects.filter(company=company, employee_id=employee_id)[:100]
        return Response([update_dict(u) for u in rows])


class SettingsView(APIView):
    def get(self, request, company_id):
        # Qualquer membro pode saber se o módulo está ligado (a interface esconde o que não existe).
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        return Response(_settings_dict(services.settings_for(company)))

    def patch(self, request, company_id):
        company = admin_company(request, company_id)
        conf, _ = AvailabilitySettings.objects.get_or_create(company=company)
        stale = request.data.get("stale_after_minutes", conf.stale_after_minutes)
        hint = request.data.get("show_punch_hint", conf.show_punch_hint)
        enabled = request.data.get("enabled", conf.enabled)
        if not isinstance(enabled, bool):
            raise ValidationError({"enabled": "Use verdadeiro ou falso."})
        if isinstance(stale, bool) or not isinstance(stale, int) or not 5 <= stale <= 1440:
            raise ValidationError({"stale_after_minutes": "Entre 5 e 1440 minutos."})
        if not isinstance(hint, bool):
            raise ValidationError({"show_punch_hint": "Use verdadeiro ou falso."})
        conf.stale_after_minutes, conf.show_punch_hint, conf.enabled = stale, hint, enabled
        conf.save()
        audit.record(
            request, "availability.settings_changed", company=company, stale=stale, hint=hint, enabled=enabled
        )
        return Response(_settings_dict(conf))


class MyAvailabilityView(APIView):
    def get(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        services.require_enabled(company)
        employee = own_employee(request, company)
        u = AvailabilityUpdate.objects.filter(employee=employee).first()
        return Response(update_dict(u) if u else None)

    def post(self, request, company_id):
        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        services.require_enabled(company)
        employee = own_employee(request, company)
        status, note, expires = _validated(request.data)
        u = services.set_status(
            company=company,
            employee=employee,
            user=request.user,
            status=status,
            note=note,
            expires_minutes=expires,
            source="employee",
        )
        return Response(update_dict(u), status=201)
