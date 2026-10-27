import datetime as dt

import pytest

from apps.attendance.tests.test_api import MON, World
from apps.fiscal import afd
from apps.fiscal.models import GeneratedFile
from apps.timeclock import hashing

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a, settings):
    settings.REP_P_INPI_REGISTRATION = "BR512026000001"
    settings.REP_P_DEVELOPER_TAX_ID = "11222333000181"
    w = World(tenant_a)
    c = w.company
    c.legal_name, c.tax_id_type, c.tax_id = "Empresa Ltda", "CNPJ", "11222333000181"
    c.save()
    w.employee.cpf = "52998224725"
    w.employee.save()
    return w


def test_crc16_vetor_conhecido():
    # CRC-16/ARC de "123456789" = 0xBB3D (vetor de referência da variante).
    assert afd.crc16(b"123456789") == "BB3D"


def test_afd_estrutura_e_hash_conferem(world):
    records = world.day(MON, "08:00", "12:00", "13:00", "17:00")
    r = world.tenant.client("company_admin").get(
        world.url("fiscal/afd/"), {"unit": world.unit.pk, "from": MON.isoformat(), "to": MON.isoformat()}
    )
    assert r.status_code == 200, r.content
    lines = r.content.decode("latin-1").split("\r\n")
    assert lines[-1] == ""
    head, body, trailer = lines[0], lines[1:-2], lines[-2]
    assert len(head) == 302 and head[:10] == "0000000001" and head[10] == "1"
    assert head[11:25] == "11222333000181" and head[189:206].rstrip() == "BR512026000001"
    assert head[206:216] == "2026-10-19" and head[216:226] == "2026-10-19"
    assert head[-4:] == afd.crc16(head[:-4].encode("latin-1"))
    assert [len(x) for x in body] == [137] * 4
    first = body[0]
    assert first[:9] == f"{records[0].nsr:09d}" and first[9] == "7" and first[34:46] == "052998224725"
    assert first[73:] == records[0].record_hash
    # O hash do tipo 7 é recalculável a partir dos próprios campos do arquivo + hash anterior.
    assert hashing.hashlib.sha256((first[:73]).encode("ascii")).hexdigest() == records[0].record_hash
    second = body[1]
    assert hashing.hashlib.sha256((second[:73] + first[73:]).encode("ascii")).hexdigest() == second[73:]
    assert (
        len(trailer) == 64
        and trailer[:9] == "999999999"
        and trailer[54:63] == "000000004"
        and trailer[63] == "9"
    )
    assert GeneratedFile.objects.get().sha256 == r["X-Noxora-Sha256"]


def test_afd_so_administrador_e_unidade_obrigatoria(world, tenant_b):
    q = {"unit": world.unit.pk, "from": MON.isoformat(), "to": MON.isoformat()}
    assert world.tenant.client("manager").get(world.url("fiscal/afd/"), q).status_code == 403
    assert tenant_b.client("company_admin").get(world.url("fiscal/afd/"), q).status_code == 404
    assert (
        world.tenant.client("company_admin").get(world.url("fiscal/afd/"), {**q, "unit": ""}).status_code
        == 400
    )


def test_exportacao_para_folha_a_partir_do_fechamento(world):
    admin = world.tenant.client("company_admin")
    world.day(MON, "08:00", "12:00", "13:00", "19:00")
    tue = MON + dt.timedelta(days=1)
    closing = admin.post(
        world.url("attendance/closings/"), {"start": MON.isoformat(), "end": tue.isoformat()}, format="json"
    ).json()
    bad = admin.post(
        world.url("fiscal/payroll-profiles/"),
        {"name": "X", "event_codes": {"nao_existe": "1"}},
        format="json",
    )
    assert bad.status_code == 400
    csv_profile = admin.post(
        world.url("fiscal/payroll-profiles/"),
        {"name": "Folha CSV", "event_codes": {"overtime_50": "150", "absences": "400", "worked": "001"}},
        format="json",
    ).json()
    text = admin.get(
        world.url("fiscal/payroll-export/"), {"profile": csv_profile["id"], "closing": closing["id"]}
    ).content.decode("utf-8-sig")
    assert "1;Maria;150;overtime_50;Horas extras 50%;2:00;horas;2026-10-19;2026-10-20" in text
    assert "1;Maria;400;absences;Faltas (dias);1;dias" in text
    fixed = admin.post(
        world.url("fiscal/payroll-profiles/"),
        {"name": "TXT", "file_format": "fixed", "event_codes": {"overtime_50": "150"}},
        format="json",
    ).json()
    line = admin.get(
        world.url("fiscal/payroll-export/"), {"profile": fixed["id"], "closing": closing["id"]}
    ).content.decode()
    assert line == "         1   150202610192026102000200\r\n"
    assert GeneratedFile.objects.filter(kind="payroll").count() == 2
    assert (
        admin.get(world.url("fiscal/payroll-export/"), {"profile": fixed["id"], "closing": 999}).status_code
        == 404
    )
