import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts import totp
from apps.audit.models import AuditLog
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_vetor_rfc6238():
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30, digits=8) == "94287082"
    assert totp.code_at(secret, 1111111109 // 30, digits=8) == "07081804"


def csrf_client():
    c = APIClient(enforce_csrf_checks=True)
    token = c.get("/api/auth/csrf/").json()["csrfToken"]
    c.credentials(HTTP_X_CSRFTOKEN=token)
    return c


def enable(client):
    secret = client.post("/api/auth/mfa/").json()["secret"]
    codes = client.put(
        "/api/auth/mfa/", {"code": totp.code_at(secret, int(__import__("time").time() // 30))}, format="json"
    )
    assert codes.status_code == 200
    return secret, codes.json()["recovery_codes"]


def test_fluxo_completo_com_segundo_fator(tenant_a):
    user = tenant_a.users["company_admin"]
    secret, recovery = enable(tenant_a.client("company_admin"))
    assert len(recovery) == 10
    c = csrf_client()
    r = c.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert r.json() == {"mfa_required": True}
    assert c.get("/api/auth/me/").status_code == 403  # sem sessão ainda
    token = c.get("/api/auth/csrf/").json()["csrfToken"]
    c.credentials(HTTP_X_CSRFTOKEN=token)
    assert c.post("/api/auth/mfa/verify/", {"code": "000000"}, format="json").status_code == 400
    import time

    good = totp.code_at(secret, int(time.time() // 30) + 1)
    r = c.post("/api/auth/mfa/verify/", {"code": good}, format="json")
    assert r.status_code == 200 and r.json()["mfa_enabled"] is True
    assert c.get("/api/auth/me/").status_code == 200
    # O mesmo código não serve duas vezes.
    c2 = csrf_client()
    c2.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    c2.credentials(HTTP_X_CSRFTOKEN=c2.get("/api/auth/csrf/").json()["csrfToken"])
    assert c2.post("/api/auth/mfa/verify/", {"code": good}, format="json").status_code == 400
    # Código de recuperação: uso único.
    assert c2.post("/api/auth/mfa/verify/", {"code": recovery[0]}, format="json").status_code == 200
    c3 = csrf_client()
    c3.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    c3.credentials(HTTP_X_CSRFTOKEN=c3.get("/api/auth/csrf/").json()["csrfToken"])
    assert c3.post("/api/auth/mfa/verify/", {"code": recovery[0]}, format="json").status_code == 400
    assert AuditLog.objects.filter(action="auth.mfa_failed").exists()


def test_tentativas_esgotadas_exigem_novo_login(tenant_a):
    enable(tenant_a.client("company_admin"))
    c = csrf_client()
    c.post(
        "/api/auth/login/",
        {"email": tenant_a.users["company_admin"].email, "password": PASSWORD},
        format="json",
    )
    c.credentials(HTTP_X_CSRFTOKEN=c.get("/api/auth/csrf/").json()["csrfToken"])
    for _ in range(5):
        c.post("/api/auth/mfa/verify/", {"code": "123456"}, format="json")
    r = c.post("/api/auth/mfa/verify/", {"code": "123456"}, format="json")
    assert r.json()["detail"] == "Faça login novamente."


def test_desativar_exige_senha_e_codigo_e_suporte(tenant_a):
    client = tenant_a.client("company_admin")
    secret, recovery = enable(client)
    assert client.post("/api/auth/mfa/").status_code == 400  # já ativo
    assert (
        client.delete(
            "/api/auth/mfa/", {"password": "errada", "code": recovery[1]}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.delete(
            "/api/auth/mfa/", {"password": PASSWORD, "code": recovery[1]}, format="json"
        ).status_code
        == 204
    )
    enable(client)
    call_command("reset_mfa", tenant_a.users["company_admin"].email, "--reason", "perdeu o celular")
    assert client.get("/api/auth/me/").json()["mfa_enabled"] is False
