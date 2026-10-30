import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.attendance.models import PeriodClosing, PunchAdjustment
from apps.audit.models import AuditLog
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, ScheduleDay, Unit, WorkSchedule
from apps.timeclock import services as tc
from apps.timeclock.models import TimeRecord

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("America/Sao_Paulo")
MON = dt.date(2026, 10, 19)


def local(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=TZ)


class World:
    def __init__(self, tenant):
        self.tenant = tenant
        self.company = tenant.company
        self.unit = Unit.objects.create(company=self.company, name="Centro")
        self.other_unit = Unit.objects.create(company=self.company, name="Filial")
        device = Device.objects.create(company=self.company, unit=self.unit, name="Tablet")
        code, _ = device_services.new_activation_code(device)
        self.device, _ = device_services.activate(code)
        Device.objects.filter(pk=self.device.pk).update(activated_at=timezone.now() - dt.timedelta(days=60))
        self.device.refresh_from_db()
        schedule = WorkSchedule.objects.create(company=self.company, name="Comercial")
        for wd in range(5):
            ScheduleDay.objects.create(
                schedule=schedule, weekday=wd, start_time=dt.time(8), end_time=dt.time(17), break_minutes=60
            )
        self.employee = self.make_employee("1", "Maria", schedule)
        self.schedule = schedule
        manager = tenant.memberships["manager"]
        manager.scope_units.add(self.unit)
        self.employee.access_user = tenant.users["employee"]
        self.employee.save()

    def make_employee(self, reg, name, schedule, unit=None):
        e = Employee.objects.create(company=self.company, registration=reg, full_name=name)
        ops.assign_unit(e, self.company, unit or self.unit, None, dt.date(2020, 1, 1))
        ops.assign_schedule(e, self.company, schedule, dt.date(2020, 1, 1))
        return e

    def punch(self, moment, employee=None):
        return tc._insert(
            self.device,
            employee or self.employee,
            uuid.uuid4(),
            "",
            None,
            tc.IdentificationResult("registration"),
            occurred_at=moment.astimezone(dt.UTC),
        )

    def day(self, day, *times, employee=None):
        return [self.punch(local(day, t), employee) for t in times]

    def url(self, suffix):
        return f"/api/companies/{self.company.pk}/{suffix}"


@pytest.fixture
def world(tenant_a):
    return World(tenant_a)


def timesheet(client, w, start=MON, end=MON, employee=None):
    return client.get(
        w.url("attendance/timesheet/"),
        {"employee": (employee or w.employee).pk, "from": start.isoformat(), "to": end.isoformat()},
    )


def test_espelho_com_explicacao_e_isolamento(world, tenant_b):
    world.day(MON, "08:00", "12:00", "13:00", "18:00")
    r = timesheet(world.tenant.client("company_admin"), world)
    assert r.status_code == 200, r.content
    day = r.json()["days"][0]
    assert day["overtime_minutes"] == 60 and day["worked_minutes"] == 540 and day["steps"]
    assert r.json()["totals"]["overtime_by_rate"] == {"50": 60}
    assert r.json()["rule_versions"] == [{"from": "2026-10-19", "to": "2026-10-19", "version": 0}]
    assert timesheet(world.tenant.client("manager"), world).status_code == 200
    assert timesheet(world.tenant.client("employee"), world).status_code == 403
    assert timesheet(tenant_b.client("company_admin"), world).status_code == 404
    fora = world.make_employee("2", "Fora", world.schedule, unit=world.other_unit)
    assert timesheet(world.tenant.client("manager"), world, employee=fora).status_code == 404


def test_periodo_invalido(world):
    c = world.tenant.client("company_admin")
    assert timesheet(c, world, start=MON, end=MON - dt.timedelta(days=1)).status_code == 400
    assert timesheet(c, world, start=MON, end=MON + dt.timedelta(days=70)).status_code == 400
    assert (
        c.get(world.url("attendance/timesheet/"), {"employee": "x", "from": "a", "to": "b"}).status_code
        == 400
    )


def test_regras_versionadas_por_vigencia(world):
    admin = world.tenant.client("company_admin")
    tue = MON + dt.timedelta(days=1)
    world.day(MON, "08:04", "12:00", "13:00", "17:00")
    world.day(tue, "08:04", "12:00", "13:00", "17:00")
    r = admin.post(
        world.url("attendance/rules/"),
        {
            "valid_from": tue.isoformat(),
            "params": {"tolerance_per_mark_minutes": 0, "tolerance_daily_minutes": 0},
        },
        format="json",
    )
    assert r.status_code == 201 and r.json()["version"] == 1
    days = timesheet(admin, world, MON, tue).json()
    assert days["days"][0]["deficit_minutes"] == 0 and days["days"][1]["deficit_minutes"] == 4
    assert [v["version"] for v in days["rule_versions"]] == [0, 1]
    assert (
        admin.post(
            world.url("attendance/rules/"), {"valid_from": "2026-11-01", "params": {"x": 1}}, format="json"
        ).status_code
        == 400
    )
    assert (
        world.tenant.client("manager")
        .post(world.url("attendance/rules/"), {"valid_from": "2026-11-01", "params": {}}, format="json")
        .status_code
        == 403
    )
    info = admin.get(world.url("attendance/rules/")).json()
    assert "tolerance_per_mark_minutes" in info["references"] and len(info["versions"]) == 1


def test_feriado_da_unidade(world):
    admin = world.tenant.client("company_admin")
    assert (
        admin.post(
            world.url("attendance/holidays/"),
            {"date": MON.isoformat(), "name": "Aniversário", "unit_id": world.unit.pk},
            format="json",
        ).status_code
        == 201
    )
    world.day(MON, "08:00", "12:00")
    day = timesheet(admin, world).json()["days"][0]
    assert (
        day["holiday"] == "Aniversário"
        and day["overtime_rate_percent"] == 100
        and day["expected_minutes"] == 0
    )
    assert (
        admin.post(
            world.url("attendance/holidays/"),
            {"date": MON.isoformat(), "name": "Outro", "unit_id": world.unit.pk},
            format="json",
        ).status_code
        == 400
    )


def test_inclusao_com_aprovacao_preserva_original(world):
    manager, admin = world.tenant.client("manager"), world.tenant.client("company_admin")
    world.day(MON, "08:00", "12:00", "13:00")  # esqueceu a saída
    originals = TimeRecord.objects.count()
    assert timesheet(admin, world).json()["days"][0]["status"] == "inconsistent"
    r = manager.post(
        world.url("attendance/requests/"),
        {
            "employee_id": world.employee.pk,
            "kind": "include",
            "occurred_at": local(MON, "17:00").isoformat(),
            "reason": "Esqueceu de marcar a saída",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    item = r.json()
    assert timesheet(admin, world).json()["days"][0]["status"] == "inconsistent"  # pendente não conta
    assert (
        manager.post(
            world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json"
        ).status_code
        == 403
    )
    assert (
        admin.post(
            world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": False}, format="json"
        ).status_code
        == 400
    )
    r = admin.post(
        world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json"
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    day = timesheet(admin, world).json()["days"][0]
    assert day["status"] == "ok" and any(m["origin"] == "included" for m in day["marks"])
    assert TimeRecord.objects.count() == originals
    assert (
        admin.post(
            world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json"
        ).status_code
        == 400
    )
    assert AuditLog.objects.filter(action="attendance.adjustment_approved").count() == 1


def test_desconsiderar_marcacao(world):
    manager, admin = world.tenant.client("manager"), world.tenant.client("company_admin")
    records = world.day(MON, "08:00", "10:00", "12:00", "13:00", "17:00")  # 10:00 indevida
    body = {
        "employee_id": world.employee.pk,
        "kind": "disregard",
        "record_id": records[1].pk,
        "reason": "Marcação por engano",
    }
    item = manager.post(world.url("attendance/requests/"), body, format="json").json()
    assert manager.post(world.url("attendance/requests/"), body, format="json").status_code == 400
    admin.post(world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json")
    day = timesheet(admin, world).json()["days"][0]
    assert day["status"] == "ok" and len(day["marks"]) == 4
    assert TimeRecord.objects.filter(pk=records[1].pk).exists()


def test_abono_de_falta(world):
    manager, admin = world.tenant.client("manager"), world.tenant.client("company_admin")
    assert timesheet(admin, world).json()["days"][0]["status"] == "absent"
    item = manager.post(
        world.url("attendance/requests/"),
        {
            "type": "justification",
            "employee_id": world.employee.pk,
            "date": MON.isoformat(),
            "kind": "medical",
            "reason": "Atestado de 1 dia",
            "document_ref": "CRM 123",
        },
        format="json",
    ).json()
    admin.post(
        world.url(f"attendance/justifications/{item['id']}/decision/"), {"approve": True}, format="json"
    )
    day = timesheet(admin, world).json()["days"][0]
    assert day["status"] == "justified" and day["deficit_minutes"] == 0 and day["justified_minutes"] == 480


def test_fechamento_bloqueia_alteracoes_e_detecta_divergencia(world):
    admin, manager = world.tenant.client("company_admin"), world.tenant.client("manager")
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    pend = manager.post(
        world.url("attendance/requests/"),
        {
            "type": "justification",
            "employee_id": world.employee.pk,
            "date": MON.isoformat(),
            "kind": "other",
            "reason": "Teste pendente",
        },
        format="json",
    ).json()
    close = {"start": MON.isoformat(), "end": (MON + dt.timedelta(days=6)).isoformat()}
    assert admin.post(world.url("attendance/closings/"), close, format="json").status_code == 400  # pendente
    admin.post(
        world.url(f"attendance/justifications/{pend['id']}/decision/"),
        {"approve": False, "note": "Sem documento"},
        format="json",
    )
    r = admin.post(world.url("attendance/closings/"), close, format="json")
    assert r.status_code == 201 and len(r.json()["snapshot_sha256"]) == 64
    closing_id = r.json()["id"]
    assert (
        admin.post(world.url("attendance/closings/"), close, format="json").status_code == 400
    )  # sobreposição
    # Nada que afete o período fechado é aceito.
    assert (
        manager.post(
            world.url("attendance/requests/"),
            {
                "employee_id": world.employee.pk,
                "kind": "include",
                "occurred_at": local(MON, "18:00").isoformat(),
                "reason": "Depois do fechamento",
            },
            format="json",
        ).status_code
        == 400
    )
    assert (
        admin.post(
            world.url("attendance/rules/"), {"valid_from": MON.isoformat(), "params": {}}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin.post(
            world.url("attendance/holidays/"), {"date": MON.isoformat(), "name": "X"}, format="json"
        ).status_code
        == 400
    )
    sheet = timesheet(admin, world).json()
    assert sheet["closings"][0]["divergent"] is False
    # Marcação offline sincronizada após o fechamento: o ponto é gravado e o espelho acusa divergência.
    world.punch(local(MON, "19:00"))
    assert timesheet(admin, world).json()["closings"][0]["divergent"] is True
    # Reabertura exige motivo, é auditada e libera ajustes.
    assert (
        admin.post(
            world.url(f"attendance/closings/{closing_id}/reopen/"), {"reason": ""}, format="json"
        ).status_code
        == 400
    )
    assert (
        manager.post(
            world.url(f"attendance/closings/{closing_id}/reopen/"), {"reason": "Ajustes"}, format="json"
        ).status_code
        == 403
    )
    r = admin.post(
        world.url(f"attendance/closings/{closing_id}/reopen/"),
        {"reason": "Marcação offline tardia"},
        format="json",
    )
    assert r.status_code == 200 and r.json()["status"] == "reopened"
    assert PeriodClosing.objects.count() == 1
    assert AuditLog.objects.filter(action="attendance.period_reopened").exists()
    # A marcação tardia deixou o dia com registro incompleto: fechar exige resolução ou exceção justificada.
    blocked = admin.post(world.url("attendance/closings/"), close, format="json")
    assert blocked.status_code == 400 and blocked.json()["code"] == "incomplete_marks"
    short = {**close, "accept_incomplete": True, "exception_reason": "curto"}
    assert admin.post(world.url("attendance/closings/"), short, format="json").status_code == 400
    ok = admin.post(
        world.url("attendance/closings/"),
        {**close, "accept_incomplete": True, "exception_reason": "Saída será corrigida na folha de novembro"},
        format="json",
    )
    assert ok.status_code == 201 and ok.json()["exceptions"]["employees"][0]["dates"] == [MON.isoformat()]
    assert AuditLog.objects.filter(action="attendance.period_closed_with_exception").exists()


def test_portal_do_funcionario(world, tenant_b):
    employee = world.tenant.client("employee")
    world.day(MON, "08:00", "12:00", "13:00")
    other = world.make_employee("2", "Outro", world.schedule)
    world.day(MON, "08:00", "17:00", employee=other)
    r = employee.get(world.url("me/timesheet/"), {"from": MON.isoformat(), "to": MON.isoformat()})
    assert r.status_code == 200 and r.json()["employee"]["id"] == world.employee.pk
    item = employee.post(
        world.url("me/requests/"),
        {"kind": "include", "occurred_at": local(MON, "17:00").isoformat(), "reason": "Esqueci a saída"},
        format="json",
    ).json()
    assert item["status"] == "pending" and item["employee"]["id"] == world.employee.pk
    # Não consegue pedir em nome de outro nem desconsiderar marcação alheia.
    other_record = TimeRecord.objects.filter(employee=other).first()
    assert (
        employee.post(
            world.url("me/requests/"),
            {"kind": "disregard", "record_id": other_record.pk, "reason": "Não é minha"},
            format="json",
        ).status_code
        == 400
    )
    assert employee.get(world.url("me/requests/")).json()["count"] == 1
    assert (
        employee.post(world.url(f"me/adjustments/{item['id']}/cancel/"), format="json").json()["status"]
        == "cancelled"
    )
    assert employee.post(world.url(f"me/adjustments/{item['id']}/cancel/"), format="json").status_code == 400
    assert (
        world.tenant.client("manager")
        .get(world.url("me/timesheet/"), {"from": "2026-10-19", "to": "2026-10-19"})
        .status_code
        == 403
    )
    assert (
        tenant_b.client("employee")
        .get(world.url("me/timesheet/"), {"from": "2026-10-19", "to": "2026-10-19"})
        .status_code
        == 404
    )


def test_resumo_por_unidade(world):
    world.day(MON, "08:00", "12:00", "13:00", "18:00")
    r = world.tenant.client("manager").get(
        world.url("attendance/summary/"),
        {"from": MON.isoformat(), "to": MON.isoformat(), "unit": world.unit.pk},
    )
    assert r.status_code == 200
    rows = r.json()["results"]
    assert rows[0]["employee"]["id"] == world.employee.pk and rows[0]["totals"]["overtime_minutes"] == 60


def test_gestor_nao_decide_fora_do_escopo(world):
    admin, manager = world.tenant.client("company_admin"), world.tenant.client("manager")
    fora = world.make_employee("3", "Fora", world.schedule, unit=world.other_unit)
    item = admin.post(
        world.url("attendance/requests/"),
        {
            "employee_id": fora.pk,
            "kind": "include",
            "occurred_at": local(MON, "08:00").isoformat(),
            "reason": "Inclusão de teste",
        },
        format="json",
    ).json()
    assert (
        manager.post(
            world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json"
        ).status_code
        == 404
    )
    assert PunchAdjustment.objects.get(pk=item["id"]).status == "pending"


def test_ninguem_decide_o_proprio_ponto(world):
    admin, manager = world.tenant.client("company_admin"), world.tenant.client("manager")
    world.employee.access_user = world.tenant.users["manager"]
    world.employee.save()
    item = admin.post(
        world.url("attendance/requests/"),
        {
            "employee_id": world.employee.pk,
            "kind": "include",
            "occurred_at": local(MON, "08:00").isoformat(),
            "reason": "Inclusão de teste",
        },
        format="json",
    ).json()
    r = manager.post(
        world.url(f"attendance/adjustments/{item['id']}/decision/"), {"approve": True}, format="json"
    )
    assert r.status_code == 403


def test_postgresql_protege_instantaneo_e_regras(world):
    from django.db import IntegrityError, connection, transaction

    if connection.vendor != "postgresql":
        pytest.skip("gatilhos só no PostgreSQL")
    admin = world.tenant.client("company_admin")
    closing = admin.post(
        world.url("attendance/closings/"), {"start": MON.isoformat(), "end": MON.isoformat()}, format="json"
    ).json()
    with pytest.raises(IntegrityError), transaction.atomic():
        PeriodClosing.objects.filter(pk=closing["id"]).update(snapshot={})
    with pytest.raises(IntegrityError), transaction.atomic():
        PeriodClosing.objects.filter(pk=closing["id"]).delete()
    admin.post(
        world.url(f"attendance/closings/{closing['id']}/reopen/"),
        {"reason": "Teste de reabertura"},
        format="json",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        PeriodClosing.objects.filter(pk=closing["id"]).update(status="closed")
    admin.post(world.url("attendance/rules/"), {"valid_from": "2027-01-01", "params": {}}, format="json")
    from apps.attendance.models import CalculationRuleSet

    with pytest.raises(IntegrityError), transaction.atomic():
        CalculationRuleSet.objects.all().delete()


def test_nao_fecha_periodo_que_ainda_nao_terminou(world):
    from django.utils import timezone

    today = timezone.localdate().isoformat()
    r = world.tenant.client("company_admin").post(
        world.url("attendance/closings/"), {"start": today, "end": today}, format="json"
    )
    assert r.status_code == 400


# ---------- Correções da revisão: fechamento, funcionários inativos, fuso e concorrência ----------


def close_week(admin, world, **extra):
    body = {"start": MON.isoformat(), "end": (MON + dt.timedelta(days=6)).isoformat(), **extra}
    return admin.post(world.url("attendance/closings/"), body, format="json")


def snapshot_names(closing):
    return {e["employee"]["name"] for e in closing.snapshot["employees"]}


def test_fechamento_recusa_registro_incompleto_sem_excecao(world):
    admin = world.tenant.client("company_admin")
    world.day(MON, "08:00", "12:00", "13:00")  # sem a saída
    r = close_week(admin, world)
    assert r.status_code == 400 and r.json()["code"] == "incomplete_marks"
    assert PeriodClosing.objects.count() == 0
    # Um ajuste aprovado resolve a pendência e o fechamento passa sem exceção.
    manager = world.tenant.client("manager")
    req = manager.post(
        world.url("attendance/requests/"),
        {
            "employee_id": world.employee.pk,
            "kind": "include",
            "occurred_at": local(MON, "17:00").isoformat(),
            "reason": "Esqueceu de bater a saída",
        },
        format="json",
    ).json()
    admin.post(world.url(f"attendance/adjustments/{req['id']}/decision/"), {"approve": True}, format="json")
    r = close_week(admin, world)
    assert r.status_code == 201 and r.json()["exceptions"] is None


def test_funcionario_desativado_continua_no_fechamento_do_periodo(world):
    admin = world.tenant.client("company_admin")
    outro = world.make_employee("2", "Desligado", world.schedule)
    world.day(MON, "08:00", "12:00", "13:00", "17:00", employee=outro)
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    # Desativado antes de fechar o mês: as horas já trabalhadas não podem sumir do fechamento.
    r = admin.patch(world.url(f"employees/{outro.pk}/"), {"is_active": False}, format="json")
    assert r.status_code == 200
    assert close_week(admin, world).status_code == 201
    closing = PeriodClosing.objects.get()
    assert snapshot_names(closing) == {"Maria", "Desligado"}
    worked = {e["employee"]["name"]: e["totals"]["worked_minutes"] for e in closing.snapshot["employees"]}
    assert worked["Desligado"] == 480
    # O resumo do período usa o mesmo critério.
    summary = admin.get(
        world.url("attendance/summary/"),
        {"from": MON.isoformat(), "to": (MON + dt.timedelta(days=6)).isoformat()},
    ).json()
    assert {row["employee"]["name"] for row in summary["results"]} == {"Maria", "Desligado"}


def test_inativo_antigo_sem_movimento_nao_entra_em_periodos_novos(world):
    admin = world.tenant.client("company_admin")
    antigo = world.make_employee("3", "Antigo", world.schedule)
    Employee.objects.filter(pk=antigo.pk).update(
        is_active=False, inactivated_at=timezone.now() - dt.timedelta(days=400)
    )
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    assert close_week(admin, world).status_code == 201
    assert "Antigo" not in snapshot_names(PeriodClosing.objects.get())


def test_inclusao_por_horario_da_unidade_usa_o_fuso_da_lotacao_e_o_dia_seguinte(world):
    manager = world.tenant.client("manager")
    # Turno que começa na segunda e termina na terça: a saída é terça, 06:00 da unidade (UTC-3).
    r = manager.post(
        world.url("attendance/requests/"),
        {
            "employee_id": world.employee.pk,
            "kind": "include",
            "occurred_local": f"{(MON + dt.timedelta(days=1)).isoformat()}T06:00",
            "reason": "Saída do turno noturno",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    item = PunchAdjustment.objects.get()
    assert item.occurred_at == dt.datetime(2026, 10, 20, 9, 0, tzinfo=dt.UTC)  # 06:00 em UTC-3
    assert item.reference_date == MON + dt.timedelta(days=1)
    # Horário com fuso no campo local é recusado: quem digita não escolhe o fuso.
    bad = manager.post(
        world.url("attendance/requests/"),
        {
            "employee_id": world.employee.pk,
            "kind": "include",
            "occurred_local": "2026-10-20T06:00:00-03:00",
            "reason": "Com fuso",
        },
        format="json",
    )
    assert bad.status_code == 400


def test_transferencia_para_outro_fuso_preserva_o_passado(world):
    manaus = Unit.objects.create(company=world.company, name="Manaus", timezone="America/Manaus")
    admin = world.tenant.client("company_admin")
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    before = timesheet(admin, world).json()["days"][0]
    # Transferência 30 dias depois do período consultado não pode deslocar a segunda-feira.
    ops.assign_unit(world.employee, world.company, manaus, None, MON + dt.timedelta(days=30))
    after = timesheet(admin, world).json()["days"][0]
    assert after["marks"] == before["marks"] and after["timezone"] == "America/Sao_Paulo"
    # Transferência no meio do período: cada dia usa o fuso da lotação vigente na data.
    outro = world.make_employee("9", "Transferido", world.schedule)
    ops.assign_unit(outro, world.company, manaus, None, MON + dt.timedelta(days=2))
    world.day(MON, "08:00", "12:00", "13:00", "17:00", employee=outro)
    sheet = timesheet(admin, world, end=MON + dt.timedelta(days=4), employee=outro).json()
    assert [d["timezone"] for d in sheet["days"]][:3] == [
        "America/Sao_Paulo",
        "America/Sao_Paulo",
        "America/Manaus",
    ]
    assert [m["local"] for m in sheet["days"][0]["marks"]] == [m["local"] for m in before["marks"]]
    assert sheet["days"][0]["status"] == "ok"


def test_pedidos_tomam_o_bloqueio_da_empresa_antes_de_verificar_o_fechamento(world):
    """O fechamento trava a empresa; criar pedidos passa pelo mesmo bloqueio, na mesma ordem. Em
    PostgreSQL isso é `FOR NO KEY UPDATE` em `companies_company` antes de consultar os fechamentos."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    manager = world.tenant.client("manager")
    body = {
        "employee_id": world.employee.pk,
        "type": "justification",
        "date": MON.isoformat(),
        "kind": "other",
        "reason": "Teste de bloqueio",
    }
    with CaptureQueriesContext(connection) as ctx:
        r = manager.post(world.url("attendance/requests/"), body, format="json")
    assert r.status_code == 201
    sql = [q["sql"] for q in ctx.captured_queries]
    if connection.vendor == "postgresql":
        lock = next(i for i, q in enumerate(sql) if "companies_company" in q and "FOR NO KEY UPDATE" in q)
        check = next(i for i, q in enumerate(sql) if "attendance_periodclosing" in q)
        assert lock < check


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_pedido_concorrente_ao_fechamento_espera_e_e_recusado(world):
    import threading

    from django.db import connection, transaction

    from apps.attendance import services
    from apps.attendance.models import DayJustification

    if connection.vendor != "postgresql":
        pytest.skip("Concorrência real exige PostgreSQL")
    started, release = threading.Event(), threading.Event()
    result = {}

    def closer():
        try:
            with transaction.atomic():
                services.lock_company(world.company)  # fechamento em andamento, ainda sem confirmar
                started.set()
                release.wait(10)
                PeriodClosing.objects.create(
                    company=world.company,
                    start=MON,
                    end=MON + dt.timedelta(days=6),
                    snapshot={"employees": []},
                    snapshot_sha256="0" * 64,
                    engine_version="t",
                    closed_by=world.tenant.users["company_admin"],
                )
        finally:
            connection.close()

    def requester():
        try:
            services.request_justification(
                company=world.company,
                employee=world.employee,
                user=world.tenant.users["manager"],
                date=MON,
                kind="other",
                reason="Pedido concorrente",
            )
            result["status"] = "aceito"
        except Exception as exc:  # noqa: BLE001
            result["status"] = f"recusado: {exc}"
        finally:
            connection.close()

    t1 = threading.Thread(target=closer)
    t1.start()
    assert started.wait(10)
    t2 = threading.Thread(target=requester)
    t2.start()
    t2.join(1.0)
    assert t2.is_alive()  # o pedido espera o fechamento terminar
    release.set()
    t1.join(10)
    t2.join(10)
    assert result["status"].startswith("recusado") and "fechado" in result["status"].lower()
    assert DayJustification.objects.filter(reason="Pedido concorrente").count() == 0


def test_lista_de_pedidos_e_paginada_sem_perder_itens(world):
    from apps.attendance.models import DayJustification

    manager = world.tenant.client("manager")
    admin_user = world.tenant.users["company_admin"]
    for i in range(230):
        DayJustification.objects.create(
            company=world.company,
            employee=world.employee,
            date=MON,
            kind="other",
            reason=f"Pedido {i}",
            requested_by=admin_user,
        )
    first = manager.get(world.url("attendance/requests/"), {"page_size": 200}).json()
    assert first["count"] == 230 and len(first["results"]) == 200 and first["next"] == "?page=2"
    second = manager.get(world.url("attendance/requests/"), {"page_size": 200, "page": 2}).json()
    assert len(second["results"]) == 30 and second["next"] is None and second["previous"] == "?page=1"
    ids = {r["id"] for r in first["results"]} | {r["id"] for r in second["results"]}
    assert len(ids) == 230  # nenhum pedido some nem se repete entre as páginas
    assert manager.get(world.url("attendance/requests/"), {"page_size": 1000}).status_code == 400
    # Filtro por período usado pelo fechamento guiado.
    other = manager.get(world.url("attendance/requests/"), {"from": "2020-01-01", "to": "2020-01-31"}).json()
    assert other["count"] == 0


# ---------- Permissões separadas: consultar, solicitar e decidir ----------


def test_gestor_somente_consulta_nao_decide_nem_solicita(world):
    admin = world.tenant.client("company_admin")
    manager = world.tenant.client("manager")
    membership = world.tenant.memberships["manager"]
    body = {
        "employee_id": world.employee.pk,
        "type": "justification",
        "date": MON.isoformat(),
        "kind": "other",
        "reason": "Pedido de teste",
    }
    assert manager.post(world.url("attendance/requests/"), body, format="json").status_code == 201
    created = admin.post(world.url("attendance/requests/"), body, format="json")  # quem pede não decide
    assert created.status_code == 201
    # O administrador libera só a consulta: o gestor continua vendo, mas não decide nem solicita.
    r = admin.patch(
        world.url(f"members/{membership.pk}/"),
        {"can_decide_requests": False, "can_request_adjustments": False},
        format="json",
    )
    assert r.status_code == 200 and r.json()["can_decide_requests"] is False
    assert manager.get(world.url("attendance/requests/")).json()["count"] == 2
    assert manager.post(world.url("attendance/requests/"), body, format="json").status_code == 403
    decide = manager.post(
        world.url(f"attendance/justifications/{created.json()['id']}/decision/"),
        {"approve": True},
        format="json",
    )
    assert decide.status_code == 403
    statuses = {r["status"] for r in admin.get(world.url("attendance/requests/")).json()["results"]}
    assert statuses == {"pending"}
    # Pode receber só a decisão, ou só a solicitação, independentemente.
    admin.patch(world.url(f"members/{membership.pk}/"), {"can_decide_requests": True}, format="json")
    assert (
        manager.post(
            world.url(f"attendance/justifications/{created.json()['id']}/decision/"),
            {"approve": False, "note": "Sem documento"},
            format="json",
        ).status_code
        == 200
    )
    assert manager.post(world.url("attendance/requests/"), body, format="json").status_code == 403
    # O gestor não altera as próprias permissões; administrador não é limitado pelas marcas.
    assert (
        manager.patch(
            world.url(f"members/{membership.pk}/"), {"can_decide_requests": True}, format="json"
        ).status_code
        == 403
    )
    assert admin.post(world.url("attendance/requests/"), body, format="json").status_code == 201


# ---------- Banco de horas ----------


def bank_url(world, suffix=""):
    return world.url(f"attendance/employees/{world.employee.pk}/hour-bank/{suffix}")


def test_banco_de_horas_lancamentos_estorno_e_saldo_dos_periodos_fechados(world):
    from apps.attendance.models import HourBankEntry

    admin, manager = world.tenant.client("company_admin"), world.tenant.client("manager")
    start = MON - dt.timedelta(days=7)
    # Sem saldo inicial o saldo do período fechado ainda não entra: não há data de partida.
    world.day(MON, "08:00", "12:00", "13:00", "18:00")  # +60 min de extras
    assert close_week(admin, world).status_code == 201
    assert admin.get(bank_url(world)).json()["balance_minutes"] == 0
    # Saldo inicial, depois abatimento e pagamento; regras de sinal por tipo.
    body = {
        "kind": "opening",
        "date": start.isoformat(),
        "minutes": 300,
        "reason": "Saldo levado do sistema anterior",
    }
    assert admin.post(bank_url(world), body, format="json").status_code == 201
    assert admin.post(bank_url(world), body, format="json").status_code == 400  # só um saldo inicial ativo
    ruim = {"kind": "offset", "date": MON.isoformat(), "minutes": 120, "reason": "Folga compensada"}
    assert admin.post(bank_url(world), ruim, format="json").status_code == 400  # abatimento é negativo
    ok = {**ruim, "minutes": -120}
    assert admin.post(bank_url(world), ok, format="json").status_code == 201
    assert admin.post(bank_url(world), {**ok, "reason": "x"}, format="json").status_code == 400
    assert admin.post(bank_url(world), {**ok, "minutes": 0}, format="json").status_code == 400
    bank = admin.get(bank_url(world)).json()
    snap = next(
        e
        for e in PeriodClosing.objects.get().snapshot["employees"]
        if e["employee"]["id"] == world.employee.pk
    )["totals"]["balance_minutes"]  # +60 de extras na segunda e 4 faltas na semana
    assert bank["ledger_minutes"] == 300 - 120 and bank["accrued_closed_minutes"] == snap
    assert bank["balance_minutes"] == 180 + snap and bank["closed_periods"][0]["balance_minutes"] == snap
    assert "convenção coletiva" in bank["notice"]
    # Estorno corrige o engano sem apagar: o lançamento original continua no livro.
    offset = next(e for e in bank["entries"] if e["kind"] == "offset")
    r = admin.post(
        bank_url(world, f"{offset['id']}/reverse/"), {"reason": "Lançado por engano"}, format="json"
    )
    assert r.status_code == 201 and r.json()["ledger_minutes"] == 300
    assert (
        admin.post(
            bank_url(world, f"{offset['id']}/reverse/"), {"reason": "De novo"}, format="json"
        ).status_code
        == 400
    )
    assert HourBankEntry.objects.filter(employee=world.employee).count() == 3
    # Lançamentos são imutáveis.
    entry = HourBankEntry.objects.first()
    entry.minutes = 1
    with pytest.raises(Exception):  # noqa: B017, PT011
        entry.save()
    with pytest.raises(Exception):  # noqa: B017, PT011
        entry.delete()
    # Gestor do escopo consulta, mas não lança nem estorna; funcionário vê o próprio e não o de outro.
    assert manager.get(bank_url(world)).status_code == 200
    assert manager.post(bank_url(world), ok, format="json").status_code == 403
    mine = world.tenant.client("employee").get(world.url("me/hour-bank/"))
    assert mine.status_code == 200 and mine.json()["employee"]["id"] == world.employee.pk


def test_banco_de_horas_isolado_entre_empresas(world, tenant_b):
    assert tenant_b.client("company_admin").get(bank_url(world)).status_code == 404
    outro = world.make_employee("8", "Fora", world.schedule, unit=world.other_unit)
    manager = world.tenant.client("manager")
    assert manager.get(world.url(f"attendance/employees/{outro.pk}/hour-bank/")).status_code == 404


# ---------- Troca retroativa de jornada/lotação e intervalo inválido ----------


def test_jornada_e_lotacao_retroativas_nao_alteram_periodo_fechado(world):
    admin = world.tenant.client("company_admin")
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    assert close_week(admin, world).status_code == 201
    other = WorkSchedule.objects.create(company=world.company, name="Nova")
    ScheduleDay.objects.create(
        schedule=other, weekday=0, start_time=dt.time(9), end_time=dt.time(18), break_minutes=60
    )
    url = world.url(f"employees/{world.employee.pk}/schedules/")
    inside = admin.post(
        url, {"schedule": other.pk, "valid_from": (MON + dt.timedelta(days=2)).isoformat()}, format="json"
    )
    assert inside.status_code == 400 and "echado" in str(inside.json())
    unit_url = world.url(f"employees/{world.employee.pk}/assignments/")
    moved = admin.post(
        unit_url,
        {"unit": world.other_unit.pk, "valid_from": (MON + dt.timedelta(days=1)).isoformat()},
        format="json",
    )
    assert moved.status_code == 400 and "echado" in str(moved.json())
    # A apuração fechada continua igual (nada foi inserido).
    assert world.employee.schedule_assignments.count() == 1 and world.employee.assignments.count() == 1
    # Depois do fim do período fechado a troca é permitida; reabrir também libera o passado.
    ok = admin.post(
        url, {"schedule": other.pk, "valid_from": (MON + dt.timedelta(days=30)).isoformat()}, format="json"
    )
    assert ok.status_code == 201
    closing_id = PeriodClosing.objects.get().pk
    admin.post(
        world.url(f"attendance/closings/{closing_id}/reopen/"), {"reason": "Corrigir jornada"}, format="json"
    )
    again = admin.post(
        url, {"schedule": other.pk, "valid_from": (MON + dt.timedelta(days=40)).isoformat()}, format="json"
    )
    assert again.status_code == 201


@pytest.mark.parametrize(
    ("start", "end", "brk", "ok"),
    [
        ("08:00", "12:00", 480, False),  # intervalo maior que a jornada
        ("08:00", "12:00", 240, False),  # intervalo igual à jornada: zero horas previstas
        ("08:00", "12:00", 30, True),
        ("22:00", "02:00", 240, False),  # cruza a meia-noite: 4 h de duração
        ("22:00", "06:00", 60, True),
        ("22:00", "06:00", 480, False),
    ],
)
def test_intervalo_precisa_caber_na_duracao_da_jornada(world, start, end, brk, ok):
    admin = world.tenant.client("company_admin")
    body = {
        "name": f"J {start}-{end}-{brk}",
        "days": [{"weekday": 0, "start_time": start, "end_time": end, "break_minutes": brk}],
    }
    r = admin.post(world.url("schedules/"), body, format="json")
    assert (r.status_code == 201) is ok, r.content
    if not ok:
        assert "intervalo" in str(r.json()).lower()
