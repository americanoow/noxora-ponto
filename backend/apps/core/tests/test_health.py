from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
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
def test_ready_retorna_503_sem_banco_e_nao_vaza_erro(client):
    with mock.patch("apps.core.views.connection.cursor", side_effect=OperationalError("senha=segredo")):
        r = client.get("/api/ready/")
    assert r.status_code == 503
    assert r.json()["database"] == "falha"
    assert "segredo" not in r.content.decode()


@pytest.mark.django_db
def test_user_modelo_usa_email():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    u = User.objects.create_user("Teste@Exemplo.com", "senha-longa-123")
    assert u.email == "teste@exemplo.com"
    assert User.USERNAME_FIELD == "email"
