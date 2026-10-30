import datetime as dt
import uuid

import pytest
from django.utils import timezone

from apps.availability.models import AvailabilitySettings, AvailabilityUpdate
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Sector, Unit
from apps.timeclock import services as tc
from apps.timeclock.models import TimeRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a):
    company = tenant_a.company
    unit = Unit.objects.create(company=company, name="Centro")
    other = Unit.objects.create(company=company, name="Filial")
    caixa = Sector.objects.create(company=company, unit=unit, name="Caixa")
    maria = Employee.objects.create(company=company, registration="1", full_name="Maria")
    ops.assign_unit(maria, company, unit, caixa, dt.date(2020, 1, 1))
    joao = Employee.objects.create(company=company, registration="2", full_name="João")
    ops.assign_unit(joao, company, other, None, dt.date(2020, 1, 1))
    maria.access_user = tenant_a.users["employee"]
    maria.save()
    tenant_a.memberships["manager"].scope_units.add(unit)
    device = Device.objects.create(company=company, unit=unit, name="Tablet")
    code, _ = device_services.new_activation_code(device)
    device, _ = device_services.activate(code)
    # Módulo opcional e desligado por padrão: os cenários abaixo partem dele ligado.
    AvailabilitySettings.objects.create(company=company, enabled=True)
    return tenant_a, unit, caixa, maria, joao, device


def url(tenant, suffix=""):
    return f"/api/companies/{tenant.company.pk}/availability/{suffix}"


def test_painel_por_unidade_e_setor_com_escopo(world, tenant_b):
    tenant, unit, caixa, maria, joao, _ = world
    manager = tenant.client("manager")
    r = manager.post(
        url(tenant), {"employee_id": maria.pk, "status": "busy", "note": "Atendendo"}, format="json"
    )
    assert r.status_code == 201
    board = manager.get(url(tenant)).json()
    assert len(board["groups"]) == 1  # gestor só vê a sua unidade
    group = board["groups"][0]
    assert group["unit"]["name"] == "Centro" and group["sector"]["name"] == "Caixa"
    assert group["counts"]["busy"] == 1 and group["employees"][0]["freshness"] == "confirmed"
    assert "não altera" in board["notice"]
    assert (
        manager.post(url(tenant), {"employee_id": joao.pk, "status": "busy"}, format="json").status_code
        == 404
    )
    admin = tenant.client("company_admin").get(url(tenant)).json()
    assert {g["unit"]["name"] for g in admin["groups"]} == {"Centro", "Filial"}
    assert (
        tenant.client("company_admin")
        .get(url(tenant), {"sector": caixa.pk})
        .json()["groups"][0]["counts"]["busy"]
        == 1
    )
    assert tenant_b.client("company_admin").get(url(tenant)).status_code == 404
    assert tenant.client("employee").get(url(tenant)).status_code == 403


def test_desatualizado_e_vencido(world):
    tenant, _, _, maria, _, _ = world
    admin = tenant.client("company_admin")
    admin.post(url(tenant), {"employee_id": maria.pk, "status": "available"}, format="json")
    AvailabilityUpdate.objects.filter(employee=maria).update(set_at=timezone.now() - dt.timedelta(hours=3))
    item = admin.get(url(tenant)).json()["groups"][0]["employees"][0]
    assert item["freshness"] == "stale" and item["status"] == "available"
    admin.post(
        url(tenant), {"employee_id": maria.pk, "status": "on_break", "expires_minutes": 1}, format="json"
    )
    AvailabilityUpdate.objects.filter(employee=maria, status="on_break").update(
        expires_at=timezone.now() - dt.timedelta(minutes=1)
    )
    item = admin.get(url(tenant)).json()["groups"][0]["employees"][0]
    assert item["freshness"] == "expired" and item["status"] == "unknown"
    assert (
        admin.patch(url(tenant, "settings/"), {"stale_after_minutes": 600}, format="json").status_code == 200
    )
    assert len(admin.get(url(tenant, f"employees/{maria.pk}/")).json()) == 2


def test_disponibilidade_nao_toca_no_ponto_e_indicio_e_so_leitura(world):
    tenant, _, _, maria, _, device = world
    tc._insert(
        device,
        maria,
        uuid.uuid4(),
        "",
        None,
        tc.IdentificationResult("registration"),
        occurred_at=timezone.now() - dt.timedelta(minutes=30),
    )
    before = TimeRecord.objects.count()
    tenant.client("company_admin").post(
        url(tenant), {"employee_id": maria.pk, "status": "unavailable"}, format="json"
    )
    assert TimeRecord.objects.count() == before
    item = tenant.client("company_admin").get(url(tenant)).json()["groups"][0]["employees"][0]
    assert item["punch_hint"]["likely_present"] is True and item["status"] == "unavailable"


def test_funcionario_informa_o_proprio_estado(world):
    tenant, *_ = world
    employee = tenant.client("employee")
    r = employee.post(
        f"/api/companies/{tenant.company.pk}/me/availability/", {"status": "external"}, format="json"
    )
    assert r.status_code == 201 and r.json()["source"] == "employee"
    assert employee.get(f"/api/companies/{tenant.company.pk}/me/availability/").json()["status"] == "external"
    for bad in (
        {"status": "x"},
        {"status": "busy", "note": "x" * 141},
        {"status": "busy", "expires_minutes": 0},
    ):
        assert (
            employee.post(
                f"/api/companies/{tenant.company.pk}/me/availability/", bad, format="json"
            ).status_code
            == 400
        )


def test_modulo_desligado_recusa_escrita_e_historico_mas_o_painel_mostra_so_o_ponto(world):
    tenant, unit, caixa, maria, joao, device = world
    admin = tenant.client("company_admin")
    AvailabilityUpdate.objects.create(
        company=tenant.company,
        employee=maria,
        status="busy",
        source="manager",
        set_by=tenant.users["manager"],
    )
    assert admin.get(url(tenant)).json()["availability_enabled"] is True
    assert admin.patch(url(tenant, "settings/"), {"enabled": False}, format="json").json()["enabled"] is False
    me = f"/api/companies/{tenant.company.pk}/me/availability/"
    for call in (
        admin.post(url(tenant), {"employee_id": maria.pk, "status": "busy"}, format="json"),
        admin.get(url(tenant, f"employees/{maria.pk}/")),
        tenant.client("employee").get(me),
        tenant.client("employee").post(me, {"status": "busy"}, format="json"),
    ):
        assert call.status_code == 403 and call.json()["code"] == "module_disabled"
    # O painel segue servindo o indício de ponto, mas sem os estados informados.
    board = admin.get(url(tenant)).json()
    assert board["availability_enabled"] is False
    people = [e for g in board["groups"] for e in g["employees"]]
    assert people and all(e["status"] == "unknown" for e in people)
    # Qualquer membro sabe se o módulo está ligado; só o administrador muda.
    assert tenant.client("employee").get(url(tenant, "settings/")).json()["enabled"] is False
    assert (
        tenant.client("manager").patch(url(tenant, "settings/"), {"enabled": True}, format="json").status_code
        == 403
    )
    assert admin.patch(url(tenant, "settings/"), {"enabled": "sim"}, format="json").status_code == 400
    assert AvailabilityUpdate.objects.filter(employee=maria).count() == 1  # histórico preservado
    assert admin.patch(url(tenant, "settings/"), {"enabled": True}, format="json").json()["enabled"] is True
    assert [
        e["status"]
        for g in admin.get(url(tenant)).json()["groups"]
        for e in g["employees"]
        if e["employee"]["id"] == maria.pk
    ] == ["busy"]


def test_empresa_nova_nasce_sem_o_modulo(tenant_b):
    admin = tenant_b.client("company_admin")
    base = f"/api/companies/{tenant_b.company.pk}/availability/"
    assert admin.get(base + "settings/").json()["enabled"] is False
    assert admin.get(base).json()["availability_enabled"] is False
