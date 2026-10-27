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
    assert admin.post(world.url("attendance/closings/"), close, format="json").status_code == 201


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
    assert len(employee.get(world.url("me/requests/")).json()) == 1
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
