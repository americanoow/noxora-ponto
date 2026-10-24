import datetime
import uuid

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Unit
from apps.timeclock import services
from apps.timeclock.models import NsrCounter, TimeRecord

pytestmark = pytest.mark.django_db

BATCH = "/api/device/punches/batch/"


def make_unit(company, name="Centro", tz="America/Sao_Paulo"):
    return Unit.objects.create(company=company, name=name, timezone=tz)


def make_device(company, unit, name="Tablet"):
    device = Device.objects.create(company=company, unit=unit, name=name)
    code, _ = device_services.new_activation_code(device)
    device, token = device_services.activate(code)
    Device.objects.filter(pk=device.pk).update(activated_at=timezone.now() - datetime.timedelta(days=2))
    return Device.objects.get(pk=device.pk), token


def tablet(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
    return client


def make_employee(
    company, unit, registration="1", name="Maria", active=True, start=datetime.date(2020, 1, 1)
):
    employee = Employee.objects.create(
        company=company, registration=registration, full_name=name, cpf="", is_active=active
    )
    if unit is not None:
        ops.assign_unit(employee, company, unit, None, start)
    return employee


def iso(moment):
    return moment.isoformat()


def ev(registration="1", ago=datetime.timedelta(minutes=10), offset=0, measured="now", **extra):
    """Evento da fila offline: horário original = agora − `ago`; desvio medido agora por padrão."""
    now = timezone.now()
    body = {
        "client_event_id": str(uuid.uuid4()),
        "registration": registration,
        "device_reported_at": iso(now - ago),
        "clock_offset_seconds": offset,
        "offset_measured_at": iso(now) if measured == "now" else measured,
    }
    body.update(extra)
    return body


def send(client, *events):
    return client.post(BATCH, {"events": list(events)}, format="json")


@pytest.fixture
def world(tenant_a):
    tenant_a.company.offline_policy = "registration_only"
    tenant_a.company.save()
    unit = make_unit(tenant_a.company)
    device, token = make_device(tenant_a.company, unit)
    employee = make_employee(tenant_a.company, unit)
    return tenant_a, unit, device, tablet(token), token, employee


# ---------- Política ----------


def test_politica_desligada_recusa_todos_e_nada_e_gravado(tenant_a):
    unit = make_unit(tenant_a.company)
    _, token = make_device(tenant_a.company, unit)
    make_employee(tenant_a.company, unit)
    r = send(tablet(token), ev(), ev())
    assert r.status_code == 200
    assert [x["reason"] for x in r.json()["results"]] == ["offline_not_allowed"] * 2
    assert TimeRecord.objects.count() == 0


# ---------- Caminho feliz, idempotência e lotes parciais ----------


def test_lote_confirma_na_ordem_com_horario_original_e_cadeia_integra(world):
    tenant, unit, device, client, _, employee = world
    events = [ev(ago=datetime.timedelta(minutes=m)) for m in (30, 20, 10)]
    r = send(client, *events)
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["status"] for x in results] == ["confirmed"] * 3
    assert [x["client_event_id"] for x in results] == [e["client_event_id"] for e in events]
    assert [x["record"]["nsr"] for x in results] == [1, 2, 3]
    assert all(x["flags"] == [] for x in results)
    records = list(TimeRecord.objects.order_by("nsr"))
    for record, event in zip(records, events, strict=True):
        assert record.offline is True and record.identification_method == "registration_offline"
        assert (
            abs(
                (
                    record.occurred_at - datetime.datetime.fromisoformat(event["device_reported_at"])
                ).total_seconds()
            )
            < 1
        )
        assert record.recorded_at > record.occurred_at  # recebimento posterior ao horário original
        assert record.clock_skew_seconds == 0 and record.sync_flags == []
    assert services.verify_unit_chain(unit) == []


def test_reenvio_do_mesmo_lote_nao_duplica_nem_consome_nsr(world):
    tenant, unit, _, client, _, _ = world
    events = [ev(), ev(), ev()]
    first = send(client, *events).json()["results"]
    again = send(client, *events)
    assert again.status_code == 200
    results = again.json()["results"]
    assert [x["status"] for x in results] == ["duplicate"] * 3
    assert [x["record"]["id"] for x in results] == [x["record"]["id"] for x in first]
    assert TimeRecord.objects.count() == 3 and NsrCounter.objects.get(unit=unit).last_nsr == 3
    assert services.verify_unit_chain(unit) == []


def test_evento_repetido_no_mesmo_lote_vira_duplicado(world):
    _, _, _, client, _, _ = world
    event = ev()
    results = send(client, event, event).json()["results"]
    assert [x["status"] for x in results] == ["confirmed", "duplicate"]
    assert results[0]["record"]["id"] == results[1]["record"]["id"]
    assert TimeRecord.objects.count() == 1


def test_lote_parcial_trata_cada_evento_e_mantem_a_ordem(world):
    _, unit, _, client, _, _ = world
    good1, good2 = ev(), ev()
    bad_uuid = ev(client_event_id="nao-e-uuid")
    unknown = ev(registration="999")
    r = send(client, good1, bad_uuid, unknown, "texto", 42, good2)
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["status"] for x in results] == [
        "confirmed",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "confirmed",
    ]
    assert [x.get("reason") for x in results[1:5]] == [
        "invalid",
        "unknown_registration",
        "invalid",
        "invalid",
    ]
    assert results[1]["client_event_id"] == "nao-e-uuid" and results[3]["client_event_id"] is None
    assert [x["record"]["nsr"] for x in (results[0], results[5])] == [1, 2]
    assert TimeRecord.objects.count() == 2
    assert services.verify_unit_chain(unit) == []


def test_eventos_invalidos(world):
    _, _, _, client, _, _ = world
    base = ev()
    bad = [
        {**base, "client_event_id": str(uuid.uuid4()), "device_reported_at": "ontem"},
        {**base, "client_event_id": str(uuid.uuid4()), "registration": ""},
        {**base, "client_event_id": str(uuid.uuid4()), "registration": "x" * 31},
        {**base, "client_event_id": str(uuid.uuid4()), "declared_kind": "almoco"},
        {**base, "client_event_id": str(uuid.uuid4()), "clock_offset_seconds": 10**9},
        {**base, "client_event_id": str(uuid.uuid4()), "clock_offset_seconds": "abc"},
        {k: v for k, v in base.items() if k != "device_reported_at"},
    ]
    results = send(client, *bad).json()["results"]
    assert [x["reason"] for x in results] == ["invalid"] * len(bad)
    assert TimeRecord.objects.count() == 0


def test_limites_do_lote(world, settings):
    _, _, _, client, _, _ = world
    for body in ({}, {"events": []}, {"events": "x"}, {"events": {"a": 1}}, {"events": None}):
        assert client.post(BATCH, body, format="json").status_code == 400, body
    assert send(client, *[ev() for _ in range(settings.OFFLINE_BATCH_MAX + 1)]).status_code == 400
    assert TimeRecord.objects.count() == 0
    assert send(client, *[ev() for _ in range(settings.OFFLINE_BATCH_MAX)]).status_code == 200
    assert TimeRecord.objects.count() == settings.OFFLINE_BATCH_MAX


# ---------- Horário e divergência de relógio ----------


def one(client, event):
    return send(client, event).json()["results"][0]


def test_sem_desvio_medido_grava_com_flag_clock_unverified(world):
    _, _, _, client, _, _ = world
    event = ev(offset=None, measured=None)
    result = one(client, event)
    assert result["status"] == "confirmed" and "clock_unverified" in result["flags"]
    record = TimeRecord.objects.get()
    assert (
        abs(
            (
                record.occurred_at - datetime.datetime.fromisoformat(event["device_reported_at"])
            ).total_seconds()
        )
        < 1
    )
    assert record.clock_skew_seconds is None


def test_desvio_corrige_o_horario_e_acima_de_30s_e_sinalizado(world):
    _, _, _, client, _, _ = world
    event = ev(offset=120)  # o aparelho estava 2 min atrasado em relação ao servidor
    result = one(client, event)
    assert result["status"] == "confirmed" and result["flags"] == ["clock_skew_large"]
    record = TimeRecord.objects.get()
    reported = datetime.datetime.fromisoformat(event["device_reported_at"])
    assert abs((record.occurred_at - (reported + datetime.timedelta(seconds=120))).total_seconds()) < 1
    assert record.clock_skew_seconds == -120  # aparelho − servidor
    small = one(client, ev(offset=20))
    assert small["flags"] == []


def test_desvio_defasado_e_sinalizado(world):
    _, _, _, client, _, _ = world
    old = iso(timezone.now() - datetime.timedelta(days=3))
    assert "clock_offset_stale" in one(client, ev(offset=5, measured=old))["flags"]
    assert "clock_offset_stale" in one(client, ev(offset=5, measured=None))["flags"]
    assert one(client, ev(offset=5))["flags"] == []


def test_horario_no_futuro_e_limitado_ao_recebimento(world):
    _, _, _, client, _, _ = world
    result = one(client, ev(ago=-datetime.timedelta(hours=1)))
    assert "time_in_future" in result["flags"]
    record = TimeRecord.objects.get()
    assert record.occurred_at <= record.recorded_at
    near = one(client, ev(ago=-datetime.timedelta(seconds=60)))  # dentro da tolerância
    assert near["status"] == "confirmed" and "time_in_future" not in near["flags"]
    assert TimeRecord.objects.count() == 2


def test_evento_antigo_demais_e_recusado_e_o_limite_aceita(world, settings):
    _, _, _, client, _, _ = world
    too_old = one(client, ev(ago=datetime.timedelta(days=settings.OFFLINE_MAX_AGE_DAYS + 1)))
    assert too_old["status"] == "rejected" and too_old["reason"] == "too_old"
    assert TimeRecord.objects.count() == 0
    ok = one(client, ev(ago=datetime.timedelta(days=settings.OFFLINE_MAX_AGE_DAYS - 1)))
    assert ok["status"] == "confirmed"


def test_horario_anterior_a_ativacao_do_tablet_e_sinalizado(world):
    tenant, unit, device, client, _, _ = world
    result = one(client, ev(ago=datetime.timedelta(days=5)))  # o tablet foi ativado há 2 dias
    assert result["status"] == "confirmed" and "before_device_activation" in result["flags"]


def test_data_local_usa_o_horario_corrigido_no_fuso_da_unidade(world):
    _, unit, _, client, _, _ = world
    day = (timezone.now() - datetime.timedelta(days=3)).date()
    reported = datetime.datetime(
        day.year, day.month, day.day, 2, 30, tzinfo=datetime.UTC
    )  # 23:30 do dia anterior (SP)
    event = ev(offset=0)
    event["device_reported_at"] = iso(reported)
    assert one(client, event)["status"] == "confirmed"
    record = TimeRecord.objects.get()
    assert record.occurred_local_date == day - datetime.timedelta(days=1)
    assert record.occurred_offset_minutes == -180
    assert services.verify_unit_chain(unit) == []


# ---------- Funcionário ----------


def test_funcionario_inativo_ou_sem_lotacao_e_aceito_e_sinalizado(world, tenant_b):
    tenant, unit, _, client, _, _ = world
    other_unit = make_unit(tenant.company, "Norte")
    make_employee(tenant.company, unit, "2", "Inativo", active=False)
    make_employee(tenant.company, other_unit, "3", "De Outra Unidade")
    make_employee(tenant.company, unit, "4", "Lotação Futura", start=datetime.date(2099, 1, 1))
    results = send(client, ev("2"), ev("3"), ev("4"), ev("1")).json()["results"]
    assert all(r["status"] == "confirmed" for r in results)
    assert "employee_inactive" in results[0]["flags"] and "not_assigned_to_unit" not in results[0]["flags"]
    assert "not_assigned_to_unit" in results[1]["flags"]
    assert "not_assigned_to_unit" in results[2]["flags"]
    assert results[3]["flags"] == []
    assert TimeRecord.objects.count() == 4


def test_matricula_de_outra_empresa_e_recusada(world, tenant_b):
    tenant, unit, _, client, _, _ = world
    unit_b = make_unit(tenant_b.company)
    make_employee(tenant_b.company, unit_b, "77", "Da Outra Empresa")
    result = one(client, ev("77"))
    assert result["status"] == "rejected" and result["reason"] == "unknown_registration"
    assert TimeRecord.objects.count() == 0


def test_corpo_nao_escolhe_empresa_unidade_nem_nsr(world, tenant_b):
    tenant, unit, device, client, _, _ = world
    other = make_unit(tenant_b.company)
    result = one(client, ev(company=tenant_b.company.pk, unit=other.pk, nsr=99, device=999))
    assert result["status"] == "confirmed" and result["record"]["nsr"] == 1
    record = TimeRecord.objects.get()
    assert (
        record.company_id == tenant.company.pk and record.unit_id == unit.pk and record.device_id == device.pk
    )


def test_identificacao_offline_so_por_matricula(world):
    _, _, _, client, _, _ = world
    assert (
        one(client, ev(identification={"method": "face", "verification_id": 1}))["reason"]
        == "unsupported_identification"
    )
    assert (
        one(client, ev(identification={"method": "authorized_exception", "code": "12345678"}))["reason"]
        == "unsupported_identification"
    )
    assert one(client, ev(identification="registration"))["reason"] == "invalid"  # formato: deve ser objeto
    assert one(client, ev(identification={"method": "registration"}))["status"] == "confirmed"
    assert TimeRecord.objects.count() == 1


# ---------- Credencial ----------


def test_dispositivo_revogado_ou_credencial_expirada_barra_o_lote(world):
    tenant, unit, device, client, token, _ = world
    event = ev()
    device_services.revoke(Device.objects.get(pk=device.pk))
    assert send(client, event).status_code == 401
    assert TimeRecord.objects.count() == 0


def test_credencial_expirada_barra_o_lote(world):
    from apps.devices.models import DeviceCredential

    _, _, _, client, _, _ = world
    DeviceCredential.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert send(client, ev()).status_code == 401
    assert TimeRecord.objects.count() == 0


def test_fila_preservada_e_aceita_apos_reativacao_do_mesmo_cadastro(world):
    tenant, unit, device, client, _, _ = world
    queue = [ev(ago=datetime.timedelta(minutes=m)) for m in (50, 40, 30)]
    device_services.revoke(Device.objects.get(pk=device.pk))
    assert send(client, *queue).status_code == 401
    code = device_services.reissue(Device.objects.get(pk=device.pk))
    _, new_token = device_services.activate(code)
    results = send(tablet(new_token), *queue).json()["results"]
    assert [x["status"] for x in results] == ["confirmed"] * 3
    assert TimeRecord.objects.count() == 3


def test_endpoint_exige_credencial_de_dispositivo(world):
    tenant, *_ = world
    body = {"events": [ev()]}
    assert APIClient().post(BATCH, body, format="json").status_code in (401, 403)
    assert tenant.client("company_admin").post(BATCH, body, format="json").status_code in (401, 403)
    assert TimeRecord.objects.count() == 0


def test_empresa_inativa_barra_o_lote(world):
    tenant, *_, client, _, _ = world
    tenant.company.is_active = False
    tenant.company.save()
    assert send(client, ev()).status_code == 403
    assert TimeRecord.objects.count() == 0


# ---------- Integração com o restante ----------


def test_marcacao_online_continua_a_sequencia_e_a_cadeia_mistura_online_e_offline(world):
    tenant, unit, device, client, _, _ = world
    online = client.post(
        "/api/device/punches/", {"registration": "1", "client_event_id": str(uuid.uuid4())}, format="json"
    )
    assert online.status_code == 201 and online.json()["record"]["nsr"] == 1
    offline = one(client, ev())
    assert offline["record"]["nsr"] == 2
    again = client.post(
        "/api/device/punches/", {"registration": "1", "client_event_id": str(uuid.uuid4())}, format="json"
    )
    assert again.json()["record"]["nsr"] == 3
    assert [r.offline for r in TimeRecord.objects.order_by("nsr")] == [False, True, False]
    assert services.verify_unit_chain(unit) == []


def test_nsr_segue_a_ordem_de_recebimento_nao_a_cronologica(world):
    _, _, _, client, _, _ = world
    recent, older = ev(ago=datetime.timedelta(minutes=5)), ev(ago=datetime.timedelta(hours=3))
    send(client, recent, older)
    first, second = TimeRecord.objects.order_by("nsr")
    assert first.occurred_at > second.occurred_at  # NSR 1 é o mais recente: ordem de gravação


def test_escopo_do_dispositivo_informa_politicas(world):
    _, _, _, client, _, _ = world
    me = client.get("/api/device/me/").json()
    assert me["offline_policy"] == "registration_only" and me["identification_mode"] == "registration"


def test_auditoria_resume_o_lote_sem_dados_pessoais(world):
    tenant, *_, client, _, _ = world
    send(client, ev(), ev("999"), ev())
    log = AuditLog.objects.get(action="device.offline_sync")
    assert log.metadata == {"confirmed": 2, "duplicate": 0, "rejected": 1}
    assert log.company_id == tenant.company.pk and log.actor_email.startswith("dispositivo:")
    assert "999" not in str(list(AuditLog.objects.values()))


def test_historico_expoe_flags_e_filtra_offline(world):
    tenant, unit, _, client, _, _ = world
    client.post(
        "/api/device/punches/", {"registration": "1", "client_event_id": str(uuid.uuid4())}, format="json"
    )
    send(client, ev(offset=None, measured=None))
    admin = tenant.client("company_admin")
    base = f"/api/companies/{tenant.company.pk}/time-records/"
    everything = admin.get(base).json()
    assert everything["count"] == 2
    offline_only = admin.get(base + "?offline=true").json()
    assert offline_only["count"] == 1
    assert offline_only["results"][0]["offline"] is True
    assert offline_only["results"][0]["sync_flags"] == ["clock_unverified"]
    assert admin.get(base + "?offline=false").json()["count"] == 1
    assert admin.get(base + "?offline=talvez").status_code == 400


def test_registros_offline_continuam_imutaveis(world):
    from apps.timeclock.models import AppendOnlyError

    _, _, _, client, _, _ = world
    send(client, ev())
    record = TimeRecord.objects.get()
    record.sync_flags = []
    with pytest.raises(AppendOnlyError):
        record.save()
    with pytest.raises(AppendOnlyError):
        TimeRecord.objects.all().update(sync_flags=["x"])


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Concorrência exige PostgreSQL real")
@pytest.mark.django_db(transaction=True)
def test_lotes_identicos_simultaneos_nao_duplicam(world):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    tenant, unit, device, _, token, _ = world
    events = [ev() for _ in range(6)]
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return send(tablet(token), *events).json()["results"]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        batches = [f.result(timeout=60) for f in futures]
    statuses = [x["status"] for batch in batches for x in batch]
    assert statuses.count("confirmed") == 6 and statuses.count("duplicate") == 6
    assert TimeRecord.objects.count() == 6
    assert list(TimeRecord.objects.order_by("nsr").values_list("nsr", flat=True)) == [1, 2, 3, 4, 5, 6]
    assert services.verify_unit_chain(unit) == []
