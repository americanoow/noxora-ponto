from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError
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
from .security import BoundedJSONParser


class BiometricView(APIView):
    parser_classes = [BoundedJSONParser]


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


# ---------- Portal do funcionário (titular dos dados) ----------


class MyBiometricView(BiometricView):
    """O próprio funcionário consulta a situação da sua biometria (nunca o dado) e pode retirar o
    consentimento a qualquer momento, de forma gratuita e facilitada (LGPD, art. 8º, §5º, e art. 18, IX).
    Retirar apaga o rosto cadastrado; o ponto passa a ser registrado pela matrícula."""

    def _employee(self, request, company_id):
        from apps.attendance.views import own_employee

        company = resolve_company(request, company_id)
        if request.membership is None:
            raise PermissionDenied("Você não tem permissão para esta operação.")
        return company, own_employee(request, company)

    @staticmethod
    def _mine(employee):
        status = _status(employee)
        return {
            "consent": status["consent"],
            "enrolled": status["template"] is not None,
            "enrolled_at": status["template"]["created_at"] if status["template"] else None,
            "notice": (
                "O sistema guarda só um modelo matemático do rosto, criptografado, nunca a foto. "
                "A biometria é opcional: sem ela, o ponto é registrado pela matrícula, sem prejuízo."
            ),
        }

    def get(self, request, company_id):
        _, employee = self._employee(request, company_id)
        return Response(self._mine(employee))

    def delete(self, request, company_id):
        company, employee = self._employee(request, company_id)
        with transaction.atomic():
            services.revoke_consent(employee=employee, user=request.user)
            audit.record(
                request, "biometric.consent_revoked", company=company, target=employee, by_holder=True
            )
        return Response(self._mine(employee))


# ---------- Painel ----------


class BiometricStatusView(BiometricView):
    def get(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        return Response(_status(_employee_or_404(company, employee_id)))

    def delete(self, request, company_id, employee_id):
        """Exclui o template (mantém o consentimento)."""
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        with transaction.atomic():
            employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
            template = services.active_template(employee)
            if template is None:
                raise Http404
            services.delete_template(template, user=request.user, reason="admin_request")
            audit.record(request, "biometric.template_deleted", company=company, target=employee)
        return Response(_status(employee))


class ConsentView(BiometricView):
    def post(self, request, company_id, employee_id):
        company = admin_company(request, company_id)
        employee = _employee_or_404(company, employee_id)
        version = request.data.get("policy_version", "")
        if not isinstance(version, str):
            raise ValidationError({"policy_version": "Informe uma versão textual."})
        version = version.strip()
        if not version or len(version) > 32:
            raise ValidationError({"policy_version": "Informe a versão da política (até 32 caracteres)."})
        evidence = request.data.get("evidence_ref", "")
        if not isinstance(evidence, str) or len(evidence) > 200:
            raise ValidationError({"evidence_ref": "Referência inválida."})
        evidence = evidence.strip()
        # LGPD, art. 8º, §2º: cabe à empresa provar o consentimento. Sem referência ao termo assinado
        # pelo funcionário (número, nome do arquivo, protocolo), o consentimento não é registrado.
        if len(evidence) < 3:
            raise ValidationError(
                {"evidence_ref": "Informe a referência do termo assinado pelo funcionário (número ou nome)."}
            )
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


class EnrollView(BiometricView):
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


class ExceptionView(BiometricView):
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
            {"authorization_id": auth.pk, "code": code, "expires_at": auth.expires_at},
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class IdentificationModeView(BiometricView):
    """Política de identificação (`mode`) e de marcação offline (`offline_policy`) da empresa."""

    MODES = ("registration", "face")
    OFFLINE = ("disabled", "registration_only")
    LIVENESS = ("certified", "basic_challenge")

    @staticmethod
    def _policy(company):
        return {
            "mode": company.identification_mode,
            "offline_policy": company.offline_policy,
            "face_liveness_policy": company.face_liveness_policy,
        }

    @classmethod
    def _body(cls, company):
        try:
            engine = engines.get_engine()
            engine_info = {
                "name": engine.name,
                "version": engine.version,
                "simulator": engine.is_simulator,
                "liveness_method": engine.liveness_method,
            }
        except engines.EngineUnavailable:
            engine_info = None
        return {**cls._policy(company), "engine": engine_info}

    def get(self, request, company_id):
        return Response(self._body(reader_company(request, company_id)))

    def patch(self, request, company_id):
        company = admin_company(request, company_id)
        data = request.data
        mode, offline = data.get("mode"), data.get("offline_policy")
        if mode == "face" and company.identification_mode != "face":
            # Ligar o modo facial sem motor configurado deixaria quem tem biometria dependente de código
            # de exceção a cada marcação. Melhor recusar a mudança do que restringir o registro.
            try:
                engines.get_engine().check_ready()
            except engines.EngineError:
                raise ValidationError(
                    {"mode": "O reconhecimento facial não está configurado no sistema. Fale com o suporte."}
                ) from None
        liveness = data.get("face_liveness_policy")
        if mode is None and offline is None and liveness is None:
            raise ValidationError({"detail": "Informe 'mode', 'offline_policy' e/ou 'face_liveness_policy'."})
        if liveness is not None and liveness not in self.LIVENESS:
            raise ValidationError({"face_liveness_policy": "Use 'certified' ou 'basic_challenge'."})
        if mode is not None and mode not in self.MODES:
            raise ValidationError({"mode": "Use 'registration' ou 'face'."})
        if offline is not None and offline not in self.OFFLINE:
            raise ValidationError({"offline_policy": "Use 'disabled' ou 'registration_only'."})
        before = self._policy(company)
        with transaction.atomic():
            fields = []
            if mode is not None:
                company.identification_mode = mode
                fields.append("identification_mode")
            if offline is not None:
                company.offline_policy = offline
                fields.append("offline_policy")
            if liveness is not None:
                company.face_liveness_policy = liveness
                fields.append("face_liveness_policy")
            company.save(update_fields=fields)
            audit.record(
                request,
                "identification.mode_changed",
                company=company,
                target=company,
                before=before,
                after=self._policy(company),
            )
        return Response(self._body(company))


# ---------- API do tablet ----------


class FaceChallengeView(DeviceView):
    """Emite o desafio de movimento (sequência imprevisível, uso único, prazo curto) para este tablet."""

    def post(self, request):
        # Antes de abrir a câmera: quem não tem biometria ativa não tem o rosto capturado (LGPD) e
        # registra pela matrícula. Matrícula desconhecida segue o fluxo normal (nada é revelado aqui).
        registration = request.data.get("registration")
        if isinstance(registration, str) and registration.strip():
            employee = ops_services.employee_for_device(request.device, registration.strip())
            reason = services.face_fallback_reason(employee) if employee is not None else None
            if reason is not None:
                return Response(
                    {"face_required": False, "reason": reason}, headers={"Cache-Control": "no-store"}
                )
        challenge = services.issue_challenge(request.device)
        return Response(
            {
                "face_required": True,
                "challenge_id": challenge.pk,
                "steps": challenge.steps,
                "expires_at": challenge.expires_at,
            },
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class FaceVerifyView(DeviceView):
    parser_classes = [BoundedJSONParser]

    """Verifica a captura contra o template do funcionário (1:1, escopo da unidade do aparelho)."""

    def post(self, request):
        registration = str(request.data.get("registration", "")).strip()
        if not registration or len(registration) > 30:
            raise ValidationError({"registration": "Informe a matrícula."})
        image = services.decode_image(request.data.get("image"))
        raw_frames = request.data.get("frames") or []
        if not isinstance(raw_frames, list) or len(raw_frames) > settings.BIOMETRIC_MAX_FRAMES:
            raise ValidationError({"frames": f"Envie até {settings.BIOMETRIC_MAX_FRAMES} quadros."})
        frames = tuple(services.decode_image(f, "frames") for f in raw_frames)
        employee = ops_services.employee_for_device(request.device, registration)
        if employee is None:
            raise Http404
        attempt = services.verify_face(
            device=request.device,
            employee=employee,
            image=image,
            frames=frames,
            challenge_id=request.data.get("challenge_id"),
        )
        body = {"outcome": attempt.outcome, "liveness": attempt.liveness}
        if (
            attempt.outcome == Outcome.SUCCESS
            and request.device.company.identification_mode == "face"
            and not services.liveness_accepted(request.device.company, attempt)
        ):
            # Rosto confere, mas a prova de vivacidade não atende à política: avisar o tablet já aqui.
            body["liveness_accepted"] = False
        if attempt.outcome == Outcome.SUCCESS:
            body.update(verification_id=attempt.pk, expires_at=attempt.expires_at)
            body["verification_token"] = signing.dumps(
                [attempt.pk, str(attempt.device_id), attempt.employee_id], salt="biometric-verification-v1"
            )
        status = 503 if attempt.outcome == Outcome.ENGINE_UNAVAILABLE else 200
        return Response(body, status=status, headers={"Cache-Control": "no-store"})
