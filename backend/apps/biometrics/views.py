from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.companies.models import Role
from apps.companies.permissions import require_role, resolve_company
from apps.devices.views import DeviceView
from apps.operations import services as ops_services
from apps.operations.models import Employee
from apps.operations.views import admin_company, reader_company

from . import engines, services
from .models import Outcome


def _employee_or_404(company, employee_id, *, request=None, scoped=False):
    employees = (
        ops_services.visible_employees(request, company)
        if scoped
        else Employee.objects.filter(company=company)
    )
    employee = employees.filter(pk=employee_id).first()
    if employee is None:
        raise Http404
    return employee


def _status(employee) -> dict:
    consent = services.active_consent(employee)
    template = services.active_template(employee)
    try:
        engine = engines.get_engine()
        engine_info = {"name": engine.name, "version": engine.version, "simulator": engine.is_simulator}
    except engines.EngineUnavailable:
        engine_info = None
    return {
        "employee_id": employee.pk,
        "consent": {"policy_version": consent.policy_version, "granted_at": consent.granted_at}
        if consent
        else None,
        "template": (
            {
                "engine": template.engine,
                "engine_version": template.engine_version,
                "created_at": template.created_at,
                "quality": template.quality,
            }
            if template
            else None
        ),
        "engine": engine_info,  # nunca inclui template, chave ou imagem
    }


# ---------- Painel ----------


class BiometricStatusView(APIView):
    def get(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        return Response(_status(_employee_or_404(company, employee_id)))

    def delete(self, request, company_id, employee_id):
        """Exclui o template (mantém o consentimento)."""
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        with transaction.atomic():
            template = services.active_template(employee)
            if template is None:
                raise Http404
            services.delete_template(template, user=request.user, reason="admin_request")
            audit.record(request, "biometric.template_deleted", company=company, target=employee)
        return Response(_status(employee))


class ConsentView(APIView):
    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        version = str(request.data.get("policy_version", "")).strip()
        if not version or len(version) > 32:
            raise ValidationError({"policy_version": "Informe a versão da política (até 32 caracteres)."})
        evidence = str(request.data.get("evidence_ref", "")).strip()[:200]
        with transaction.atomic():
            services.grant_consent(
                employee=employee, user=request.user, policy_version=version, evidence_ref=evidence
            )
            audit.record(
                request, "biometric.consent_granted", company=company, target=employee, policy_version=version
            )
        return Response(_status(employee), status=201)

    def delete(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        with transaction.atomic():
            services.revoke_consent(employee=employee, user=request.user)
            audit.record(request, "biometric.consent_revoked", company=company, target=employee)
        return Response(_status(employee))


class EnrollView(APIView):
    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        with transaction.atomic():
            template = services.enroll(
                employee=employee, user=request.user, images_b64=request.data.get("images")
            )
            audit.record(
                request, "biometric.enrolled", company=company, target=employee, engine=template.engine
            )
        return Response(_status(employee), status=201)


class ExceptionView(APIView):
    """Autoriza UMA marcação por exceção (sem face). Administrador ou gestor do escopo do funcionário."""

    def post(self, request, company_id, employee_id):
        company = resolve_company(request, company_id)
        require_role(request, Role.COMPANY_ADMIN, Role.MANAGER)
        employee = _employee_or_404(company, employee_id, request=request, scoped=True)
        if not employee.is_active:
            raise ValidationError({"detail": "Funcionário inativo."})
        with transaction.atomic():
            auth, code = services.create_exception(
                company=company, employee=employee, user=request.user, reason=request.data.get("reason", "")
            )
            audit.record(
                request,
                "identification.exception_authorized",
                company=company,
                target=employee,
                authorization=auth.pk,
            )
        # O código aparece só nesta resposta: informe-o ao funcionário, que o digita no tablet.
        return Response(
            {"authorization_id": auth.pk, "code": code, "expires_at": auth.expires_at}, status=201
        )


class IdentificationModeView(APIView):
    def get(self, request, company_id):
        company = reader_company(request, company_id)
        return Response({"mode": company.identification_mode})

    def patch(self, request, company_id):
        company = admin_company(request, company_id)
        mode = request.data.get("mode")
        if mode not in ("registration", "face"):
            raise ValidationError({"mode": "Use 'registration' ou 'face'."})
        before = company.identification_mode
        with transaction.atomic():
            company.identification_mode = mode
            company.save(update_fields=["identification_mode"])
            audit.record(
                request,
                "identification.mode_changed",
                company=company,
                target=company,
                before=before,
                after=mode,
            )
        return Response({"mode": mode})


# ---------- API do tablet ----------


class FaceVerifyView(DeviceView):
    """Verifica a captura contra o template do funcionário (1:1, escopo da unidade do aparelho)."""

    def post(self, request):
        registration = str(request.data.get("registration", "")).strip()
        if not registration or len(registration) > 30:
            raise ValidationError({"registration": "Informe a matrícula."})
        image = services.decode_image(request.data.get("image"))
        employee = ops_services.employee_for_device(request.device, registration)
        if employee is None:
            raise Http404
        attempt = services.verify_face(device=request.device, employee=employee, image=image)
        body = {"outcome": attempt.outcome, "liveness": attempt.liveness}
        if attempt.outcome == Outcome.SUCCESS:
            body.update(verification_id=attempt.pk, expires_at=attempt.expires_at)
        status = 503 if attempt.outcome == Outcome.ENGINE_UNAVAILABLE else 200
        return Response(body, status=status)
