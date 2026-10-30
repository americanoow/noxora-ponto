from django.conf import settings
from django.db import models
from django.db.models import Q


class BiometricConsent(models.Model):
    """Registro de que o funcionário concordou com o tratamento biométrico (versão da política).

    A base legal definitiva (LGPD art. 11) depende de validação jurídica. Revogar apaga o template.
    """

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="biometric_consents"
    )
    policy_version = models.CharField(max_length=32)
    evidence_ref = models.CharField(
        max_length=200, blank=True
    )  # p.ex. nº do termo assinado; sem dado biométrico
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee"],
                condition=Q(revoked_at__isnull=True),
                name="uniq_active_biometric_consent",
            )
        ]


class TemplateStatus(models.TextChoices):
    ACTIVE = "active", "Ativo"
    DELETED = "deleted", "Excluído"


class BiometricTemplate(models.Model):
    """Template biométrico CRIPTOGRAFADO. Nenhuma API devolve este conteúdo; imagens nunca são guardadas."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="biometric_templates"
    )
    status = models.CharField(max_length=8, choices=TemplateStatus.choices, default=TemplateStatus.ACTIVE)
    engine = models.CharField(max_length=40)
    engine_version = models.CharField(max_length=20)
    key_id = models.CharField(max_length=40)
    nonce = models.BinaryField(max_length=12, blank=True)
    ciphertext = models.BinaryField(blank=True)
    quality = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    delete_reason = models.CharField(max_length=60, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee"], condition=Q(status="active"), name="uniq_active_biometric_template"
            )
        ]

    def __repr__(self):  # nunca expor conteúdo em logs/tracebacks
        return f"<BiometricTemplate id={self.pk} status={self.status}>"


class Outcome(models.TextChoices):
    SUCCESS = "success", "Verificado"
    NO_MATCH = "no_match", "Rosto não confere"
    LIVENESS_FAILED = "liveness_failed", "Vivacidade reprovada"
    POOR_QUALITY = "poor_quality", "Qualidade insuficiente"
    NO_TEMPLATE = "no_template", "Sem cadastro facial"
    NO_CONSENT = "no_consent", "Sem consentimento"
    LOCKED = "locked", "Bloqueado por tentativas"
    ENGINE_UNAVAILABLE = "engine_unavailable", "Motor indisponível"


class VerificationAttempt(models.Model):
    """Resultado de uma verificação facial 1:1. Não guarda imagem nem template."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    unit = models.ForeignKey("operations.Unit", on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="verification_attempts"
    )
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    engine = models.CharField(max_length=40, blank=True)
    engine_version = models.CharField(max_length=20, blank=True)
    score = models.FloatField(null=True, blank=True)
    liveness = models.CharField(max_length=14, blank=True)
    liveness_method = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # só em sucesso
    consumed_at = models.DateTimeField(null=True, blank=True)  # uso único

    class Meta:
        indexes = [models.Index(fields=["employee", "-created_at"])]


class LivenessChallenge(models.Model):
    """Desafio de movimento emitido pelo servidor para UM tablet: sequência imprevisível e uso único.

    Sem ele não há prova de vivacidade: um vídeo gravado antes não conhece a sequência pedida agora."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, related_name="+")
    steps = models.JSONField()  # ["center", "left", "right", ...]
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["device", "-created_at"])]


class ExceptionAuthorization(models.Model):
    """Autorização de marcação por exceção (sem face), dada por pessoa autorizada. Curta e de uso único."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey(
        "operations.Employee", on_delete=models.PROTECT, related_name="exception_auths"
    )
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=200)
    code_hash = models.CharField(max_length=64)  # SHA-256 do código de 8 dígitos; o código só aparece uma vez
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)


class ExceptionBudget(models.Model):
    """Cota compartilhada por processos, sem código ou imagem."""

    scope = models.CharField(max_length=80, primary_key=True)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
