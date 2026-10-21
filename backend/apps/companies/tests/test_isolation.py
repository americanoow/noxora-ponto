import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.companies.models import Company, Membership

pytestmark = pytest.mark.django_db


def members_url(company):
    return f"/api/companies/{company.pk}/members/"


def member_url(company, membership):
    return f"/api/companies/{company.pk}/members/{membership.pk}/"


def test_anonimo_nao_acessa_nada(tenant_a):
    client = APIClient()
    for url in (
        "/api/companies/",
        members_url(tenant_a.company),
        f"/api/companies/{tenant_a.company.pk}/audit/",
    ):
        assert client.get(url).status_code == 403


@pytest.mark.parametrize("role", ["company_admin", "manager", "employee"])
def test_empresa_de_outro_cliente_e_invisivel_para_todos_os_papeis(tenant_a, tenant_b, role):
    client = tenant_a.client(role)
    company_b = tenant_b.company
    assert client.get(f"/api/companies/{company_b.pk}/").status_code == 404
    assert client.get(members_url(company_b)).status_code == 404
    assert (
        client.post(
            members_url(company_b), {"email": "x@x.test", "role": "employee"}, format="json"
        ).status_code
        == 404
    )
    assert client.get(f"/api/companies/{company_b.pk}/audit/").status_code == 404
    assert (
        client.patch(
            member_url(company_b, tenant_b.memberships["employee"]), {"role": "manager"}, format="json"
        ).status_code
        == 404
    )


def test_listagem_de_empresas_mostra_so_as_proprias(tenant_a, tenant_b):
    ids = [c["id"] for c in tenant_a.client("employee").get("/api/companies/").json()]
    assert ids == [tenant_a.company.pk]


def test_id_de_vinculo_de_outra_empresa_nao_e_alcancado_pela_propria_url(tenant_a, tenant_b):
    admin_a = tenant_a.client("company_admin")
    alvo = tenant_b.memberships["employee"]
    r = admin_a.patch(member_url(tenant_a.company, alvo), {"role": "company_admin"}, format="json")
    assert r.status_code == 404
    alvo.refresh_from_db()
    assert alvo.role == "employee"


def test_listagem_de_membros_nao_vaza_outra_empresa(tenant_a, tenant_b):
    emails = {m["email"] for m in tenant_a.client("company_admin").get(members_url(tenant_a.company)).json()}
    assert emails == {u.email for u in tenant_a.users.values()}


def test_gestor_e_funcionario_nao_gerenciam_membros(tenant_a):
    for role in ("manager", "employee"):
        client = tenant_a.client(role)
        assert client.get(members_url(tenant_a.company)).status_code == 403
        r = client.post(
            members_url(tenant_a.company), {"email": "n@a.test", "role": "employee"}, format="json"
        )
        assert r.status_code == 403
        r = client.patch(
            member_url(tenant_a.company, tenant_a.memberships["employee"]), {"role": "manager"}, format="json"
        )
        assert r.status_code == 403
        assert client.get(f"/api/companies/{tenant_a.company.pk}/audit/").status_code == 403


def test_usuario_nao_aumenta_a_propria_permissao(tenant_a):
    for role in ("manager", "employee", "company_admin"):
        client = tenant_a.client(role)
        r = client.patch(
            member_url(tenant_a.company, tenant_a.memberships[role]), {"role": "company_admin"}, format="json"
        )
        assert r.status_code == 403
    tenant_a.memberships["manager"].refresh_from_db()
    assert tenant_a.memberships["manager"].role == "manager"


def test_payload_nao_concede_admin_da_plataforma(tenant_a):
    admin = tenant_a.client("company_admin")
    r = admin.post(
        members_url(tenant_a.company),
        {"email": "novo@a.test", "role": "manager", "is_platform_admin": True, "is_staff": True},
        format="json",
    )
    assert r.status_code == 201
    from apps.accounts.models import User

    novo = User.objects.get(email="novo@a.test")
    assert not novo.is_platform_admin and not novo.is_staff
    assert (
        admin.post(
            members_url(tenant_a.company), {"email": "z@a.test", "role": "platform_admin"}, format="json"
        ).status_code
        == 400
    )


def test_admin_cria_membro_e_convite_e_enviado(tenant_a, django_capture_on_commit_callbacks):
    from django.core import mail

    with django_capture_on_commit_callbacks(execute=True):
        r = tenant_a.client("company_admin").post(
            members_url(tenant_a.company),
            {"email": "Novo@A.test", "name": "Novo", "role": "employee"},
            format="json",
        )
    assert r.status_code == 201
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["novo@a.test"]
    assert AuditLog.objects.filter(action="member.created", company=tenant_a.company).exists()


def test_usuario_existente_em_outra_empresa_nao_tem_dados_alterados(tenant_a, tenant_b):
    alvo = tenant_b.users["employee"]
    antes = alvo.password
    r = tenant_a.client("company_admin").post(
        members_url(tenant_a.company),
        {"email": alvo.email, "name": "Outro Nome", "role": "manager"},
        format="json",
    )
    assert r.status_code == 201
    alvo.refresh_from_db()
    assert alvo.password == antes and alvo.first_name == "employee"
    assert alvo.memberships.count() == 2


def test_vinculo_duplicado_retorna_409(tenant_a):
    r = tenant_a.client("company_admin").post(
        members_url(tenant_a.company), {"email": "manager@a.test", "role": "employee"}, format="json"
    )
    assert r.status_code == 409


def test_vinculo_desativado_perde_acesso_imediatamente(tenant_a):
    manager = tenant_a.client("manager")
    assert manager.get(f"/api/companies/{tenant_a.company.pk}/").status_code == 200
    tenant_a.client("company_admin").patch(
        member_url(tenant_a.company, tenant_a.memberships["manager"]), {"is_active": False}, format="json"
    )
    assert manager.get(f"/api/companies/{tenant_a.company.pk}/").status_code == 404


def test_empresa_inativa_bloqueia_membros(tenant_a, platform_admin):
    Company.objects.filter(pk=tenant_a.company.pk).update(is_active=False)
    assert tenant_a.client("company_admin").get(f"/api/companies/{tenant_a.company.pk}/").status_code == 404
    assert tenant_a.client("employee").get("/api/companies/").json() == []


def test_usuario_com_vinculos_em_duas_empresas_tem_papeis_independentes(tenant_a, tenant_b):
    user = tenant_a.users["manager"]
    Membership.objects.create(user=user, company=tenant_b.company, role="employee")
    client = tenant_a.client("manager")
    assert client.get(members_url(tenant_b.company)).status_code == 403  # empregado em B
    assert client.get(f"/api/companies/{tenant_b.company.pk}/").status_code == 200


def test_auditoria_da_empresa_nao_mostra_eventos_de_outra(tenant_a, tenant_b):
    tenant_b.client("company_admin").post(
        members_url(tenant_b.company), {"email": "q@b.test", "role": "employee"}, format="json"
    )
    logs = tenant_a.client("company_admin").get(f"/api/companies/{tenant_a.company.pk}/audit/").json()
    assert all(entry["action"] != "member.created" for entry in logs)


# --- Administração da plataforma ---


def test_so_plataforma_cria_empresa(tenant_a, platform_admin):
    payload = {"name": "Nova SA", "admin_email": "dono@nova.test"}
    assert tenant_a.client("company_admin").post("/api/companies/", payload, format="json").status_code == 403
    from conftest import login_client

    r = login_client(platform_admin).post("/api/companies/", payload, format="json")
    assert r.status_code == 201
    nova = Company.objects.get(name="Nova SA")
    assert nova.memberships.get().role == "company_admin"


def test_plataforma_nao_le_membros_e_acesso_a_empresa_e_auditado(tenant_a, platform_admin):
    from conftest import login_client

    client = login_client(platform_admin)
    assert client.get(members_url(tenant_a.company)).status_code == 403
    assert AuditLog.objects.filter(action="platform.company_access", company=tenant_a.company).exists()


def test_plataforma_le_auditoria_da_empresa_com_registro_do_acesso(tenant_a, platform_admin):
    from conftest import login_client

    r = login_client(platform_admin).get(f"/api/companies/{tenant_a.company.pk}/audit/")
    assert r.status_code == 200
    assert AuditLog.objects.filter(action="platform.company_access", actor=platform_admin).exists()


def test_so_plataforma_altera_empresa(tenant_a, platform_admin):
    from conftest import login_client

    url = f"/api/companies/{tenant_a.company.pk}/"
    assert tenant_a.client("company_admin").patch(url, {"is_active": False}, format="json").status_code == 403
    assert login_client(platform_admin).patch(url, {"is_active": False}, format="json").status_code == 200
    tenant_a.company.refresh_from_db()
    assert tenant_a.company.is_active is False


def test_convite_nao_revela_nome_global(tenant_a, tenant_b):
    client = tenant_a.client("company_admin")
    response = client.post(
        members_url(tenant_a.company),
        {
            "email": tenant_b.users["employee"].email,
            "name": "Nome local",
            "role": "employee",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Nome local"
    listed = client.get(members_url(tenant_a.company)).json()
    assert next(m for m in listed if m["id"] == response.json()["id"])["name"] == "Nome local"
    assert tenant_b.users["employee"].first_name == "employee"


def test_plataforma_com_vinculo_continua_sem_acesso_operacional(tenant_a, platform_admin):
    from conftest import login_client

    Membership.objects.create(user=platform_admin, company=tenant_a.company, role="company_admin")
    client = login_client(platform_admin)
    url = members_url(tenant_a.company)
    assert client.get(url).status_code == 403
    assert client.post(url, {"email": "x@x.test", "role": "employee"}, format="json").status_code == 403
    assert (
        client.patch(
            member_url(tenant_a.company, tenant_a.memberships["employee"]), {"role": "manager"}, format="json"
        ).status_code
        == 403
    )
    assert AuditLog.objects.filter(action="platform.company_access", actor=platform_admin).count() == 3


def test_patch_nao_move_vinculo_nem_altera_identidade(tenant_a, tenant_b):
    member = tenant_a.memberships["employee"]
    user = tenant_a.users["employee"]
    response = tenant_a.client("company_admin").patch(
        member_url(tenant_a.company, member),
        {
            "company": tenant_b.company.pk,
            "user": tenant_b.users["company_admin"].pk,
            "email": "invadido@x.test",
            "password": "senha-injetada",
            "is_superuser": True,
            "is_platform_admin": True,
            "role": "manager",
        },
        format="json",
    )
    assert response.status_code == 200
    member.refresh_from_db()
    user.refresh_from_db()
    assert member.company == tenant_a.company and member.user == user
    assert user.email == "employee@a.test" and not user.is_superuser and not user.is_platform_admin


@pytest.mark.parametrize("disabled", ["user", "membership", "company"])
def test_revogacao_bloqueia_todos_endpoints_empresa(tenant_a, disabled):
    client = tenant_a.client("company_admin")
    target = {
        "user": tenant_a.users["company_admin"],
        "membership": tenant_a.memberships["company_admin"],
        "company": tenant_a.company,
    }[disabled]
    target.is_active = False
    target.save()
    expected = 403 if disabled == "user" else 404
    base = f"/api/companies/{tenant_a.company.pk}/"
    assert client.get(base).status_code == expected
    assert client.get(base + "audit/").status_code == expected
    assert client.get(base + "members/").status_code == expected
    assert (
        client.post(base + "members/", {"email": "x@x.test", "role": "employee"}, format="json").status_code
        == expected
    )
    assert (
        client.patch(
            member_url(tenant_a.company, tenant_a.memberships["employee"]), {"role": "manager"}, format="json"
        ).status_code
        == expected
    )


def test_falha_auditoria_reverte_alteracao(tenant_a, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Falha simulada")

    monkeypatch.setattr("apps.companies.views.audit.record", fail)
    with pytest.raises(RuntimeError, match="simulada"):
        tenant_a.client("company_admin").patch(
            member_url(tenant_a.company, tenant_a.memberships["employee"]), {"role": "manager"}, format="json"
        )
    tenant_a.memberships["employee"].refresh_from_db()
    assert tenant_a.memberships["employee"].role == "employee"


def test_corrida_criacao_usuario_recupera_identidade_existente(tenant_b, monkeypatch):
    from django.db import IntegrityError

    from apps.accounts.models import User
    from apps.accounts.services import get_or_invite_user

    target = tenant_b.users["employee"]
    manager = User.objects
    original_filter = manager.filter
    calls = 0

    def concurrent_filter(**kwargs):
        nonlocal calls
        calls += 1
        return manager.none() if calls == 1 else original_filter(**kwargs)

    def duplicate(*args, **kwargs):
        raise IntegrityError("Conflito simulado")

    monkeypatch.setattr(manager, "filter", concurrent_filter)
    monkeypatch.setattr(manager, "create_user", duplicate)
    user, created = get_or_invite_user(target.email)
    assert user == target and created is False
