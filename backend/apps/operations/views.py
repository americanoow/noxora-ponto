import hashlib

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers as drf
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.billing import services as billing
from apps.companies.models import Membership, Role
from apps.companies.permissions import require_role, resolve_company

from . import importing, services
from .models import Assignment, Employee, Sector, Unit, WorkSchedule
from .serializers import (
    AssignmentCreateSerializer,
    EmployeeUpdateSerializer,
    EmployeeWriteSerializer,
    ScheduleAssignCreateSerializer,
    SectorSerializer,
    UnitSerializer,
    WorkScheduleSerializer,
    employee_to_dict,
)


def admin_company(request, company_id):
    company = resolve_company(request, company_id)
    require_role(request, Role.COMPANY_ADMIN)
    return company


def reader_company(request, company_id):
    company = resolve_company(request, company_id)
    require_role(request, Role.COMPANY_ADMIN, Role.MANAGER)
    return company


def is_admin(request):
    return request.membership.role == Role.COMPANY_ADMIN


class Pagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_or_404(queryset, pk):
    obj = queryset.filter(pk=pk).first()
    if obj is None:
        raise Http404
    return obj


def _valid_id(value):
    return value.isascii() and value.isdecimal() and len(value) <= 19 and 0 < int(value) <= 2**63 - 1


def _apply(instance, validated, fields):
    changed = []
    for field in fields:
        if field in validated:
            setattr(instance, field, validated[field])
            changed.append(field)
    return changed


# ---------- Unidades e setores ----------


def _visible_units(request, company):
    units = Unit.objects.filter(company=company)
    if is_admin(request):
        return units
    return units.filter(pk__in=services.visible_unit_ids(request.membership))


def _visible_sectors(request, company):
    sectors = Sector.objects.filter(company=company)
    if is_admin(request):
        return sectors
    m = request.membership
    return sectors.filter(Q(pk__in=m.scope_sectors.values("pk")) | Q(unit__in=m.scope_units.values("pk")))


class UnitListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        return Response(UnitSerializer(_visible_units(request, company), many=True).data)

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = UnitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                unit = Unit.objects.create(company=company, **data.validated_data)
                audit.record(request, "unit.created", company=company, target=unit)
        except IntegrityError:
            raise ValidationError({"name": "Já existe uma unidade com este nome."}) from None
        return Response(UnitSerializer(unit).data, status=201)


class UnitDetailView(APIView):
    def get(self, request, company_id, unit_id):
        company = reader_company(request, company_id)
        return Response(UnitSerializer(_get_or_404(_visible_units(request, company), unit_id)).data)

    def patch(self, request, company_id, unit_id):
        company = admin_company(request, company_id)
        unit = _get_or_404(Unit.objects.filter(company=company), unit_id)
        data = UnitSerializer(unit, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                data.save()
                audit.record(
                    request, "unit.updated", company=company, target=unit, changes=sorted(data.validated_data)
                )
        except IntegrityError:
            raise ValidationError({"name": "Já existe uma unidade com este nome."}) from None
        return Response(data.data)


class SectorListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        sectors = _visible_sectors(request, company)
        if unit := request.query_params.get("unit"):
            sectors = sectors.filter(unit_id=unit) if _valid_id(unit) else sectors.none()
        return Response(SectorSerializer(sectors, many=True).data)

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = SectorSerializer(data=request.data, context={"company": company})
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                sector = Sector.objects.create(company=company, **data.validated_data)
                audit.record(request, "sector.created", company=company, target=sector)
        except IntegrityError:
            raise ValidationError({"name": "Já existe um setor com este nome na unidade."}) from None
        return Response(SectorSerializer(sector).data, status=201)


class SectorDetailView(APIView):
    def patch(self, request, company_id, sector_id):
        company = admin_company(request, company_id)
        sector = _get_or_404(Sector.objects.filter(company=company), sector_id)
        data = SectorSerializer(sector, data=request.data, partial=True, context={"company": company})
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                data.save()
                audit.record(
                    request,
                    "sector.updated",
                    company=company,
                    target=sector,
                    changes=sorted(data.validated_data),
                )
        except IntegrityError:
            raise ValidationError({"name": "Já existe um setor com este nome na unidade."}) from None
        return Response(data.data)


# ---------- Funcionários ----------


def _resolve_access_user(company, email):
    if not email:
        return None
    membership = (
        Membership.objects.filter(company=company, user__email__iexact=email).select_related("user").first()
    )
    if membership is None:
        raise ValidationError({"access_email": "Não há acesso da empresa com este e-mail."})
    return membership.user


def _employees_with_assignments(queryset):
    from django.db.models import Prefetch

    return queryset.select_related("access_user").prefetch_related(
        Prefetch("assignments", queryset=Assignment.objects.select_related("unit", "sector"))
    )


def _bool_param(value):
    return {"true": True, "1": True, "false": False, "0": False}.get(value.lower()) if value else None


class EmployeeListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        qs = services.visible_employees(request, company)
        p = request.query_params
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(full_name__icontains=q) | Q(registration__icontains=q))
        active = _bool_param(p.get("active", ""))
        if active is not None:
            qs = qs.filter(is_active=active)
        unit, sector = p.get("unit", ""), p.get("sector", "")
        if unit or sector:
            current = Assignment.objects.filter(employee=OuterRef("pk")).filter(services.current_q())
            if unit:
                current = current.filter(unit_id=unit) if _valid_id(unit) else current.none()
            if sector:
                current = current.filter(sector_id=sector) if _valid_id(sector) else current.none()
            qs = qs.filter(Exists(current))
        paginator = Pagination()
        page = paginator.paginate_queryset(_employees_with_assignments(qs), request)
        return paginator.get_paginated_response([employee_to_dict(e) for e in page])

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = EmployeeWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        access_user = _resolve_access_user(company, v.pop("access_email"))
        try:
            with transaction.atomic():
                billing.check_limit(company, "employees")
                employee = Employee.objects.create(company=company, access_user=access_user, **v)
                audit.record(request, "employee.created", company=company, target=employee)
        except IntegrityError:
            raise ValidationError(
                {"registration": "Matrícula, CPF ou acesso já utilizado por outro funcionário."}
            ) from None
        return Response(employee_to_dict(employee, full_cpf=True), status=201)


def _employee_or_404(request, company, employee_id):
    return _get_or_404(_employees_with_assignments(services.visible_employees(request, company)), employee_id)


class EmployeeDetailView(APIView):
    def get(self, request, company_id, employee_id):
        company = reader_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        return Response(employee_to_dict(employee, full_cpf=is_admin(request)))

    def patch(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        data = EmployeeUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        changed = _apply(employee, v, ["full_name", "cpf", "admission_date"])
        if "access_email" in v:
            employee.access_user = _resolve_access_user(company, v["access_email"])
            changed.append("access_user")
        activating = "is_active" in v and v["is_active"] and not employee.is_active
        if "is_active" in v and v["is_active"] != employee.is_active:
            employee.is_active = v["is_active"]
            employee.inactivated_at = None if v["is_active"] else timezone.now()
            changed += ["is_active", "inactivated_at"]
        try:
            with transaction.atomic():
                if activating:  # reativar também ocupa uma vaga do plano: mesma verificação sob bloqueio
                    billing.check_limit(company, "employees")
                if changed:
                    employee.save(update_fields=changed)
                audit.record(
                    request, "employee.updated", company=company, target=employee, changes=sorted(changed)
                )
        except IntegrityError:
            raise ValidationError({"cpf": "CPF ou acesso já utilizado por outro funcionário."}) from None
        return Response(employee_to_dict(employee, full_cpf=True))


def _interval_dict(item, name_field, name):
    return {
        "id": item.pk,
        name_field: name,
        "valid_from": item.valid_from,
        "valid_to": item.valid_to,
    }


class EmployeeAssignmentsView(APIView):
    def get(self, request, company_id, employee_id):
        company = reader_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        rows = employee.assignments.all()
        return Response(
            [
                {
                    "id": a.pk,
                    "unit": {"id": a.unit_id, "name": a.unit.name},
                    "sector": {"id": a.sector_id, "name": a.sector.name} if a.sector_id else None,
                    "valid_from": a.valid_from,
                    "valid_to": a.valid_to,
                }
                for a in rows
            ]
        )

    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        data = AssignmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        unit = Unit.objects.filter(company=company, pk=v["unit"]).first()
        if unit is None:
            raise ValidationError({"unit": "Unidade inválida."})
        sector = None
        if v["sector"] is not None:
            sector = Sector.objects.filter(company=company, pk=v["sector"]).first()
            if sector is None:
                raise ValidationError({"sector": "Setor inválido para a unidade."})
        with transaction.atomic():
            assignment = services.assign_unit(employee, company, unit, sector, v["valid_from"])
            audit.record(
                request,
                "employee.assignment_changed",
                company=company,
                target=employee,
                valid_from=str(v["valid_from"]),
            )
        return Response(
            {"id": assignment.pk, "valid_from": assignment.valid_from, "valid_to": assignment.valid_to},
            status=201,
        )


class EmployeeSchedulesView(APIView):
    def get(self, request, company_id, employee_id):
        company = reader_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        rows = employee.schedule_assignments.select_related("schedule")
        return Response(
            [_interval_dict(r, "schedule", {"id": r.schedule_id, "name": r.schedule.name}) for r in rows]
        )

    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(request, company, employee_id)
        data = ScheduleAssignCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        schedule = WorkSchedule.objects.filter(company=company, pk=v["schedule"]).first()
        if schedule is None:
            raise ValidationError({"schedule": "Jornada inválida."})
        with transaction.atomic():
            row = services.assign_schedule(employee, company, schedule, v["valid_from"])
            audit.record(
                request,
                "employee.schedule_changed",
                company=company,
                target=employee,
                valid_from=str(v["valid_from"]),
            )
        return Response({"id": row.pk, "valid_from": row.valid_from, "valid_to": row.valid_to}, status=201)


# ---------- Jornadas ----------


def _visible_schedules(request, company):
    schedules = WorkSchedule.objects.filter(company=company)
    if not is_admin(request):
        schedules = schedules.filter(
            assignments__employee__in=services.visible_employees(request, company)
        ).distinct()
    return schedules


class ScheduleListView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        schedules = _visible_schedules(request, company).prefetch_related("days")
        return Response(WorkScheduleSerializer(schedules, many=True).data)

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = WorkScheduleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            with transaction.atomic():
                schedule = WorkSchedule.objects.create(
                    company=company, name=v["name"], is_active=v.get("is_active", True)
                )
                services.replace_schedule_days(schedule, v["days"])
                audit.record(request, "schedule.created", company=company, target=schedule)
        except IntegrityError:
            raise ValidationError({"name": "Já existe uma jornada com este nome."}) from None
        return Response(WorkScheduleSerializer(schedule).data, status=201)


class ScheduleDetailView(APIView):
    def get(self, request, company_id, schedule_id):
        company = reader_company(request, company_id)
        schedule = _get_or_404(_visible_schedules(request, company), schedule_id)
        return Response(WorkScheduleSerializer(schedule).data)

    def patch(self, request, company_id, schedule_id):
        company = admin_company(request, company_id)
        schedule = _get_or_404(WorkSchedule.objects.filter(company=company), schedule_id)
        data = WorkScheduleSerializer(schedule, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            with transaction.atomic():
                changed = _apply(schedule, v, ["name", "is_active"])
                if changed:
                    schedule.save(update_fields=changed)
                if "days" in v:
                    services.replace_schedule_days(schedule, v["days"])
                    changed.append("days")
                audit.record(
                    request, "schedule.updated", company=company, target=schedule, changes=sorted(changed)
                )
        except IntegrityError:
            raise ValidationError({"name": "Já existe uma jornada com este nome."}) from None
        schedule.refresh_from_db()
        return Response(WorkScheduleSerializer(schedule).data)


# ---------- Importação ----------


class ImportRequestSerializer(drf.Serializer):
    csv = drf.CharField(trim_whitespace=False)
    commit = drf.BooleanField(default=False)


class EmployeeImportView(APIView):
    """Sem `commit`: apenas prévia. Com `commit`: grava tudo ou nada, e só se não houver erros."""

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        data = ImportRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            rows = importing.parse(data.validated_data["csv"])
        except importing.ImportFileError as exc:
            raise ValidationError({"csv": str(exc)}) from exc
        records, errors = importing.validate(company, rows)
        committed = 0
        # A sessão guarda apenas o resumo do arquivo, nunca CPF ou conteúdo CSV.
        preview_key = f"employee_import_preview:{company.pk}"
        digest = hashlib.sha256(data.validated_data["csv"].encode("utf-8")).hexdigest()
        if data.validated_data["commit"] and not errors:
            if request.session.get(preview_key) != digest:
                raise ValidationError({"csv": "Pré-visualize este arquivo antes de importar."})
            try:
                with transaction.atomic():
                    committed = len(importing.commit(company, records))
                    audit.record(request, "employee.imported", company=company, count=committed)
            except IntegrityError:
                raise ValidationError({"csv": "Conflito de cadastro. Faça uma nova prévia."}) from None
            request.session.pop(preview_key, None)
        elif not data.validated_data["commit"]:
            request.session.pop(preview_key, None)
            if not errors:
                request.session[preview_key] = digest
        return Response({"total": len(rows), "valid": len(records), "errors": errors, "committed": committed})
