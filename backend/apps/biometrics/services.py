import base64
import binascii
import datetime
import hashlib
import hmac
import secrets

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.operations.models import Employee
from apps.timeclock.services import IdentificationRejected, IdentificationResult

from . import crypto, engines
from .models import (
    BiometricConsent,
    BiometricTemplate,
    ExceptionAuthorization,
    ExceptionBudget,
    Outcome,
    TemplateStatus,
    VerificationAttempt,
)

FAILURE_OUTCOMES = (Outcome.NO_MATCH, Outcome.LIVENESS_FAILED)


# ---------- Imagens ----------


def decode_image(value, field="image") -> bytes:
    """Base64 estrito, com limite de tamanho. A imagem só vive em memória."""
    if not isinstance(value, str) or not value:
        raise ValidationError({field: "Imagem inválida."})
    if len(value) > settings.BIOMETRIC_MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise ValidationError({field: "Imagem grande demais."})
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError({field: "Imagem inválida."}) from None
    if len(data) > settings.BIOMETRIC_MAX_IMAGE_BYTES:
        raise ValidationError({field: "Imagem grande demais."})
    return data


# ---------- Consentimento e cadastro ----------


def active_consent(employee):
    return BiometricConsent.objects.filter(employee=employee, revoked_at__isnull=True).first()


def active_template(employee):
    return BiometricTemplate.objects.filter(employee=employee, status=TemplateStatus.ACTIVE).first()


def grant_consent(*, employee, user, policy_version, evidence_ref=""):
    with transaction.atomic():
        locked = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        if active_consent(locked):
            raise ValidationError({"detail": "O consentimento já está registrado."})
        return BiometricConsent.objects.create(
            company_id=locked.company_id,
            employee=locked,
            policy_version=policy_version,
            evidence_ref=evidence_ref,
            granted_by=user,
        )


@transaction.atomic
def delete_template(template, *, user, reason):
    """Apaga o conteúdo criptografado, mantendo só os metadados para auditoria."""
    Employee.objects.select_for_update(no_key=True).get(pk=template.employee_id)
    template.refresh_from_db()
    VerificationAttempt.objects.filter(employee_id=template.employee_id, consumed_at__isnull=True).update(
        expires_at=timezone.now()
    )
    template.status = TemplateStatus.DELETED
    template.ciphertext = b""
    template.nonce = b""
    template.deleted_at = timezone.now()
    template.deleted_by = user
    template.delete_reason = reason[:60]
    template.save(
        update_fields=["status", "ciphertext", "nonce", "deleted_at", "deleted_by", "delete_reason"]
    )


def revoke_consent(*, employee, user):
    """Revogar o consentimento exclui o template."""
    with transaction.atomic():
        locked = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        consent = active_consent(locked)
        if consent is None:
            raise ValidationError({"detail": "Não há consentimento ativo."})
        consent.revoked_at, consent.revoked_by = timezone.now(), user
        consent.save(update_fields=["revoked_at", "revoked_by"])
        template = active_template(locked)
        if template:
            delete_template(template, user=user, reason="consent_revoked")
        return consent


@transaction.atomic
def enroll(*, employee, user, images_b64):
    employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
    if active_consent(employee) is None:
        raise ValidationError({"detail": "Registre o consentimento antes do cadastro facial."})
    if not isinstance(images_b64, list) or not (1 <= len(images_b64) <= settings.BIOMETRIC_MAX_IMAGES):
        raise ValidationError({"images": f"Envie de 1 a {settings.BIOMETRIC_MAX_IMAGES} imagens."})
    images = [decode_image(v, "images") for v in images_b64]
    try:
        engine = engines.get_engine()
        result = engine.enroll(images)
    except engines.PoorQuality:
        raise ValidationError({"images": "Qualidade insuficiente. Refaça a captura."}) from None
    except engines.EngineError:
        raise ValidationError({"detail": "Motor biométrico indisponível."}) from None
    finally:
        del images
    try:
        key_id, nonce, ciphertext = crypto.encrypt(
            result.template, crypto.make_aad(employee.company_id, employee.pk, engine.name)
        )
    except crypto.CryptoUnavailable:
        raise ValidationError({"detail": "Proteção de chaves biométricas não configurada."}) from None
    with transaction.atomic():
        locked = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
        if active_consent(locked) is None:
            raise ValidationError({"detail": "Registre o consentimento antes do cadastro facial."})
        old = active_template(locked)
        if old:
            delete_template(old, user=user, reason="replaced")
        return BiometricTemplate.objects.create(
            company_id=locked.company_id,
            employee=locked,
            engine=engine.name,
            engine_version=engine.version,
            key_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
            quality=result.quality,
            created_by=user,
        )


# ---------- Verificação 1:1 ----------


def _attempt(device, employee, outcome, **extra):
    return VerificationAttempt.objects.create(
        company_id=device.company_id,
        unit_id=device.unit_id,
        device=device,
        employee=employee,
        outcome=outcome,
        **extra,
    )


def _locked(employee) -> bool:
    since = timezone.now() - datetime.timedelta(seconds=settings.BIOMETRIC_LOCKOUT_WINDOW_SECONDS)
    recent = VerificationAttempt.objects.filter(
        employee=employee, created_at__gte=since, outcome__in=(*FAILURE_OUTCOMES, Outcome.SUCCESS)
    ).order_by("-id")
    failures = 0
    for outcome in recent.values_list("outcome", flat=True)[: settings.BIOMETRIC_LOCKOUT_FAILURES + 1]:
        if outcome in FAILURE_OUTCOMES:
            failures += 1
        elif outcome == Outcome.SUCCESS:
            break  # falhas anteriores ao último sucesso não contam
    return failures >= settings.BIOMETRIC_LOCKOUT_FAILURES


@transaction.atomic
def verify_face(*, device, employee, image: bytes, frames: tuple[bytes, ...] = ()) -> VerificationAttempt:
    """Compara a captura com o template do funcionário. Sempre registra a tentativa (sem imagem)."""
    employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
    if employee.company_id != device.company_id or not employee.is_active:
        raise IdentificationRejected({"identification": "Funcionário indisponível."})
    if active_consent(employee) is None:
        return _attempt(device, employee, Outcome.NO_CONSENT)
    template = active_template(employee)
    if template is None:
        return _attempt(device, employee, Outcome.NO_TEMPLATE)
    if _locked(employee):
        return _attempt(device, employee, Outcome.LOCKED)
    try:
        engine = engines.get_engine()
        if (engine.name, engine.version) != (template.engine, template.engine_version):
            return _attempt(device, employee, Outcome.ENGINE_UNAVAILABLE)
        stored = crypto.decrypt(
            template.key_id,
            template.nonce,
            template.ciphertext,
            crypto.make_aad(template.company_id, template.employee_id, template.engine),
        )
        result = engine.verify(stored, image, tuple(frames))
    except engines.PoorQuality:
        return _attempt(
            device, employee, Outcome.POOR_QUALITY, engine=engine.name, engine_version=engine.version
        )
    except (engines.EngineError, crypto.CryptoUnavailable, crypto.DecryptionFailed):
        return _attempt(device, employee, Outcome.ENGINE_UNAVAILABLE)
    info = {
        "engine": engine.name,
        "engine_version": engine.version,
        "score": result.score,
        "liveness": result.liveness,
        "liveness_method": engine.liveness_method if result.liveness != "not_performed" else "",
    }
    if result.liveness == "failed":
        return _attempt(device, employee, Outcome.LIVENESS_FAILED, **info)
    if not result.matched:
        return _attempt(device, employee, Outcome.NO_MATCH, **info)
    expires = timezone.now() + datetime.timedelta(seconds=settings.BIOMETRIC_VERIFICATION_TTL_SECONDS)
    return _attempt(device, employee, Outcome.SUCCESS, expires_at=expires, **info)


def liveness_accepted(company, attempt) -> bool:
    """Vivacidade aprovada E com método aceito pela política da empresa."""
    if attempt.liveness != "passed":
        return False
    accepted = {"certified"}
    if attempt.engine == "simulator":
        accepted.add("simulated")  # só chega aqui em debug (ver checagem do simulador acima)
    if company.face_liveness_policy == "basic_challenge":
        accepted.add("motion_challenge_v1")
    return attempt.liveness_method in accepted


def _int_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise IdentificationRejected({"identification": f"{field} inválido."})
    return value


class FaceProvider:
    """Consome (uso único) uma verificação facial bem-sucedida deste dispositivo e funcionário."""

    method = "face"

    def verify(self, *, device, employee, payload) -> IdentificationResult:
        vid = _int_id(payload.get("verification_id"), "verification_id")
        token = payload.get("verification_token")
        if not isinstance(token, str) or len(token) > 256:
            raise IdentificationRejected({"identification": "Verificação facial inválida ou expirada."})
        try:
            signed = signing.loads(
                token, salt="biometric-verification-v1", max_age=settings.BIOMETRIC_VERIFICATION_TTL_SECONDS
            )
        except signing.BadSignature:
            raise IdentificationRejected(
                {"identification": "Verificação facial inválida ou expirada."}
            ) from None
        if signed != [vid, str(device.pk), employee.pk]:
            raise IdentificationRejected({"identification": "Verificação facial inválida ou expirada."})
        now = timezone.now()
        attempt = (
            VerificationAttempt.objects.select_for_update(no_key=True)
            .filter(
                pk=vid,
                device=device,
                employee=employee,
                company_id=device.company_id,
                outcome=Outcome.SUCCESS,
            )
            .first()
        )
        if (
            attempt is None
            or attempt.consumed_at is not None
            or attempt.expires_at is None
            or attempt.expires_at <= now
        ):
            raise IdentificationRejected({"identification": "Verificação facial inválida ou expirada."})
        if active_consent(employee) is None or active_template(employee) is None:
            raise IdentificationRejected({"identification": "Cadastro facial indisponível."})
        if attempt.engine == "simulator" and not (settings.DEBUG and settings.BIOMETRIC_ALLOW_SIMULATOR):
            raise IdentificationRejected({"identification": "Motor simulador não é aceito."})
        if device.company.identification_mode == "face" and not liveness_accepted(device.company, attempt):
            raise IdentificationRejected({"identification": "A empresa exige prova de vivacidade aprovada."})
        attempt.consumed_at = now
        attempt.save(update_fields=["consumed_at"])
        return IdentificationResult(self.method, str(attempt.pk))


# ---------- Exceção autorizada ----------


def _exception_code_hash(employee_id: int, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"noxora-exception:{employee_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


@transaction.atomic
def create_exception(*, company, employee, user, reason):
    """Cria a autorização e devolve (autorização, código). O código de 8 dígitos só existe aqui, em claro."""
    if not isinstance(reason, str):
        raise ValidationError({"reason": "Informe um motivo textual."})
    reason = reason.strip()
    if len(reason) < 5:
        raise ValidationError({"reason": "Informe o motivo (mínimo de 5 caracteres)."})
    employee = Employee.objects.select_for_update(no_key=True).get(pk=employee.pk)
    if employee.company_id != company.pk or not employee.is_active:
        raise ValidationError({"detail": "Funcionário indisponível."})
    ExceptionAuthorization.objects.filter(employee=employee, consumed_at__isnull=True).update(
        expires_at=timezone.now()
    )
    code = f"{secrets.randbelow(10**8):08d}"
    expires = timezone.now() + datetime.timedelta(minutes=settings.EXCEPTION_AUTHORIZATION_TTL_MINUTES)
    auth = ExceptionAuthorization.objects.create(
        company=company,
        employee=employee,
        authorized_by=user,
        reason=reason[:200],
        code_hash=_exception_code_hash(employee.pk, code),
        expires_at=expires,
    )
    return auth, code


class ExceptionProvider:
    """Consome (uso único) uma autorização de exceção a partir do código informado no tablet."""

    method = "authorized_exception"

    def verify(self, *, device, employee, payload) -> IdentificationResult:
        code = payload.get("code")
        if not isinstance(code, str) or len(code) != 8 or not (code.isascii() and code.isdigit()):
            raise IdentificationRejected({"identification": "Código de exceção inválido ou expirado."})
        now = timezone.now()
        auth = (
            ExceptionAuthorization.objects.select_for_update(no_key=True)
            .filter(
                employee=employee,
                company_id=device.company_id,
                code_hash=_exception_code_hash(employee.pk, code),
                consumed_at__isnull=True,
                expires_at__gt=now,
            )
            .first()
        )
        if auth is None:
            raise IdentificationRejected({"identification": "Código de exceção inválido ou expirado."})
        auth.consumed_at = now
        auth.save(update_fields=["consumed_at"])
        return IdentificationResult(self.method, str(auth.pk))


# ---------- Retenção ----------


def purge_inactive(*, days: int, dry_run: bool = False) -> int:
    """Exclui templates de funcionários inativos há pelo menos `days` dias. Não há prazo padrão (jurídico)."""
    limit = timezone.now() - datetime.timedelta(days=days)
    templates = BiometricTemplate.objects.filter(status=TemplateStatus.ACTIVE).filter(
        Q(employee__is_active=False, employee__inactivated_at__lte=limit)
    )
    count = templates.count()
    if not dry_run:
        for template in templates:
            with transaction.atomic():
                employee = Employee.objects.select_for_update(no_key=True).get(pk=template.employee_id)
                if not employee.is_active and employee.inactivated_at and employee.inactivated_at <= limit:
                    delete_template(template, user=None, reason="retention_purge")
    return count


@transaction.atomic
def reserve_exception_attempt(*, device, employee=None):
    """Executar antes da transação de marcação: recusa não devolve a cota.

    Conta inclusive códigos malformados; alternar matrícula não renova a cota do
    aparelho, nem alternar aparelhos renova a do funcionário.
    """
    now = timezone.now()
    scopes = [f"device:{device.pk}"]
    if employee is not None:
        scopes.append(f"employee:{employee.pk}")
    allowed = True
    for scope in sorted(scopes):
        ExceptionBudget.objects.get_or_create(scope=scope, defaults={"window_started_at": now})
        budget = ExceptionBudget.objects.select_for_update(no_key=True).get(pk=scope)
        if (now - budget.window_started_at).total_seconds() >= 60:
            budget.window_started_at, budget.count = now, 0
        if budget.count >= 10:
            allowed = False
        else:
            budget.count += 1
            budget.save(update_fields=["window_started_at", "count"])
    return allowed


@transaction.atomic
def refund_exception_attempt(*, device, employee=None):
    """Devolve a cota de uma tentativa que terminou em marcação gravada (sucesso legítimo)."""
    scopes = [f"device:{device.pk}"]
    if employee is not None:
        scopes.append(f"employee:{employee.pk}")
    for scope in sorted(scopes):
        budget = ExceptionBudget.objects.select_for_update(no_key=True).filter(pk=scope).first()
        if budget is not None and budget.count > 0:
            budget.count -= 1
            budget.save(update_fields=["count"])
