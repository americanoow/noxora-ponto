import datetime as dt

import pytest

from apps.attendance.tests.test_api import MON, World, local
from apps.audit.models import AuditLog
from apps.reports.exports import csv_bytes, safe_cell

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a):
    w = World(tenant_a)
    w.employee.cpf = "52998224725"
    w.employee.save()
    return w


def test_portal_ultimas_48h_e_comprovante_pdf(world, tenant_b):
    from django.utils import timezone

    recent = world.punch(timezone.now() - dt.timedelta(hours=1))
    world.punch(timezone.now() - dt.timedelta(days=5))
    employee = world.tenant.client("employee")
    rows = employee.get(world.url("me/punches/")).json()["results"]
    assert [r["id"] for r in rows] == [recent.pk]
    assert rows[0]["cpf"].startswith("***")
    receipt = employee.get(world.url(f"me/punches/{recent.pk}/receipt/")).json()
    assert receipt["worker"]["cpf"] == "529.982.247-25" and receipt["signed"] is False
    pdf = employee.get(world.url(f"me/punches/{recent.pk}/receipt/"), {"format": "pdf"})
    assert (
        pdf.status_code == 200
        and pdf["Content-Type"] == "application/pdf"
        and pdf.content.startswith(b"%PDF")
    )
    other = world.make_employee("9", "Outro", world.schedule)
    alheia = world.punch(timezone.now() - dt.timedelta(hours=1), employee=other)
    assert employee.get(world.url(f"me/punches/{alheia.pk}/receipt/")).status_code == 404
    assert tenant_b.client("employee").get(world.url("me/punches/")).status_code == 404


def test_espelho_pdf_e_csv_com_auditoria(world):
    world.day(MON, "08:00", "12:00", "13:00", "18:00")
    admin = world.tenant.client("company_admin")
    q = {"employee": world.employee.pk, "from": MON.isoformat(), "to": MON.isoformat()}
    pdf = admin.get(world.url("reports/timesheet/"), {**q, "format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv = admin.get(world.url("reports/timesheet/"), {**q, "format": "csv"})
    text = csv.content.decode("utf-8-sig")
    assert text.splitlines()[1].startswith("2026-10-19;08:00 12:00 13:00 18:00;480;540;60;50")
    assert AuditLog.objects.filter(action="report.timesheet_exported").count() == 2
    assert admin.get(world.url("reports/timesheet/"), {**q, "format": "xls"}).status_code == 400
    assert world.tenant.client("employee").get(world.url("reports/timesheet/"), q).status_code == 403


def test_resumo_e_marcacoes_csv(world):
    world.day(MON, "08:00", "12:00", "13:00", "18:00")
    q = {"from": MON.isoformat(), "to": MON.isoformat()}
    summary = (
        world.tenant.client("manager").get(world.url("reports/summary.csv"), q).content.decode("utf-8-sig")
    )
    assert "1;Maria;480;540;60;0" in summary
    manager_csv = (
        world.tenant.client("manager")
        .get(world.url("reports/time-records.csv"), q)
        .content.decode("utf-8-sig")
    )
    assert "***.***.***-25" in manager_csv and "52998224725" not in manager_csv
    admin_csv = (
        world.tenant.client("company_admin")
        .get(world.url("reports/time-records.csv"), q)
        .content.decode("utf-8-sig")
    )
    assert "52998224725" in admin_csv and admin_csv.count("\r\n") == 5


def test_ciencia_do_espelho_fechado(world):
    world.day(MON, "08:00", "12:00", "13:00", "17:00")
    admin, employee = world.tenant.client("company_admin"), world.tenant.client("employee")
    closing = admin.post(
        world.url("attendance/closings/"), {"start": MON.isoformat(), "end": MON.isoformat()}, format="json"
    ).json()
    mine = employee.get(world.url("me/closings/")).json()
    assert mine[0]["id"] == closing["id"] and mine[0]["acknowledged_at"] is None
    r = employee.post(
        world.url(f"me/closings/{closing['id']}/acknowledge/"), {"comment": "De acordo"}, format="json"
    )
    assert r.status_code == 201
    assert (
        employee.post(world.url(f"me/closings/{closing['id']}/acknowledge/"), {}, format="json").status_code
        == 400
    )
    acks = admin.get(world.url(f"attendance/closings/{closing['id']}/acknowledgements/")).json()
    assert acks[0]["matches_snapshot"] is True and acks[0]["comment"] == "De acordo"
    # Espelho do período exato fechado sai do instantâneo, mesmo com marcação nova depois.
    world.punch(local(MON, "19:00"))
    csv = admin.get(
        world.url("reports/timesheet/"),
        {"employee": world.employee.pk, "from": MON.isoformat(), "to": MON.isoformat(), "format": "csv"},
    ).content.decode("utf-8-sig")
    assert "19:00" not in csv
    pdf = employee.get(world.url("me/timesheet.pdf"), {"from": MON.isoformat(), "to": MON.isoformat()})
    assert pdf.content.startswith(b"%PDF")


def test_csv_neutraliza_formulas():
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and safe_cell("-1") == "'-1" and safe_cell(5) == "5"
    assert csv_bytes(["a"], [["@x"]]).decode("utf-8-sig") == "a\r\n'@x\r\n"
