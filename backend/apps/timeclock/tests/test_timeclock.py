import datetime
import uuid
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, connection, transaction
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Unit
from apps.timeclock import hashing, services
from apps.timeclock.models import AppendOnlyError, NsrCounter, TimeRecord

pytestmark = pytest.mark.django_db

CPF = "52998224725"
CNPJ = "11222333000181"


def make_unit(company, name="Centro", **extra):
    return Unit.objects.create(company=company, name=name, **extra)


def make_device(company, unit, name="Tablet"):
    device = Device.objects.create(company=company, unit=unit, name=name)
    code, _ = device_services.new_activation_code(device)
    device, token = device_services.activate(code)
    return device, token


def tablet(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
    return client


def make_employee(company, unit, registration="1", name="Maria", cpf=CPF, active=True):
    employee = Employee.objects.create(
        company=company, registration=registration, full_name=name, cpf=cpf, is_active=active
    )
    if unit is not None:
        ops.assign_unit(employee, company, unit, None, datetime.date(2020, 1, 1))
    return employee


def punch(client, registration="1", event=None, **extra):
    body = {"registration": registration, "client_event_id": str(event or uuid.uuid4()), **extra}
    return client.post("/api/device/punches/", body, format="json")


@pytest.fixture
def setup(tenant_a):
    unit = make_unit(tenant_a.company)
    device, token = make_device(tenant_a.company, unit)
    employee = make_employee(tenant_a.company, unit)
    return tenant_a, unit, device, tablet(token), employee


# ---------- Gravação ----------


def test_marcacao_grava_campos_exigidos_pelo_anexo_ix(setup):
    tenant, unit, device, client, employee = setup
    r = punch(client, declared_kind="entry")
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False and body["record"]["nsr"] == 1
    record = TimeRecord.objects.get()
    assert record.nsr == 1 and record.unit_id == unit.pk and record.device_id == device.pk
    assert record.cpf == CPF and record.employee_name == "Maria" and record.registration == "1"
    assert record.occurred_at == record.recorded_at
    assert (
        record.occurred_offset_minutes == -180 and record.recorded_offset_minutes == -180
    )  # America/Sao_Paulo
    assert (
        len(record.record_hash) == 64
        and record.prev_hash == ""
        and record.hash_version == hashing.HASH_VERSION
    )
    assert record.identification_method == "registration" and record.offline is False
    assert record.declared_kind == "entry" and record.collector_code == "01"


def test_resposta_nao_expoe_cpf_completo(setup):
    *_, client, _employee = setup
    body = punch(client).json()
    assert body["record"]["cpf"] == "***.***.***-25" and body["receipt"]["worker"]["cpf"] == "***.***.***-25"
    assert CPF not in str(body)


def test_nsr_sequencial_por_unidade_e_independente_entre_unidades(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "A"), make_unit(tenant_a.company, "B")
    _, t1 = make_device(tenant_a.company, u1)
    _, t2 = make_device(tenant_a.company, u2)
    make_employee(tenant_a.company, u1, "1")
    make_employee(tenant_a.company, u2, "2", cpf="11144477735")
    c1, c2 = tablet(t1), tablet(t2)
    assert [punch(c1, "1").json()["record"]["nsr"] for _ in range(3)] == [1, 2, 3]
    assert punch(c2, "2").json()["record"]["nsr"] == 1
    assert punch(c1, "1").json()["record"]["nsr"] == 4


def test_hash_encadeado_e_verificavel(setup):
    tenant, unit, *_, client, _employee = setup
    for _ in range(3):
        punch(client)
    records = list(TimeRecord.objects.order_by("nsr"))
    assert records[1].prev_hash == records[0].record_hash and records[2].prev_hash == records[1].record_hash
    assert len({r.record_hash for r in records}) == 3
    assert services.verify_unit_chain(unit) == []
    call_command("verify_timeclock")


def test_formato_dh_e_hash_seguem_o_layout_historico():
    moment = datetime.datetime(2021, 4, 27, 19, 44, 31, tzinfo=datetime.UTC)
    assert hashing.format_dh(moment, -180) == "2021-04-27T16:44:00-0300"
    assert hashing.format_dh(moment, 330) == "2021-04-28T01:14:00+0530"
    args = dict(
        nsr=7,
        occurred_at=moment,
        occurred_offset=-180,
        cpf="123",
        recorded_at=moment,
        recorded_offset=-180,
        collector_code="01",
        offline=False,
        prev_hash="ab",
    )
    expected = (
        "000000007"
        + "7"
        + "2021-04-27T16:44:00-0300"
        + "000000000123"
        + "2021-04-27T16:44:00-0300"
        + "01"
        + "0"
        + "ab"
    )
    import hashlib

    assert hashing.compute_hash(**args) == hashlib.sha256(expected.encode()).hexdigest()
    assert hashing.compute_hash(**{**args, "offline": True}) != hashing.compute_hash(**args)


def test_verificacao_detecta_adulteracao_lacuna_e_contador(setup):
    tenant, unit, device, client, employee = setup
    for _ in range(2):
        punch(client)
    first = TimeRecord.objects.get(nsr=1)
    forged = TimeRecord(
        nsr=9,
        unit=unit,
        company=tenant.company,
        employee=employee,
        device=device,
        client_event_id=uuid.uuid4(),
        occurred_at=first.occurred_at,
        occurred_offset_minutes=-180,
        occurred_local_date=first.occurred_local_date,
        recorded_at=first.recorded_at,
        recorded_offset_minutes=-180,
        cpf=CPF,
        employee_name="x",
        registration="1",
        identification_method="registration",
        hash_version=hashing.HASH_VERSION,
        prev_hash="errado",
        record_hash="0" * 64,
    )
    if connection.vendor == "postgresql":
        # O banco recusa a inserção fora da cadeia (migration 0006)...
        with pytest.raises(IntegrityError), transaction.atomic():
            TimeRecord.objects.bulk_create([forged])
        # ...e, se alguém com DDL desligar os gatilhos, a verificação ainda detecta.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE timeclock_timerecord DISABLE TRIGGER timeclock_timerecord_chain")
            TimeRecord.objects.bulk_create([forged])
            cursor.execute("ALTER TABLE timeclock_timerecord ENABLE TRIGGER timeclock_timerecord_chain")
    else:
        TimeRecord.objects.bulk_create([forged])
    problems = "\n".join(services.verify_unit_chain(unit))
    assert "NSR 9: esperado 3" in problems and "hash anterior" in problems and "recalculado" in problems
    assert "Contador" in problems
    with pytest.raises(CommandError):
        call_command("verify_timeclock")


# ---------- Idempotência ----------


def test_reenvio_do_mesmo_evento_nao_duplica_nem_consome_nsr(setup):
    *_, client, _employee = setup
    event = uuid.uuid4()
    first = punch(client, event=event)
    again = punch(client, event=event, declared_kind="exit")  # payload diferente: devolve o original
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["record"]["id"] == first.json()["record"]["id"]
    assert again.json()["record"]["declared_kind"] == ""
    assert TimeRecord.objects.count() == 1
    assert punch(client).json()["record"]["nsr"] == 2


def test_marcacoes_distintas_proximas_nao_sao_descartadas(setup):
    *_, client, _employee = setup
    for _ in range(5):
        assert punch(client).status_code == 201
    assert TimeRecord.objects.count() == 5


def test_mesmo_evento_em_outro_dispositivo_e_outra_marcacao(tenant_a):
    unit = make_unit(tenant_a.company)
    _, t1 = make_device(tenant_a.company, unit, "T1")
    _, t2 = make_device(tenant_a.company, unit, "T2")
    make_employee(tenant_a.company, unit)
    event = uuid.uuid4()
    assert punch(tablet(t1), event=event).status_code == 201
    assert punch(tablet(t2), event=event).status_code == 201
    assert TimeRecord.objects.count() == 2


def test_corrida_entre_dois_envios_do_mesmo_evento_devolve_o_original(setup):
    tenant, unit, device, client, employee = setup
    event = uuid.uuid4()
    original, created = services.record_punch(device=device, registration="1", client_event_id=event)
    assert created
    real = services._existing
    calls = {"n": 0}

    def late_lookup(device_, event_):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(device_, event_)

    with mock.patch.object(services, "_existing", late_lookup):
        record, created = services.record_punch(device=device, registration="1", client_event_id=event)
    assert created is False and record.pk == original.pk
    assert TimeRecord.objects.count() == 1 and NsrCounter.objects.get(unit=unit).last_nsr == 1


def test_falha_na_gravacao_nao_consome_nsr_nem_deixa_registro(setup):
    tenant, unit, device, client, employee = setup
    punch(client)
    with mock.patch.object(TimeRecord.objects, "create", side_effect=RuntimeError("disco cheio")):
        with pytest.raises(RuntimeError):
            services.record_punch(device=device, registration="1", client_event_id=uuid.uuid4())
    counter = NsrCounter.objects.get(unit=unit)
    assert counter.last_nsr == 1 and TimeRecord.objects.count() == 1
    assert services.verify_unit_chain(unit) == []
    assert punch(client).json()["record"]["nsr"] == 2


# ---------- Escopo, identificação e regras que NÃO bloqueiam ----------


def test_matricula_desconhecida_ou_fora_da_unidade_nao_grava_nem_consome_nsr(tenant_a, tenant_b):
    unit, other = make_unit(tenant_a.company, "A"), make_unit(tenant_a.company, "B")
    unit_b = make_unit(tenant_b.company, "A")
    _, token = make_device(tenant_a.company, unit)
    make_employee(tenant_a.company, other, "2", cpf="")
    make_employee(tenant_a.company, unit, "3", cpf="", active=False)
    make_employee(tenant_b.company, unit_b, "4", cpf="")
    client = tablet(token)
    for reg in ("999", "2", "3", "4"):
        r = punch(client, reg)
        assert r.status_code == 404, reg
    assert TimeRecord.objects.count() == 0
    assert (
        not NsrCounter.objects.filter(unit=unit).exists() or NsrCounter.objects.get(unit=unit).last_nsr == 0
    )


def test_corpo_nao_escolhe_empresa_unidade_nem_dispositivo(setup, tenant_b):
    tenant, unit, device, client, employee = setup
    other_unit = make_unit(tenant_b.company)
    r = punch(client, company=tenant_b.company.pk, unit=other_unit.pk, device=999, nsr=50)
    assert r.status_code == 201
    record = TimeRecord.objects.get()
    assert record.company_id == tenant.company.pk and record.unit_id == unit.pk and record.nsr == 1


def test_marcacao_nao_depende_de_jornada_escala_ou_horario(setup):
    # Art. 74: sem restrição de horário, sem exigir autorização, sem checar escala.
    *_, client, employee = setup
    assert employee.schedule_assignments.count() == 0
    assert punch(client).status_code == 201


def test_unidade_inativada_depois_da_ativacao_nao_impede_registrar(setup):
    tenant, unit, *_, client, _employee = setup
    Unit.objects.filter(pk=unit.pk).update(is_active=False)
    assert punch(client).status_code == 201


def test_funcionario_sem_cpf_nao_perde_a_marcacao(tenant_a):
    unit = make_unit(tenant_a.company)
    _, token = make_device(tenant_a.company, unit)
    make_employee(tenant_a.company, unit, cpf="")
    body = punch(tablet(token)).json()
    assert body["record"]["cpf"] == ""
    assert "trabalhador.cpf" in body["receipt"]["pending_fields"]
    assert TimeRecord.objects.get().cpf == ""


def test_identificacao_desconhecida_ou_desligada_nao_grava(setup, settings):
    *_, client, _employee = setup
    assert punch(client, identification={"method": "magia"}).status_code == 400
    settings.TIMECLOCK_ALLOW_REGISTRATION_ONLY = False
    assert punch(client).status_code == 400
    assert TimeRecord.objects.count() == 0


def test_relogio_do_aparelho_e_preservado_sem_bloquear(setup):
    *_, client, _employee = setup
    reported = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)).isoformat()
    r = punch(client, device_reported_at=reported)
    assert r.status_code == 201
    record = TimeRecord.objects.get()
    assert -310 < record.clock_skew_seconds < -290
    assert record.device_reported_at is not None and record.occurred_at != record.device_reported_at


def test_entradas_invalidas_sao_rejeitadas(setup):
    *_, client, _employee = setup
    base = {"registration": "1", "client_event_id": str(uuid.uuid4())}
    for bad in (
        {**base, "client_event_id": "nao-e-uuid"},
        {**base, "declared_kind": "lunch"},
        {**base, "registration": ""},
        {**base, "registration": "x" * 31},
        {**base, "device_reported_at": "ontem"},
        {"client_event_id": base["client_event_id"]},
    ):
        assert client.post("/api/device/punches/", bad, format="json").status_code == 400, bad
    assert TimeRecord.objects.count() == 0


# ---------- Autenticação do dispositivo ----------


def test_marcar_exige_credencial_de_dispositivo(setup):
    tenant, *_, client, _employee = setup
    body = {"registration": "1", "client_event_id": str(uuid.uuid4())}
    assert APIClient().post("/api/device/punches/", body, format="json").status_code in (401, 403)
    assert tenant.client("company_admin").post("/api/device/punches/", body, format="json").status_code in (
        401,
        403,
    )
    assert TimeRecord.objects.count() == 0


def test_dispositivo_revogado_nao_marca(setup):
    tenant, unit, device, client, _employee = setup
    device_services.revoke(Device.objects.get(pk=device.pk))
    assert punch(client).status_code == 401
    assert TimeRecord.objects.count() == 0


# ---------- Imutabilidade ----------


def test_orm_nao_altera_nem_apaga_marcacoes(setup):
    *_, client, _employee = setup
    punch(client)
    record = TimeRecord.objects.get()
    record.registration = "outra"
    with pytest.raises(AppendOnlyError):
        record.save()
    with pytest.raises(AppendOnlyError):
        record.delete()
    with pytest.raises(AppendOnlyError):
        TimeRecord.objects.all().update(registration="x")
    with pytest.raises(AppendOnlyError):
        TimeRecord.objects.all().delete()
    with pytest.raises(AppendOnlyError):
        TimeRecord.objects.bulk_update([record], ["registration"])
    with pytest.raises(AppendOnlyError):
        TimeRecord.objects.bulk_create(
            [record], update_conflicts=True, update_fields=["cpf"], unique_fields=["id"]
        )
    record.refresh_from_db()
    assert record.registration == "1"


@pytest.mark.skipif(
    connection.vendor not in ("sqlite", "postgresql"), reason="gatilho só criado nesses bancos"
)
def test_banco_bloqueia_sql_direto(setup):
    *_, client, _employee = setup
    punch(client)
    table = TimeRecord._meta.db_table
    for sql in (f"UPDATE {table} SET registration = 'x'", f"DELETE FROM {table}"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)
    assert TimeRecord.objects.get().registration == "1"


# ---------- Painel somente leitura ----------


def list_url(company, query=""):
    return f"/api/companies/{company.pk}/time-records/{query}"


def test_painel_nao_tem_escrita(setup):
    tenant, *_, client, _employee = setup
    punch(client)
    admin = tenant.client("company_admin")
    record_id = TimeRecord.objects.get().pk
    detail = list_url(tenant.company, f"{record_id}/")
    for method in ("post", "put", "patch", "delete"):
        assert getattr(admin, method)(list_url(tenant.company), {}, format="json").status_code == 405
        assert getattr(admin, method)(detail, {}, format="json").status_code == 405
    assert TimeRecord.objects.get().registration == "1"


def test_painel_lista_filtra_pagina_e_mascara_cpf(setup):
    tenant, unit, device, client, employee = setup
    for _ in range(30):
        punch(client)
    admin = tenant.client("company_admin")
    page = admin.get(list_url(tenant.company)).json()
    assert page["count"] == 30 and len(page["results"]) == 25
    assert page["results"][0]["nsr"] == 30 and page["results"][0]["cpf"] == "***.***.***-25"
    assert admin.get(list_url(tenant.company, f"?employee={employee.pk}")).json()["count"] == 30
    assert admin.get(list_url(tenant.company, "?employee=999999")).json()["count"] == 0
    assert admin.get(list_url(tenant.company, "?from=2000-01-01&to=2000-01-02")).json()["count"] == 0
    today = TimeRecord.objects.first().occurred_local_date.isoformat()
    assert admin.get(list_url(tenant.company, f"?from={today}&to={today}")).json()["count"] == 30
    for bad in ("?from=ontem", "?employee=abc", "?unit=-1"):
        assert admin.get(list_url(tenant.company, bad)).status_code == 400
    assert CPF not in str(page)


def test_acesso_ao_historico_por_papel_e_empresa(setup, tenant_b):
    tenant, unit, *_, client, employee = setup
    punch(client)
    record_id = TimeRecord.objects.get().pk
    assert tenant.client("employee").get(list_url(tenant.company)).status_code == 403
    manager = tenant.client("manager")
    assert manager.get(list_url(tenant.company)).json()["count"] == 0  # gestor sem escopo
    tenant.memberships["manager"].scope_units.add(unit)
    assert manager.get(list_url(tenant.company)).json()["count"] == 1
    assert manager.get(list_url(tenant.company, f"{record_id}/")).status_code == 200
    other = tenant_b.client("company_admin")
    assert other.get(list_url(tenant.company)).status_code == 404
    assert other.get(list_url(tenant.company, f"{record_id}/")).status_code == 404
    assert other.get(list_url(tenant_b.company, f"{record_id}/")).status_code == 404
    assert other.get(list_url(tenant_b.company)).json()["count"] == 0


# ---------- Comprovante ----------


def test_comprovante_traz_os_campos_do_art_79_e_lista_pendencias(setup, settings):
    tenant, unit, device, client, employee = setup
    receipt = punch(client).json()["receipt"]
    assert receipt["title"] == "Comprovante de Registro de Ponto do Trabalhador" and receipt["nsr"] == 1
    assert receipt["signed"] is False and receipt["hash_sha256"] == TimeRecord.objects.get().record_hash
    assert receipt["occurred_at"].endswith("-03:00") and receipt["service_location"]["unit"] == "Centro"
    assert {"empregador.cnpj_cpf", "local_prestacao_servico.endereco", "numero_registro_inpi"} <= set(
        receipt["pending_fields"]
    )
    tenant.company.legal_name, tenant.company.tax_id_type, tenant.company.tax_id = (
        "Empresa A Ltda",
        "CNPJ",
        CNPJ,
    )
    tenant.company.save()
    Unit.objects.filter(pk=unit.pk).update(address="Rua 1, 100")
    settings.REP_P_INPI_REGISTRATION = "BR512026000001"
    full = punch(client).json()["receipt"]
    assert full["pending_fields"] == []
    assert full["employer"]["document"] == CNPJ and full["service_location"]["address"] == "Rua 1, 100"
    assert full["rep_p_inpi_registration"] == "BR512026000001"


def test_comprovante_so_do_proprio_dispositivo(setup, tenant_b):
    tenant, unit, device, client, _employee = setup
    record_id = punch(client).json()["record"]["id"]
    assert client.get(f"/api/device/punches/{record_id}/receipt/").status_code == 200
    _, other_token = make_device(tenant.company, unit, "Outro")
    assert tablet(other_token).get(f"/api/device/punches/{record_id}/receipt/").status_code == 404
    unit_b = make_unit(tenant_b.company)
    _, token_b = make_device(tenant_b.company, unit_b)
    assert tablet(token_b).get(f"/api/device/punches/{record_id}/receipt/").status_code == 404


# ---------- Dados do empregador ----------


def employer_url(company):
    return f"/api/companies/{company.pk}/employer/"


def test_admin_atualiza_empregador_com_validacao_e_auditoria(tenant_a):
    admin = tenant_a.client("company_admin")
    ok = admin.patch(
        employer_url(tenant_a.company),
        {"legal_name": "Empresa A Ltda", "tax_id_type": "CNPJ", "tax_id": "11.222.333/0001-81"},
        format="json",
    )
    assert ok.status_code == 200 and ok.json()["tax_id"] == CNPJ
    log = AuditLog.objects.get(action="employer.updated")
    assert log.metadata["before"]["tax_id"] == "" and log.metadata["after"]["tax_id"] == CNPJ
    for bad in (
        {"tax_id_type": "CNPJ", "tax_id": "11.222.333/0001-82"},
        {"tax_id_type": "CPF", "tax_id": "123"},
        {"tax_id": "x"},
        {"tax_id_type": "XYZ"},
    ):
        assert admin.patch(employer_url(tenant_a.company), bad, format="json").status_code == 400, bad
    assert (
        admin.patch(
            employer_url(tenant_a.company), {"tax_id_type": "CPF", "tax_id": "529.982.247-25"}, format="json"
        ).json()["tax_id"]
        == CPF
    )
    assert tenant_a.company.__class__.objects.get(pk=tenant_a.company.pk).tax_id == CPF


def test_empregador_permissoes_e_isolamento(tenant_a, tenant_b, platform_admin):
    from conftest import login_client

    url = employer_url(tenant_a.company)
    assert tenant_a.client("manager").get(url).status_code == 200
    assert tenant_a.client("manager").patch(url, {"legal_name": "x"}, format="json").status_code == 403
    assert tenant_a.client("employee").get(url).status_code == 403
    assert tenant_b.client("company_admin").get(url).status_code == 404
    assert tenant_b.client("company_admin").patch(url, {"legal_name": "x"}, format="json").status_code == 404
    assert login_client(platform_admin).patch(url, {"legal_name": "x"}, format="json").status_code == 403
    tenant_a.company.refresh_from_db()
    assert tenant_a.company.legal_name == ""


def test_endereco_da_unidade_pode_ser_informado(tenant_a):
    r = tenant_a.client("company_admin").post(
        f"/api/companies/{tenant_a.company.pk}/units/",
        {"name": "Sede", "address": "Av. Brasil, 1"},
        format="json",
    )
    assert r.status_code == 201 and r.json()["address"] == "Av. Brasil, 1"


@pytest.mark.parametrize("query", ["?from=2026-02-30", "?to=2026-13-01"])
def test_datas_impossiveis_retornam_400(setup, query):
    tenant, *_ = setup
    assert tenant.client("company_admin").get(list_url(tenant.company, query)).status_code == 400


@pytest.mark.parametrize("method", [[], {}, 12, None])
def test_identificacao_malformada_nao_gera_500(setup, method):
    *_, client, _employee = setup
    assert punch(client, identification={"method": method}).status_code == 400
    assert not TimeRecord.objects.exists()


def test_cnpj_nao_descarta_letras_ou_digitos_unicode(tenant_a):
    admin = tenant_a.client("company_admin")
    for value in ("x11222333000181", "１１２２２３３３０００１８１"):
        assert (
            admin.patch(
                employer_url(tenant_a.company), {"tax_id_type": "CNPJ", "tax_id": value}, format="json"
            ).status_code
            == 400
        )


def test_cpf_empregador_nao_vaza_em_auditoria_gestor_ou_terminal(setup):
    tenant, *_rest, client, _employee = setup
    admin = tenant.client("company_admin")
    admin.patch(employer_url(tenant.company), {"tax_id_type": "CPF", "tax_id": CPF}, format="json")
    assert CPF not in str(AuditLog.objects.get(action="employer.updated").metadata)
    assert CPF not in str(tenant.client("manager").get(employer_url(tenant.company)).json())
    assert CPF not in str(punch(client).json())
    admin.patch(employer_url(tenant.company), {"tax_id_type": "CNPJ", "tax_id": CNPJ}, format="json")
    assert all(CPF not in str(log.metadata) for log in AuditLog.objects.filter(action="employer.updated"))


def test_comprovante_nao_muda_com_cadastro_ou_configuracao(setup, settings):
    tenant, unit, device, client, employee = setup
    event = uuid.uuid4()
    original = punch(client, event=event).json()
    tenant.company.legal_name = "Novo nome"
    tenant.company.save()
    Unit.objects.filter(pk=unit.pk).update(address="Novo endereco", name="Nova sede")
    settings.REP_P_INPI_REGISTRATION = "novo"
    assert punch(client, event=event).json()["receipt"] == original["receipt"]
    url = f"/api/device/punches/{original['record']['id']}/receipt/"
    assert client.get(url).json() == original["receipt"]


def test_revogacao_entre_autenticacao_e_servico_nao_grava(setup):
    from rest_framework.exceptions import AuthenticationFailed

    tenant, unit, device, client, employee = setup
    stale_credential = device.credentials.first()
    device_services.revoke(Device.objects.get(pk=device.pk))
    with pytest.raises(AuthenticationFailed):
        services.record_punch(
            device=device, credential=stale_credential, registration="1", client_event_id=uuid.uuid4()
        )
    assert not TimeRecord.objects.exists()


def test_empresa_inativa_nao_registra(setup):
    tenant, unit, device, client, employee = setup
    tenant.company.is_active = False
    tenant.company.save()
    assert punch(client).status_code == 403
    assert not TimeRecord.objects.exists()


def test_falha_apos_insert_reverte_registro_e_nsr(setup):
    tenant, unit, device, client, employee = setup
    punch(client)
    with mock.patch.object(NsrCounter, "save", side_effect=RuntimeError("falha")):
        assert punch(client).status_code == 500
    assert TimeRecord.objects.count() == 1
    assert services.verify_unit_chain(unit) == []
    assert punch(client).json()["record"]["nsr"] == 2


@pytest.mark.parametrize(
    "tz_name,moment,offset,local_date",
    [
        ("America/Sao_Paulo", "2026-10-22T01:30:00+00:00", -180, "2026-10-21"),
        ("Asia/Kathmandu", "2026-10-22T20:00:00+00:00", 345, "2026-10-23"),
        ("America/St_Johns", "2026-01-22T02:00:00+00:00", -210, "2026-01-21"),
        ("America/New_York", "2026-11-01T05:30:00+00:00", -240, "2026-11-01"),
        ("America/New_York", "2026-11-01T06:30:00+00:00", -300, "2026-11-01"),
    ],
)
def test_data_local_e_offset_no_instante(setup, tz_name, moment, offset, local_date):
    tenant, unit, device, client, employee = setup
    Unit.objects.filter(pk=unit.pk).update(timezone=tz_name)
    with mock.patch.object(services.timezone, "now", return_value=datetime.datetime.fromisoformat(moment)):
        # Serviço sem credencial: relógio congelado não interfere na expiração do token de teste.
        record, _ = services.record_punch(device=device, registration="1", client_event_id=uuid.uuid4())
    assert record.occurred_offset_minutes == offset
    assert record.occurred_local_date.isoformat() == local_date
    assert services.verify_unit_chain(unit) == []


def test_fks_protegem_exclusao_indireta(setup):
    from django.db.models.deletion import ProtectedError

    tenant, unit, device, client, employee = setup
    punch(client)
    for obj in (tenant.company, unit, device, employee):
        with pytest.raises(ProtectedError):
            obj.delete()
    assert TimeRecord.objects.count() == 1


def test_contador_sem_registros_e_detectado(setup):
    _, unit, *_ = setup
    if connection.vendor == "postgresql":
        with pytest.raises(IntegrityError), transaction.atomic():
            NsrCounter.objects.create(unit=unit, last_nsr=8, last_hash="x")
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE timeclock_nsrcounter DISABLE TRIGGER timeclock_nsrcounter_guard")
            NsrCounter.objects.create(unit=unit, last_nsr=8, last_hash="x")
            cursor.execute("ALTER TABLE timeclock_nsrcounter ENABLE TRIGGER timeclock_nsrcounter_guard")
    else:
        NsrCounter.objects.create(unit=unit, last_nsr=8, last_hash="x")
    assert "Contador" in str(services.verify_unit_chain(unit))


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Gatilhos de cadeia só no PostgreSQL")
def test_postgresql_recusa_insercao_e_contador_fora_da_cadeia(setup):
    *_, client, _employee = setup
    punch(client)
    record = TimeRecord.objects.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        NsrCounter.objects.filter(unit=record.unit).update(last_nsr=5)
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM timeclock_nsrcounter")
    # Registro com NSR certo mas hash inventado também é recusado.
    copy = TimeRecord(
        **{
            f.attname: getattr(record, f.attname)
            for f in TimeRecord._meta.concrete_fields
            if f.attname not in ("id",)
        }
    )
    copy.nsr, copy.prev_hash, copy.record_hash, copy.client_event_id = (
        2,
        record.record_hash,
        "f" * 64,
        uuid.uuid4(),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TimeRecord.objects.bulk_create([copy])
    assert services.verify_unit_chain(record.unit) == []


@pytest.mark.skipif(connection.vendor != "postgresql", reason="TRUNCATE requer PostgreSQL")
def test_postgresql_bloqueia_truncate(setup):
    *_, client, _employee = setup
    punch(client)
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("TRUNCATE timeclock_timerecord CASCADE")
    assert TimeRecord.objects.count() == 1


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Concorrencia exige PostgreSQL real")
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_event,same_device", [(True, True), (False, True), (False, False)])
def test_nsr_concorrente_postgresql(setup, same_event, same_device):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    tenant, unit, device, client, employee = setup
    other = device if same_device else make_device(tenant.company, unit, "Outro")[0]
    event = uuid.uuid4()
    barrier = Barrier(2)

    def attempt(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            record, created = services.record_punch(
                device=device if index == 0 else other,
                registration="1",
                client_event_id=event if same_event else uuid.uuid4(),
            )
            return record.pk, created
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, index) for index in range(2)]
        results = [future.result(timeout=20) for future in futures]
    expected = 1 if same_event else 2
    assert sum(created for _, created in results) == expected
    assert len({pk for pk, _ in results}) == expected
    assert list(TimeRecord.objects.order_by("nsr").values_list("nsr", flat=True)) == list(
        range(1, expected + 1)
    )
    assert NsrCounter.objects.get(unit=unit).last_nsr == expected
    assert services.verify_unit_chain(unit) == []


@pytest.mark.skipif(connection.vendor != "sqlite", reason="REPLACE especifico do SQLite")
def test_sqlite_replace_nao_contorna_imutabilidade(setup):
    *_, client, _employee = setup
    punch(client)
    fields = [field.column for field in TimeRecord._meta.concrete_fields]
    columns = ", ".join(connection.ops.quote_name(field) for field in fields)
    values = ", ".join(
        "'adulterado'" if field == "registration" else connection.ops.quote_name(field) for field in fields
    )
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            f"INSERT OR REPLACE INTO timeclock_timerecord ({columns}) "
            f"SELECT {values} FROM timeclock_timerecord"
        )
    assert TimeRecord.objects.get().registration == "1"


def test_empregador_aceita_formulario_parcial_sem_documento(tenant_a):
    response = tenant_a.client("company_admin").patch(
        employer_url(tenant_a.company),
        {"legal_name": "Empresa", "tax_id_type": "", "tax_id": "", "cei_caepf_cno": ""},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["legal_name"] == "Empresa"


def test_relogio_muito_distante_cabe_no_campo_do_postgresql(setup):
    *_, client, _employee = setup
    assert punch(client, device_reported_at="9999-01-01T00:00:00Z").status_code == 201
    assert TimeRecord.objects.get().clock_skew_seconds > 2**31
