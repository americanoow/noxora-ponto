import time

import pytest
from django.contrib.sessions.models import Session
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.notifications import services as outbox
from apps.notifications.models import OutboundEmail
from conftest import PASSWORD, make_user

pytestmark = pytest.mark.django_db


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    client.defaults["HTTP_X_CSRFTOKEN"] = token
    return client


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login/", {"email": email, "password": password}, format="json")


def test_login_valido_retorna_vinculos(tenant_a):
    client = csrf_client()
    r = login(client, "company_admin@a.test")
    assert r.status_code == 200
    assert r.json()["memberships"][0]["company_id"] == tenant_a.company.pk
    assert client.get("/api/auth/me/").status_code == 200


def test_login_exige_csrf(tenant_a):
    client = APIClient(enforce_csrf_checks=True)
    assert login(client, "company_admin@a.test").status_code == 403


def test_login_email_sem_distincao_de_caixa(tenant_a):
    assert login(csrf_client(), "Company_Admin@A.TEST").status_code == 200


def test_login_invalido_nao_distingue_causa_e_e_auditado(tenant_a):
    r1 = login(csrf_client(), "company_admin@a.test", "errada-errada-1")
    r2 = login(csrf_client(), "naoexiste@a.test", "errada-errada-1")
    assert r1.status_code == r2.status_code == 400
    assert r1.json() == r2.json()
    assert AuditLog.objects.filter(action="auth.login_failed").count() == 2
    assert "errada" not in str(list(AuditLog.objects.values_list("metadata", flat=True)))


def test_usuario_inativo_nao_entra(tenant_a):
    user = tenant_a.users["employee"]
    user.is_active = False
    user.save()
    assert login(csrf_client(), user.email).status_code == 400


def test_limite_de_tentativas_de_login(tenant_a):
    client = csrf_client()
    codes = [login(client, "company_admin@a.test", "errada-errada-1").status_code for _ in range(12)]
    assert codes[:10] == [400] * 10
    assert 429 in codes[10:]


def test_logout_encerra_a_sessao(tenant_a):
    client = csrf_client()
    login(client, "company_admin@a.test")
    # o Django rotaciona o token CSRF no login: o cliente precisa buscar um novo
    assert client.post("/api/auth/logout/").status_code == 403
    client.defaults["HTTP_X_CSRFTOKEN"] = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.get("/api/auth/me/").status_code == 403


def test_sessao_expirada_por_inatividade_deixa_de_autorizar(tenant_a):
    client = tenant_a.client("company_admin")
    assert client.get("/api/auth/me/").status_code == 200
    Session.objects.update(expire_date=timezone.now() - timezone.timedelta(seconds=1))
    assert client.get("/api/auth/me/").status_code == 403


def test_sessao_expirada_por_duracao_absoluta(tenant_a, settings):
    settings.SESSION_ABSOLUTE_TIMEOUT = 60
    client = csrf_client()
    login(client, "company_admin@a.test")
    session = client.session
    session["login_at"] = time.time() - 120
    session.save()
    assert client.get("/api/auth/me/").status_code == 403


def test_troca_de_senha_encerra_outras_sessoes(tenant_a):
    client = tenant_a.client("employee")
    assert client.get("/api/auth/me/").status_code == 200
    user = tenant_a.users["employee"]
    user.set_password("outra-senha-forte-99")
    user.save()
    assert client.get("/api/auth/me/").status_code == 403


def test_recuperacao_de_acesso_fluxo_completo(tenant_a):
    client = csrf_client()
    r = client.post("/api/auth/password-reset/", {"email": "employee@a.test"}, format="json")
    assert r.status_code == 202
    assert mail.outbox == []  # a requisição só enfileira
    assert outbox.process()["sent"] == 1
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    uid = body.split("uid=")[1].split("&")[0]
    token = body.split("token=")[1].split()[0]
    payload = {"uid": uid, "token": token, "new_password": "nova-senha-forte-77"}
    assert client.post("/api/auth/password-reset/confirm/", payload, format="json").status_code == 200
    assert login(csrf_client(), "employee@a.test", "nova-senha-forte-77").status_code == 200
    # token de uso único: a troca do hash o invalida
    assert client.post("/api/auth/password-reset/confirm/", payload, format="json").status_code == 400


def test_recuperacao_nao_revela_cadastro_e_ignora_inativos(tenant_a):
    client = csrf_client()
    r1 = client.post("/api/auth/password-reset/", {"email": "naoexiste@x.test"}, format="json")
    inativo = tenant_a.users["manager"]
    inativo.is_active = False
    inativo.save()
    r2 = client.post("/api/auth/password-reset/", {"email": inativo.email}, format="json")
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()
    assert mail.outbox == []


def test_recuperacao_rejeita_senha_fraca_e_token_invalido(tenant_a):
    client = csrf_client()
    client.post("/api/auth/password-reset/", {"email": "employee@a.test"}, format="json")
    outbox.process()
    body = mail.outbox[0].body
    uid = body.split("uid=")[1].split("&")[0]
    token = body.split("token=")[1].split()[0]
    fraca = client.post(
        "/api/auth/password-reset/confirm/",
        {"uid": uid, "token": token, "new_password": "123"},
        format="json",
    )
    assert fraca.status_code == 400
    ruim = client.post(
        "/api/auth/password-reset/confirm/",
        {"uid": uid, "token": "token-falso", "new_password": "nova-senha-forte-77"},
        format="json",
    )
    assert ruim.status_code == 400


def test_usuario_convidado_nao_loga_sem_definir_senha(db):
    user = make_user("novo@x.test")
    user.set_unusable_password()
    user.save()
    assert login(csrf_client(), "novo@x.test", "").status_code == 400


def test_reset_concorrente_nao_sobrescreve_senha(tenant_a, monkeypatch):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from apps.accounts.models import User

    user = tenant_a.users["employee"]
    token = default_token_generator.make_token(user)
    original_check = default_token_generator.check_token

    def competing_reset(snapshot, supplied):
        valid = original_check(snapshot, supplied)
        concurrent = User.objects.get(pk=user.pk)
        concurrent.set_password("senha-do-primeiro-reset-99")
        concurrent.save(update_fields=["password"])
        return valid

    monkeypatch.setattr(default_token_generator, "check_token", competing_reset)
    response = csrf_client().post(
        "/api/auth/password-reset/confirm/",
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": token,
            "new_password": "senha-do-segundo-reset-88",
        },
        format="json",
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password("senha-do-primeiro-reset-99")
    assert not AuditLog.objects.filter(action="auth.password_reset_confirmed").exists()


def test_falha_smtp_nao_enumera_nem_expoe_segredos(tenant_a, monkeypatch, caplog):
    from smtplib import SMTPException

    def fail(*args, **kwargs):
        raise SMTPException("token-ultrassecreto")

    monkeypatch.setattr("apps.notifications.services.send_mail", fail)
    client = csrf_client()
    known = client.post("/api/auth/password-reset/", {"email": "employee@a.test"}, format="json")
    unknown = client.post("/api/auth/password-reset/", {"email": "unknown@a.test"}, format="json")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert outbox.process()["retry"] == 1
    item = OutboundEmail.objects.get()
    assert item.status == "queued" and item.last_error == "SMTPException"
    assert "token-ultrassecreto" not in caplog.text and "token" not in item.last_error


@pytest.mark.parametrize("path", ["password-reset/", "password-reset/confirm/"])
def test_reset_exige_csrf(path):
    client = APIClient(enforce_csrf_checks=True)
    assert client.post("/api/auth/" + path, {}, format="json").status_code == 403


def test_login_rotaciona_chave_da_sessao(tenant_a):
    client = csrf_client()
    session = client.session
    session["antes"] = True
    session.save()
    old_key = session.session_key
    assert login(client, "employee@a.test").status_code == 200
    assert client.session.session_key != old_key
    assert not Session.objects.filter(session_key=old_key).exists()


def test_sessao_sem_marca_login_e_invalida(tenant_a):
    client = tenant_a.client("employee")
    session = client.session
    del session["login_at"]
    session.save()
    assert client.get("/api/auth/me/").status_code == 403


def test_mutacoes_empresa_exigem_csrf(tenant_a):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(tenant_a.users["company_admin"])
    base = f"/api/companies/{tenant_a.company.pk}/"
    assert client.post(base + "members/", {}, format="json").status_code == 403
    assert (
        client.patch(base + f"members/{tenant_a.memberships['employee'].pk}/", {}, format="json").status_code
        == 403
    )
    assert client.patch(base, {}, format="json").status_code == 403


def test_reset_expirado_e_usuario_inativo_rejeitados(tenant_a, monkeypatch):
    from datetime import timedelta

    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    user = tenant_a.users["employee"]
    token = default_token_generator.make_token(user)
    payload = {
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": token,
        "new_password": "senha-forte-nova-99",
    }
    client = csrf_client()
    now = default_token_generator._now()
    with monkeypatch.context() as patch:
        patch.setattr(default_token_generator, "_now", lambda: now + timedelta(hours=2))
        assert client.post("/api/auth/password-reset/confirm/", payload, format="json").status_code == 400
    user.is_active = False
    user.save()
    assert client.post("/api/auth/password-reset/confirm/", payload, format="json").status_code == 400


def _login_com_origin(origin):
    """Simula o navegador: o Vite (5173) faz proxy e o Origin original chega ao Django."""
    client = APIClient(enforce_csrf_checks=True, HTTP_ORIGIN=origin)
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    client.defaults["HTTP_X_CSRFTOKEN"] = token
    return client.post(
        "/api/auth/login/", {"email": "company_admin@a.test", "password": PASSWORD}, format="json"
    )


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_login_com_origin_do_painel_em_desenvolvimento(tenant_a, origin):
    assert _login_com_origin(origin).status_code == 200


def test_login_com_origin_desconhecida_e_recusado(tenant_a):
    r = _login_com_origin("http://site-malicioso.test")
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]
