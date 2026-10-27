from django.db import models


class EmailStatus(models.TextChoices):
    QUEUED = "queued", "Na fila"
    SENT = "sent", "Enviado"
    FAILED = "failed", "Falhou (desistiu)"
    EXPIRED = "expired", "Expirou sem envio"


class OutboundEmail(models.Model):
    """E-mail na fila (outbox). O corpo pode conter link de acesso: fica CIFRADO e é apagado após o envio
    ou expiração. Erros guardam só a classe da exceção (sem detalhes SMTP)."""

    kind = models.CharField(max_length=30)
    to = models.EmailField()
    subject = models.CharField(max_length=200)
    body_nonce = models.BinaryField(max_length=12, blank=True)
    body_ciphertext = models.BinaryField(blank=True)
    status = models.CharField(max_length=8, choices=EmailStatus.choices, default=EmailStatus.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField()
    last_error = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __repr__(self):
        return f"<OutboundEmail id={self.pk} status={self.status}>"
