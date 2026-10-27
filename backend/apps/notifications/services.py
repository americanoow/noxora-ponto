"""Fila de e-mails (D13 revisada): a requisição só enfileira; o envio acontece fora dela, com novas
tentativas. Reduz a diferença de tempo entre conta existente/inexistente e não perde e-mail por falha
momentânea de SMTP."""

import datetime as dt
import hashlib
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import EmailStatus, OutboundEmail

logger = logging.getLogger(__name__)
BACKOFF_MINUTES = [1, 5, 15, 60, 180]


def _key() -> bytes:
    return hashlib.sha256(b"noxora-outbox-v1:" + settings.SECRET_KEY.encode()).digest()


def _aad(email_id_hint: str) -> bytes:
    return f"noxora-outbox:{email_id_hint}".encode()


def enqueue(*, to: str, subject: str, body: str, kind: str, ttl: dt.timedelta = dt.timedelta(hours=1)):
    now = timezone.now()
    nonce = os.urandom(12)
    item = OutboundEmail.objects.create(
        kind=kind,
        to=to,
        subject=subject[:200],
        body_nonce=nonce,
        body_ciphertext=AESGCM(_key()).encrypt(nonce, body.encode(), _aad(to)),
        next_attempt_at=now,
        expires_at=now + ttl,
    )
    if settings.EMAIL_OUTBOX_SYNC:
        transaction.on_commit(lambda: process(limit=10))
    return item


def _wipe(item):
    item.body_nonce, item.body_ciphertext = b"", b""


def process(*, limit: int = 50) -> dict:
    """Envia os e-mails vencidos. Seguro com vários workers (`skip_locked`)."""
    counts = {"sent": 0, "retry": 0, "failed": 0, "expired": 0}
    now = timezone.now()
    with transaction.atomic():
        batch = list(
            OutboundEmail.objects.select_for_update(skip_locked=True)
            .filter(status=EmailStatus.QUEUED, next_attempt_at__lte=now)
            .order_by("next_attempt_at", "id")[:limit]
        )
        for item in batch:
            if item.expires_at <= now:
                item.status = EmailStatus.EXPIRED
                _wipe(item)
                counts["expired"] += 1
            else:
                try:
                    body = AESGCM(_key()).decrypt(
                        bytes(item.body_nonce), bytes(item.body_ciphertext), _aad(item.to)
                    )
                    send_mail(item.subject, body.decode(), None, [item.to])
                except InvalidTag:
                    item.status, item.last_error = EmailStatus.FAILED, "chave alterada"
                    _wipe(item)
                    counts["failed"] += 1
                except Exception as exc:  # noqa: BLE001 - nunca registrar detalhes (podem conter o corpo)
                    item.attempts += 1
                    item.last_error = type(exc).__name__[:100]
                    if item.attempts >= len(BACKOFF_MINUTES):
                        item.status = EmailStatus.FAILED
                        _wipe(item)
                        counts["failed"] += 1
                    else:
                        item.next_attempt_at = now + dt.timedelta(minutes=BACKOFF_MINUTES[item.attempts - 1])
                        counts["retry"] += 1
                    logger.warning(
                        "Falha no envio de e-mail", extra={"email_id": item.pk, "error": item.last_error}
                    )
                else:
                    item.status, item.sent_at = EmailStatus.SENT, now
                    item.attempts += 1
                    _wipe(item)
                    counts["sent"] += 1
            item.save()
    return counts


def stats() -> dict:
    from django.db.models import Count

    return dict(OutboundEmail.objects.values_list("status").annotate(n=Count("id")))
