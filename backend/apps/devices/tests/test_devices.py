import datetime

import pytest
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.devices import services
from apps.devices.models import ActivationCode, Device, DeviceCredential
from apps.operations import services as ops
from apps.operations.models import Employee, Unit

pytestmark = pytest.mark.django_db


def curl(company, path=""):
    return f"/api/companies/{company.pk}/devices/{path}"


def make_unit(company, name="Centro"):
    return Unit.objects.create(company=company, name=name)


def create_device(tenant, unit=None, name="Tablet 1"):
    unit = unit or make_unit(tenant.company)
    r = tenant.client("company_admin").post(
        curl(tenant.company), {"name": name, "unit": unit.pk}, format="json"
    )
    assert r.status_code == 201, r.content
    return r.json()


def activate(code, **extra):
    return APIClient().post("/api/device/activate/", {"code": code, **extra}, format="json")


def device_client(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
    return client


def active_device(tenant, unit=None):
    created = create_device(tenant, unit)
    body = activate(created["activation_code"]).json()
    return Device.objects.get(pk=created["id"]), body["token"]


# ---------- Cadastro e permissões do painel ----------


def test_admin_cria_dispositivo_e_codigo_aparece_uma_vez_e_so_o_hash_e_guardado(tenant_a):
    created = create_device(tenant_a)
    code = created["activation_code"]
    assert len(code.replace("-", "")) == 10 and created["status"] == "pending"
    assert code.replace("-", "") not in str(list(ActivationCode.objects.values()))
    detail = tenant_a.client("company_admin").get(curl(tenant_a.company, f"{created['id']}/")).json()
    assert "activation_code" not in detail
    assert code not in str(list(AuditLog.objects.values()))


def test_funcionario_nao_acessa_e_gestor_so_le(tenant_a):
    unit = make_unit(tenant_a.company)
    created = create_device(tenant_a, unit)
    assert tenant_a.client("employee").get(curl(tenant_a.company)).status_code == 403
    manager = tenant_a.client("manager")
    assert manager.get(curl(tenant_a.company)).json() == []  # sem escopo
    tenant_a.memberships["manager"].scope_units.add(unit)
    assert len(manager.get(curl(tenant_a.company)).json()) == 1
    assert (
        manager.post(curl(tenant_a.company), {"name": "x", "unit": unit.pk}, format="json").status_code == 403
    )
    for action in ("revoke/", "activation-code/"):
        assert manager.post(curl(tenant_a.company, f"{created['id']}/{action}")).status_code == 403
    assert manager.get(curl(tenant_a.company, f"{created['id']}/locations/")).status_code == 403
    assert (
        manager.patch(curl(tenant_a.company, f"{created['id']}/"), {"name": "x"}, format="json").status_code
        == 403
    )


def test_dispositivo_de_outra_empresa_e_invisivel_em_todos_os_endpoints(tenant_a, tenant_b):
    created = create_device(tenant_b)
    admin_a = tenant_a.client("company_admin")
    did = created["id"]
    assert admin_a.get(curl(tenant_a.company, f"{did}/")).status_code == 404
    assert admin_a.patch(curl(tenant_a.company, f"{did}/"), {"name": "x"}, format="json").status_code == 404
    assert admin_a.post(curl(tenant_a.company, f"{did}/revoke/")).status_code == 404
    assert admin_a.post(curl(tenant_a.company, f"{did}/activation-code/")).status_code == 404
    assert admin_a.get(curl(tenant_a.company, f"{did}/locations/")).status_code == 404
    assert admin_a.get(curl(tenant_a.company, f"{did}/")).status_code == 404
    assert admin_a.get(curl(tenant_b.company, f"{did}/")).status_code == 404  # pela URL da outra empresa
    assert admin_a.get(curl(tenant_a.company)).json() == []


def test_unidade_de_outra_empresa_ou_inativa_e_rejeitada(tenant_a, tenant_b):
    unit_b = make_unit(tenant_b.company)
    admin = tenant_a.client("company_admin")
    assert (
        admin.post(curl(tenant_a.company), {"name": "x", "unit": unit_b.pk}, format="json").status_code == 400
    )
    inactive = make_unit(tenant_a.company, "Inativa")
    inactive.is_active = False
    inactive.save()
    assert (
        admin.post(curl(tenant_a.company), {"name": "x", "unit": inactive.pk}, format="json").status_code
        == 400
    )
    created = create_device(tenant_a)
    assert (
        admin.patch(
            curl(tenant_a.company, f"{created['id']}/"), {"unit": unit_b.pk}, format="json"
        ).status_code
        == 400
    )
    assert Device.objects.count() == 1


def test_patch_ignora_campos_protegidos(tenant_a, tenant_b):
    created = create_device(tenant_a)
    r = tenant_a.client("company_admin").patch(
        curl(tenant_a.company, f"{created['id']}/"),
        {"status": "active", "company": tenant_b.company.pk, "app_version": "9", "name": "Novo"},
        format="json",
    )
    assert r.status_code == 200
    device = Device.objects.get(pk=created["id"])
    assert (
        device.status == "pending" and device.company_id == tenant_a.company.pk and device.app_version == ""
    )
    assert device.name == "Novo"


# ---------- Ativação ----------


def test_ativacao_com_codigo_valido_entrega_credencial_e_escopo(tenant_a):
    created = create_device(tenant_a)
    r = activate(created["activation_code"].lower(), app_version="1.0.0", hardware_hint="SM-T500")
    assert r.status_code == 201
    body = r.json()
    assert body["company"]["id"] == tenant_a.company.pk and body["unit"]["id"] == created["unit"]
    device = Device.objects.get(pk=created["id"])
    assert device.status == "active" and device.app_version == "1.0.0" and device.last_seen_at
    assert body["token"] not in str(list(DeviceCredential.objects.values()))  # só o hash fica no banco


def test_codigo_e_de_uso_unico_e_invalido_nao_distingue_causa(tenant_a):
    created = create_device(tenant_a)
    assert activate(created["activation_code"]).status_code == 201
    reuse = activate(created["activation_code"])
    wrong = activate("AAAAA-BBBBB")
    short = activate("123")
    assert reuse.status_code == wrong.status_code == short.status_code == 400
    assert reuse.json() == wrong.json() == short.json()


def test_codigo_expirado_e_recusado(tenant_a):
    created = create_device(tenant_a)
    ActivationCode.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert activate(created["activation_code"]).status_code == 400
    assert Device.objects.get(pk=created["id"]).status == "pending"


def test_ativacao_bloqueada_com_empresa_ou_unidade_inativa(tenant_a):
    created = create_device(tenant_a)
    Unit.objects.filter(pk=created["unit"]).update(is_active=False)
    assert activate(created["activation_code"]).status_code == 400
    Unit.objects.filter(pk=created["unit"]).update(is_active=True)
    tenant_a.company.is_active = False
    tenant_a.company.save()
    assert activate(created["activation_code"]).status_code == 400


def test_ativacao_tem_limite_de_tentativas(tenant_a):
    codes = [activate("AAAAA-BBBBB").status_code for _ in range(12)]
    assert codes[:10] == [400] * 10 and 429 in codes[10:]


def test_ativacao_nao_exige_sessao_nem_csrf(tenant_a):
    created = create_device(tenant_a)
    client = APIClient(enforce_csrf_checks=True)
    assert (
        client.post("/api/device/activate/", {"code": created["activation_code"]}, format="json").status_code
        == 201
    )


def test_novo_codigo_invalida_o_anterior(tenant_a):
    created = create_device(tenant_a)
    device = Device.objects.get(pk=created["id"])
    new_code, _ = services.new_activation_code(device)
    assert activate(created["activation_code"]).status_code == 400
    assert activate(new_code).status_code == 201


# ---------- Autenticação do dispositivo e escopo ----------


def test_endpoints_do_tablet_exigem_credencial_valida(tenant_a):
    device, token = active_device(tenant_a)
    anon = APIClient()
    for method, path in (
        ("get", "me/"),
        ("post", "heartbeat/"),
        ("post", "rotate-credential/"),
        ("get", "employees/?registration=1"),
    ):
        assert getattr(anon, method)(f"/api/device/{path}").status_code in (401, 403)
    for bad in (
        "Device",
        "Device x",
        "Device 1.",
        f"Device {token}x",
        "Device 99999.abc",
        "Device " + "9" * 500,
        "Bearer " + token,
        "Device \xff",
    ):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=bad)
        assert client.get("/api/device/me/").status_code in (401, 403), bad
    assert device_client(token).get("/api/device/me/").status_code == 200


def test_sessao_de_usuario_nao_serve_de_credencial_de_dispositivo_e_vice_versa(tenant_a):
    _, token = active_device(tenant_a)
    admin = tenant_a.client("company_admin")
    assert admin.get("/api/device/me/").status_code in (401, 403)
    assert device_client(token).get("/api/auth/me/").status_code == 403
    assert device_client(token).get(f"/api/companies/{tenant_a.company.pk}/devices/").status_code == 403


def test_revogacao_barra_o_acesso_online_imediatamente_e_audita_sem_inundar(tenant_a):
    device, token = active_device(tenant_a)
    tablet = device_client(token)
    assert tablet.post("/api/device/heartbeat/").status_code == 200
    assert (
        tenant_a.client("company_admin").post(curl(tenant_a.company, f"{device.pk}/revoke/")).status_code
        == 200
    )
    for _ in range(3):
        r = tablet.post("/api/device/heartbeat/")
        assert r.status_code == 401 and r.json()["detail"] == "Dispositivo revogado."
    assert tablet.get("/api/device/employees/?registration=1").status_code == 401
    assert (
        AuditLog.objects.filter(action="device.revoked_access_attempt", company=tenant_a.company).count() == 1
    )
    assert Device.objects.get(pk=device.pk).status == "revoked"


def test_credencial_expirada_e_recusada(tenant_a):
    _, token = active_device(tenant_a)
    DeviceCredential.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert device_client(token).get("/api/device/me/").status_code == 401


def test_empresa_inativa_derruba_o_tablet(tenant_a):
    _, token = active_device(tenant_a)
    tenant_a.company.is_active = False
    tenant_a.company.save()
    assert device_client(token).get("/api/device/me/").status_code == 403


def test_heartbeat_atualiza_versao_e_conectividade(tenant_a):
    device, token = active_device(tenant_a)
    tablet = device_client(token)
    tablet.post("/api/device/heartbeat/", {"app_version": "2.1.0"}, format="json")
    admin = tenant_a.client("company_admin")
    row = admin.get(curl(tenant_a.company, f"{device.pk}/")).json()
    assert row["app_version"] == "2.1.0" and row["connectivity"] == "online"
    Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now() - datetime.timedelta(hours=1))
    assert admin.get(curl(tenant_a.company, f"{device.pk}/")).json()["connectivity"] == "stale"


def test_dispositivo_nunca_aceita_escopo_do_cliente(tenant_a, tenant_b):
    device, token = active_device(tenant_a)
    me = (
        device_client(token)
        .post(
            "/api/device/heartbeat/",
            {"company": tenant_b.company.pk, "unit": 999, "app_version": "1"},
            format="json",
        )
        .json()
    )
    assert me["company"]["id"] == tenant_a.company.pk and me["unit"]["id"] == device.unit_id


def test_consulta_de_matricula_so_enxerga_a_propria_unidade(tenant_a, tenant_b):
    unit = make_unit(tenant_a.company, "Centro")
    other = make_unit(tenant_a.company, "Norte")
    unit_b = make_unit(tenant_b.company, "Centro")
    here = Employee.objects.create(company=tenant_a.company, registration="1", full_name="Aqui", cpf="")
    away = Employee.objects.create(company=tenant_a.company, registration="2", full_name="Outra Unidade")
    inactive = Employee.objects.create(
        company=tenant_a.company, registration="3", full_name="Inativo", is_active=False
    )
    foreign = Employee.objects.create(company=tenant_b.company, registration="1", full_name="Outra Empresa")
    start = datetime.date(2020, 1, 1)
    for emp, u in ((here, unit), (away, other), (inactive, unit)):
        ops.assign_unit(emp, tenant_a.company, u, None, start)
    ops.assign_unit(foreign, tenant_b.company, unit_b, None, start)
    _, token = active_device(tenant_a, unit)
    tablet = device_client(token)
    ok = tablet.get("/api/device/employees/?registration=1")
    assert ok.status_code == 200 and ok.json() == {"id": here.pk, "registration": "1", "full_name": "Aqui"}
    assert "cpf" not in ok.json()
    for reg in ("2", "3", "999"):
        assert tablet.get(f"/api/device/employees/?registration={reg}").status_code == 404
    assert tablet.get("/api/device/employees/").status_code == 400  # sem listagem geral


# ---------- Credencial: rotação e renovação ----------


def test_rotacao_emite_nova_credencial_e_a_antiga_vale_so_pela_janela(tenant_a):
    _, old = active_device(tenant_a)
    new = device_client(old).post("/api/device/rotate-credential/").json()["token"]
    assert new != old
    assert device_client(new).get("/api/device/me/").status_code == 200
    assert device_client(old).get("/api/device/me/").status_code == 200  # janela de tolerância
    DeviceCredential.objects.filter(pk=old.split(".")[0]).update(
        expires_at=timezone.now() - datetime.timedelta(seconds=1)
    )
    assert device_client(old).get("/api/device/me/").status_code == 401
    assert device_client(new).get("/api/device/me/").status_code == 200


def test_renovacao_derruba_a_credencial_atual_e_o_novo_codigo_reativa(tenant_a):
    device, old = active_device(tenant_a)
    r = tenant_a.client("company_admin").post(curl(tenant_a.company, f"{device.pk}/activation-code/"))
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert device_client(old).get("/api/device/me/").status_code == 401
    assert activate(r.json()["activation_code"]).status_code == 201
    assert Device.objects.get(pk=device.pk).status == "active"


def test_dispositivo_revogado_pode_ser_reativado_so_por_novo_codigo(tenant_a):
    device, token = active_device(tenant_a)
    admin = tenant_a.client("company_admin")
    admin.post(curl(tenant_a.company, f"{device.pk}/revoke/"))
    assert device_client(token).get("/api/device/me/").status_code == 401
    code = admin.post(curl(tenant_a.company, f"{device.pk}/activation-code/")).json()["activation_code"]
    new = activate(code).json()["token"]
    assert device_client(new).get("/api/device/me/").status_code == 200
    assert device_client(token).get("/api/device/me/").status_code == 401


# ---------- Localização ----------

LOC = {
    "latitude": "-23.550520",
    "longitude": "-46.633308",
    "accuracy_m": 25,
    "captured_at": "2026-10-21T12:00:00Z",
}


def test_localizacao_desligada_nao_grava_nada(tenant_a):
    device, token = active_device(tenant_a)
    assert device_client(token).post("/api/device/location/", LOC, format="json").status_code == 409
    assert device.locations.count() == 0


def test_ligar_coleta_exige_justificativa_e_desligar_limpa(tenant_a):
    device, token = active_device(tenant_a)
    admin = tenant_a.client("company_admin")
    path = curl(tenant_a.company, f"{device.pk}/")
    assert admin.patch(path, {"collect_location": True}, format="json").status_code == 400
    assert (
        admin.patch(
            path, {"collect_location": True, "location_justification": "  "}, format="json"
        ).status_code
        == 400
    )
    ok = admin.patch(
        path,
        {"collect_location": True, "location_justification": "Unidade externa, sem rede fixa"},
        format="json",
    )
    assert ok.status_code == 200
    tablet = device_client(token)
    assert tablet.post("/api/device/location/", LOC, format="json").status_code == 201
    assert device.locations.count() == 1
    locations = admin.get(curl(tenant_a.company, f"{device.pk}/locations/")).json()
    assert len(locations) == 1 and locations[0]["latitude"] == "-23.550520"
    admin.patch(path, {"collect_location": False}, format="json")
    device.refresh_from_db()
    assert device.location_justification == "" and not device.collect_location
    assert tablet.post("/api/device/location/", LOC, format="json").status_code == 409


@pytest.mark.parametrize(
    "patch",
    [
        {"latitude": "91"},
        {"latitude": "x"},
        {"longitude": "-181"},
        {"accuracy_m": -1},
        {"captured_at": "ontem"},
    ],
)
def test_localizacao_invalida_e_rejeitada(tenant_a, patch):
    device, token = active_device(tenant_a)
    tenant_a.client("company_admin").patch(
        curl(tenant_a.company, f"{device.pk}/"),
        {"collect_location": True, "location_justification": "motivo"},
        format="json",
    )
    assert (
        device_client(token).post("/api/device/location/", {**LOC, **patch}, format="json").status_code == 400
    )
    assert device.locations.count() == 0


def test_banco_recusa_coleta_sem_justificativa(tenant_a):
    device, _ = active_device(tenant_a)
    device.collect_location = True
    device.location_justification = ""
    with pytest.raises(IntegrityError):
        device.save()


# ---------- Auditoria ----------


def test_eventos_sao_auditados_sem_segredos(tenant_a):
    device, token = active_device(tenant_a)
    admin = tenant_a.client("company_admin")
    device_client(token).post("/api/device/rotate-credential/")
    admin.post(curl(tenant_a.company, f"{device.pk}/revoke/"))
    actions = set(AuditLog.objects.filter(company=tenant_a.company).values_list("action", flat=True))
    assert {"device.created", "device.activated", "device.credential_rotated", "device.revoked"} <= actions
    dump = str(list(AuditLog.objects.values()))
    assert token.split(".")[1] not in dump
