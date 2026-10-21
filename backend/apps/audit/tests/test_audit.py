import pytest

from apps.audit import services
from apps.audit.models import AppendOnlyError, AuditLog

pytestmark = pytest.mark.django_db


def test_registro_nao_pode_ser_alterado_nem_apagado():
    log = services.record(None, "teste.evento", actor_email="a@a.test")
    log.action = "outro"
    with pytest.raises(AppendOnlyError):
        log.save()
    with pytest.raises(AppendOnlyError):
        log.delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().update(action="x")


def test_metadados_sensiveis_sao_descartados():
    log = services.record(None, "teste", senha="x", password="y", token="z", Biometria="b", motivo="ok")
    assert log.metadata == {"motivo": "ok"}


def test_limpeza_recursiva_e_upsert_bloqueado():
    log = services.record(
        None,
        "teste",
        nested={
            "token": "segredo",
            "items": [{"Authorization": "segredo", "Cookie": "segredo", "motivo": "ok"}],
        },
    )
    assert log.metadata == {"nested": {"items": [{"motivo": "ok"}]}}
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.bulk_create(
            [AuditLog(pk=log.pk, action="alterado")],
            update_conflicts=True,
            update_fields=["action"],
            unique_fields=["id"],
        )
    log.refresh_from_db()
    assert log.action == "teste"
