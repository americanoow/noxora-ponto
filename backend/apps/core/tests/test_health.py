from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient


@pytest.fixture
def client():
    return APIClient()


def test_health_ok(client):
    r = client.get("/api/health/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_ok(client):
    r = client.get("/api/ready/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_ready_retorna_503_sem_banco_e_nao_vaza_erro(client, caplog):
    with mock.patch("apps.core.views.connection.cursor", side_effect=OperationalError("senha=segredo")):
        r = client.get("/api/ready/")
    assert r.status_code == 503
    assert r.json()["database"] == "falha"
    assert "segredo" not in r.content.decode()
    assert "segredo" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("path", ["/api/health/", "/api/ready/"])
def test_endpoints_rejeitam_escrita(client, path):
    assert client.post(path, {}, format="json").status_code == 405


@pytest.mark.django_db
def test_user_modelo_usa_email():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    u = User.objects.create_user("Teste@Exemplo.com", "senha-longa-123")
    assert u.email == "teste@exemplo.com"
    assert User.USERNAME_FIELD == "email"
