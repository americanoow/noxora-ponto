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


# ---------- Operações sensíveis: limite de tentativas e login recente ----------


def test_confirmar_mfa_tem_espera_crescente_e_nao_vaza_o_codigo(tenant_a):
    client = tenant_a.client("company_admin")
    client.post("/api/auth/mfa/")
    for _ in range(3):
        assert client.put("/api/auth/mfa/", {"code": "000000"}, format="json").status_code == 400
    blocked = client.put("/api/auth/mfa/", {"code": "000000"}, format="json")
    assert blocked.status_code == 429 and blocked.json()["code"] == "throttled"
    assert AuditLog.objects.filter(action="auth.mfa_confirm_failed").count() == 3
    # O código certo também espera: durante a espera não há como adivinhar em rajada.
    from apps.accounts import sensitive

    wait = sensitive.wait_seconds(tenant_a.users["company_admin"], "mfa_confirm")
    assert 0 < wait <= 30


def test_espera_aumenta_com_mais_falhas_e_zera_no_acerto(tenant_a, monkeypatch):
    from apps.accounts import sensitive

    user = tenant_a.users["company_admin"]
    clock = [1000.0]
    monkeypatch.setattr(sensitive.time, "time", lambda: clock[0])
    for _ in range(3):
        sensitive.register_failure(user, "mfa_disable")
    assert sensitive.wait_seconds(user, "mfa_disable") == 30
    for _ in range(2):
        sensitive.register_failure(user, "mfa_disable")
    assert sensitive.wait_seconds(user, "mfa_disable") == 300
    for _ in range(3):
        sensitive.register_failure(user, "mfa_disable")
    assert sensitive.wait_seconds(user, "mfa_disable") == 1800
    clock[0] += 1801
    assert sensitive.wait_seconds(user, "mfa_disable") == 0
    sensitive.reset(user, "mfa_disable")
    sensitive.register_failure(user, "mfa_disable")
    assert sensitive.wait_seconds(user, "mfa_disable") == 0  # recomeça do zero


def test_desativar_mfa_limita_tentativas_de_senha_e_codigo(tenant_a):
    client = tenant_a.client("company_admin")
    secret, recovery = enable(client)
    for _ in range(3):
        r = client.delete("/api/auth/mfa/", {"password": "errada", "code": recovery[0]}, format="json")
        assert r.status_code == 400
    r = client.delete("/api/auth/mfa/", {"password": PASSWORD, "code": recovery[0]}, format="json")
    assert r.status_code == 429  # nem a senha certa passa durante a espera


def test_operacoes_de_mfa_exigem_login_recente_e_a_senha_o_renova(tenant_a, monkeypatch):
    import time

    from apps.accounts import sensitive

    client = tenant_a.client("company_admin")
    session = client.session
    session["login_at"] = time.time() - sensitive.REAUTH_SECONDS - 5
    session.save()
    r = client.post("/api/auth/mfa/")
    assert r.status_code == 403 and r.json()["code"] == "reauth_required"
    assert client.put("/api/auth/mfa/", {"code": "123456"}, format="json").status_code == 403
    assert (
        client.delete("/api/auth/mfa/", {"password": PASSWORD, "code": "1"}, format="json").status_code == 403
    )
    assert client.post("/api/auth/reauth/", {"password": "errada"}, format="json").status_code == 400
    assert client.post("/api/auth/reauth/", {"password": PASSWORD}, format="json").status_code == 204
    assert client.post("/api/auth/mfa/").status_code == 200
    assert AuditLog.objects.filter(action="auth.reauth").exists()


def test_reautenticacao_tambem_tem_limite_de_tentativas(tenant_a):
    client = tenant_a.client("company_admin")
    for _ in range(3):
        assert client.post("/api/auth/reauth/", {"password": "errada"}, format="json").status_code == 400
    assert client.post("/api/auth/reauth/", {"password": PASSWORD}, format="json").status_code == 429


def test_login_por_senha_tem_espera_por_conta_sem_revelar_cadastro(tenant_a):
    from apps.accounts import sensitive

    email = tenant_a.users["company_admin"].email
    c = csrf_client()
    for _ in range(10):
        r = c.post("/api/auth/login/", {"email": email, "password": "errada-123456"}, format="json")
        assert r.status_code in (400, 429)
    # Mesmo de outro IP (sem o limite por IP), a conta está em espera; nem a senha certa entra agora.
    sensitive_wait = sensitive.wait_seconds(sensitive.email_subject(email), "login")
    assert 0 < sensitive_wait <= 60
    r = csrf_client().post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")
    assert r.status_code == 429
    # E-mail inexistente é contado do mesmo jeito (a resposta não revela se a conta existe).
    ghost = "ninguem@a.test"
    for _ in range(10):
        sensitive.register_failure(sensitive.email_subject(ghost), "login", sensitive.LOGIN_STEPS)
    assert sensitive.wait_seconds(sensitive.email_subject(ghost.upper()), "login") > 0


def test_codigo_do_segundo_fator_conta_falhas_por_conta_entre_logins(tenant_a):
    from apps.accounts import sensitive

    user = tenant_a.users["company_admin"]
    enable(tenant_a.client("company_admin"))
    for _ in range(10):
        sensitive.register_failure(user, "mfa_login", sensitive.MFA_LOGIN_STEPS)
    c = csrf_client()
    c.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    c.credentials(HTTP_X_CSRFTOKEN=c.get("/api/auth/csrf/").json()["csrfToken"])
    assert c.post("/api/auth/mfa/verify/", {"code": "123456"}, format="json").status_code == 429
