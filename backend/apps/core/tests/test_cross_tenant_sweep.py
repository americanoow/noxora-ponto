"""Varredura de isolamento: TODA rota sob /api/companies/<id>/ chamada por usuários de OUTRA empresa,
em todos os métodos, com ids de objetos reais da empresa alvo, nunca devolve sucesso nem dados."""

import re

import pytest
from django.urls import get_resolver

from apps.attendance.tests.test_api import MON, World

pytestmark = pytest.mark.django_db

METHODS = ("get", "post", "put", "patch", "delete")


def _routes():
    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)

    return sorted(
        {r for r in walk(get_resolver().url_patterns) if r.startswith("api/companies/<int:company_id>/")}
    )


def test_nenhuma_rota_vaza_para_outra_empresa(tenant_a, tenant_b):
    w = World(tenant_a)
    records = w.day(MON, "08:00", "12:00")
    admin = tenant_a.client("company_admin")
    closing = admin.post(
        w.url("attendance/closings/"), {"start": MON.isoformat(), "end": MON.isoformat()}, format="json"
    ).json()
    ids = {
        "company_id": w.company.pk,
        "employee_id": w.employee.pk,
        "unit_id": w.unit.pk,
        "device_id": w.device.pk,
        "record_id": records[0].pk,
        "closing_id": closing["id"],
        "schedule_id": w.schedule.pk,
        "member_id": tenant_a.memberships["employee"].pk,
        "sector_id": 1,
        "holiday_id": 1,
        "item_id": 1,
        "entry_id": 1,
        "kind": "adjustments",
    }
    query = f"?employee={w.employee.pk}&from={MON}&to={MON}&unit={w.unit.pk}"
    leaks = []
    for route in _routes():
        path = "/" + re.sub(r"<(?:int|str):(\w+)>", lambda m: str(ids[m.group(1)]), route)
        for role in ("company_admin", "manager", "employee"):
            client = tenant_b.client(role)
            for method in METHODS:
                r = getattr(client, method)(path + (query if method == "get" else ""), {}, format="json")
                # PATCH da empresa é exclusivo da plataforma: 403 antes de qualquer consulta, igual para
                # empresas existentes ou não (não revela existência).
                platform_only = method == "patch" and route == "api/companies/<int:company_id>/"
                if r.status_code not in (404, 405) and not (platform_only and r.status_code == 403):
                    leaks.append((method.upper(), path, role, r.status_code))
    assert leaks == []
