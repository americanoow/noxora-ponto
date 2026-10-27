import datetime as dt

import pytest
from django.core import mail
from django.utils import timezone

from apps.notifications import services
from apps.notifications.models import OutboundEmail

pytestmark = pytest.mark.django_db


def test_corpo_cifrado_e_apagado_apos_envio():
    item = services.enqueue(to="a@x.test", subject="Oi", body="link secreto token=XYZ", kind="teste")
    assert b"XYZ" not in bytes(item.body_ciphertext)
    assert services.process()["sent"] == 1
    item.refresh_from_db()
    assert (
        item.status == "sent" and bytes(item.body_ciphertext) == b"" and mail.outbox[0].body.endswith("XYZ")
    )


def test_novas_tentativas_e_desistencia(monkeypatch):
    def fail(*a, **k):
        raise OSError("rede")

    monkeypatch.setattr("apps.notifications.services.send_mail", fail)
    item = services.enqueue(to="a@x.test", subject="Oi", body="x", kind="teste", ttl=dt.timedelta(days=2))
    for _ in range(len(services.BACKOFF_MINUTES)):
        OutboundEmail.objects.filter(pk=item.pk).update(next_attempt_at=timezone.now())
        services.process()
    item.refresh_from_db()
    assert item.status == "failed" and item.attempts == 5 and bytes(item.body_ciphertext) == b""


def test_expira_sem_enviar():
    item = services.enqueue(to="a@x.test", subject="Oi", body="x", kind="teste")
    OutboundEmail.objects.filter(pk=item.pk).update(expires_at=timezone.now() - dt.timedelta(seconds=1))
    assert services.process()["expired"] == 1 and mail.outbox == []


def test_chave_trocada_nao_envia(settings):
    services.enqueue(to="a@x.test", subject="Oi", body="x", kind="teste")
    settings.SECRET_KEY = "outra-chave-" * 5
    assert services.process()["failed"] == 1 and mail.outbox == []
