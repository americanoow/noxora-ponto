import datetime

import pytest
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.companies.models import Membership
from apps.operations import importing, services
from apps.operations.models import Employee, WorkSchedule
from apps.operations.tests.test_operations import (
    DAYS,
    make_employee,
    make_sector,
    make_unit,
    post_import,
    url,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "text",
    [
        "matricula,nome,nome\n1,A,B",
        "matricula,nome\n1,A,extra",
        "matricula,nome\n1",
        'matricula,nome\n1,"sem fim',
        "matricula,nome\n1," + "a" * 140000,
        "matricula,nome\n" + "é" * 500000,
    ],
    ids=["duplicate", "extra", "missing", "quotes", "field_limit", "byte_limit"],
)
def test_csv_malformed_returns_400(tenant_a, text):
    response = post_import(tenant_a.client("company_admin"), tenant_a.company, text)
    assert response.status_code == 400
    assert Employee.objects.count() == 0


def test_csv_bom_quotes_and_physical_lines(tenant_a):
    text = '\ufeffmatricula;nome;cpf\r\n1;"Ana; Maria\nSilva";\r\n\r\n2;Bia;123\r\n'
    response = post_import(tenant_a.client("company_admin"), tenant_a.company, text).json()
    assert response["valid"] == 1
    assert response["errors"][0]["line"] == 5


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t=", "\r="])
def test_csv_formula_is_rejected_without_echo(tenant_a, prefix):
    text = f'matricula,nome\n1,"{prefix}SEGREDO"'
    response = post_import(tenant_a.client("company_admin"), tenant_a.company, text).json()
    assert response["valid"] == 0
    assert response["errors"][0]["field"] == "nome"
    assert "SEGREDO" not in str(response)


def test_import_requires_preview_of_same_content_and_session(tenant_a):
    admin = tenant_a.client("company_admin")
    text = "matricula,nome\n1,Ana"
    assert post_import(admin, tenant_a.company, text, True).status_code == 400
    assert post_import(admin, tenant_a.company, text).status_code == 200
    assert post_import(admin, tenant_a.company, text + " Maria", True).status_code == 400
    other_session = tenant_a.client("company_admin")
    assert post_import(other_session, tenant_a.company, text, True).status_code == 400
    assert post_import(admin, tenant_a.company, text, True).json()["committed"] == 1


def test_import_race_rolls_back_without_database_details(tenant_a, monkeypatch):
    admin = tenant_a.client("company_admin")
    text = "matricula,nome\n1,Ana"
    post_import(admin, tenant_a.company, text)

    def conflict(company, records):
        Employee.objects.create(company=company, registration="1", full_name="Ana")
        raise IntegrityError("CPF SECRETO")

    monkeypatch.setattr(importing, "commit", conflict)
    response = post_import(admin, tenant_a.company, text, True)
    assert response.status_code == 400
    assert "SECRETO" not in str(response.json())
    assert Employee.objects.count() == 0


@pytest.mark.parametrize("value", ["²", "9" * 100, "-1", "abc"])
def test_malformed_filters_do_not_crash(tenant_a, value):
    admin = tenant_a.client("company_admin")
    for path in ("employees/", "sectors/"):
        response = admin.get(url(tenant_a.company, path), {"unit": value})
        assert response.status_code == 200
    assert admin.get(url(tenant_a.company, "employees/"), {"sector": value}).status_code == 200


def test_manager_scope_current_dates_search_filters_and_details(tenant_a, tenant_b, monkeypatch):
    company = tenant_a.company
    first, second = make_unit(company, "A"), make_unit(company, "B")
    sector = make_sector(first)
    employee = make_employee(company, "1", unit=first, sector=sector)
    services.assign_unit(employee, company, second, None, datetime.date(2030, 1, 1))
    future = make_employee(company, "2", unit=first, start=datetime.date(2030, 1, 1))
    outsider = make_employee(tenant_b.company, "3")
    tenant_a.memberships["manager"].scope_sectors.add(sector)
    monkeypatch.setattr(services, "today", lambda: datetime.date(2029, 12, 31))
    client = tenant_a.client("manager")
    base = url(company, "employees/")
    assert client.get(base, {"q": "Fulano", "page_size": 1}).json()["count"] == 1
    assert client.get(base, {"unit": second.pk}).json()["count"] == 0
    for hidden in (future, outsider):
        for suffix in ("", "assignments/", "schedules/"):
            assert client.get(f"{base}{hidden.pk}/{suffix}").status_code == 404
    monkeypatch.setattr(services, "today", lambda: datetime.date(2030, 1, 1))
    assert client.get(base).json()["count"] == 0
    assert client.get(f"{base}{employee.pk}/").status_code == 404


def test_manager_schedule_catalog_is_scoped(tenant_a):
    company = tenant_a.company
    unit = make_unit(company)
    employee = make_employee(company, "1", unit=unit)
    used = WorkSchedule.objects.create(company=company, name="Usada")
    hidden = WorkSchedule.objects.create(company=company, name="Privada")
    services.assign_schedule(employee, company, used, datetime.date(2020, 1, 1))
    client = tenant_a.client("manager")
    base = url(company, "schedules/")
    assert client.get(base).json() == []
    assert client.get(f"{base}{used.pk}/").status_code == 404
    tenant_a.memberships["manager"].scope_units.add(unit)
    assert [s["id"] for s in client.get(base).json()] == [used.pk]
    assert client.get(f"{base}{hidden.pk}/").status_code == 404


def test_schedule_partial_days_returns_400_and_preserves_days(tenant_a):
    client = tenant_a.client("company_admin")
    base = url(tenant_a.company, "schedules/")
    schedule = client.post(base, {"name": "A", "days": DAYS}, format="json").json()
    for days in ([{}], [{"weekday": 1}], [{"start_time": "08:00", "end_time": "17:00"}]):
        assert client.patch(f"{base}{schedule['id']}/", {"days": days}, format="json").status_code == 400
    assert len(client.get(f"{base}{schedule['id']}/").json()["days"]) == 5


def test_services_recheck_inactive_targets(tenant_a):
    company = tenant_a.company
    unit = make_unit(company)
    employee = make_employee(company, "1")
    schedule = WorkSchedule.objects.create(company=company, name="A")
    WorkSchedule.objects.filter(pk=schedule.pk).update(is_active=False)
    type(unit).objects.filter(pk=unit.pk).update(is_active=False)
    for assign, target in ((services.assign_schedule, schedule), (services.assign_unit, unit)):
        args = (employee, company, target)
        if target == unit:
            args += (None,)
        with pytest.raises(ValidationError):
            assign(*args, datetime.date(2020, 1, 1))
    assert not employee.assignments.exists()
    assert not employee.schedule_assignments.exists()


def test_employee_and_member_list_query_count_is_constant(tenant_a, django_assert_num_queries):
    company = tenant_a.company
    unit = make_unit(company)
    client = tenant_a.client("company_admin")
    make_employee(company, "1", unit=unit)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    counts = {}
    for path in ("employees/", "members/"):
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url(company, path)).status_code == 200
        counts[path] = len(queries)
    for number in range(2, 20):
        make_employee(company, str(number), unit=unit)
    for number in range(5):
        user = User.objects.create(email=f"extra{number}@test.test")
        Membership.objects.create(company=company, user=user, role="manager")
    for path in ("employees/", "members/"):
        with django_assert_num_queries(counts[path]):
            assert client.get(url(company, path)).status_code == 200


@pytest.mark.parametrize("role", ["manager", "employee"])
def test_all_operational_writes_deny_non_admin(tenant_a, role):
    company = tenant_a.company
    unit = make_unit(company)
    sector = make_sector(unit)
    employee = make_employee(company, "1", unit=unit)
    schedule = WorkSchedule.objects.create(company=company, name="A")
    client = tenant_a.client(role)
    for method, path in (
        ("post", "units/"),
        ("patch", f"units/{unit.pk}/"),
        ("post", "sectors/"),
        ("patch", f"sectors/{sector.pk}/"),
        ("post", "employees/"),
        ("patch", f"employees/{employee.pk}/"),
        ("post", f"employees/{employee.pk}/assignments/"),
        ("post", f"employees/{employee.pk}/schedules/"),
        ("post", "schedules/"),
        ("patch", f"schedules/{schedule.pk}/"),
        ("post", "employees/import/"),
    ):
        assert getattr(client, method)(url(company, path), {}, format="json").status_code == 403


def test_cross_company_history_writes_and_schedule_updates_are_hidden(tenant_a, tenant_b):
    unit = make_unit(tenant_b.company)
    sector = make_sector(unit)
    employee = make_employee(tenant_b.company, "1", unit=unit)
    schedule = WorkSchedule.objects.create(company=tenant_b.company, name="B")
    client = tenant_a.client("company_admin")
    for suffix in ("assignments/", "schedules/"):
        path = url(tenant_a.company, f"employees/{employee.pk}/{suffix}")
        assert client.get(path).status_code == 404
        assert client.post(path, {}, format="json").status_code == 404
    assert (
        client.patch(
            url(tenant_a.company, f"schedules/{schedule.pk}/"), {"name": "A"}, format="json"
        ).status_code
        == 404
    )
    own_unit = make_unit(tenant_a.company)
    own_employee = make_employee(tenant_a.company, "1")
    response = client.post(
        url(tenant_a.company, f"employees/{own_employee.pk}/assignments/"),
        {"unit": own_unit.pk, "sector": sector.pk, "valid_from": "2020-01-01"},
        format="json",
    )
    assert response.status_code == 400
    response = client.patch(
        url(tenant_a.company, f"members/{tenant_a.memberships['manager'].pk}/"),
        {"scope_unit_ids": [own_unit.pk], "scope_sector_ids": [sector.pk]},
        format="json",
    )
    assert response.status_code == 400
    assert not tenant_a.memberships["manager"].scope_units.exists()


def test_create_ignores_mass_assignment_and_delete_is_disabled(tenant_a, tenant_b):
    client = tenant_a.client("company_admin")
    response = client.post(
        url(tenant_a.company, "employees/"),
        {
            "registration": "1",
            "full_name": "Ana",
            "company": tenant_b.company.pk,
            "is_active": False,
            "access_user": tenant_b.users["employee"].pk,
            "inactivated_at": "2020-01-01",
            "id": 12345,
        },
        format="json",
    )
    assert response.status_code == 201
    employee = Employee.objects.get(pk=response.json()["id"])
    assert employee.company_id == tenant_a.company.pk and employee.is_active
    assert employee.access_user_id is None and employee.inactivated_at is None
    assert client.delete(url(tenant_a.company, f"employees/{employee.pk}/")).status_code == 405
    assert Employee.objects.filter(pk=employee.pk).exists()


def test_schedule_intervals_close_and_reject_equal_or_retroactive(tenant_a):
    company = tenant_a.company
    employee = make_employee(company, "1")
    schedule = WorkSchedule.objects.create(company=company, name="A")
    start = datetime.date(2020, 1, 1)
    future = services.today() + datetime.timedelta(days=30)
    first = services.assign_schedule(employee, company, schedule, start)
    second = services.assign_schedule(employee, company, schedule, future)
    for invalid in (start, future, future - datetime.timedelta(days=1)):
        with pytest.raises(ValidationError):
            services.assign_schedule(employee, company, schedule, invalid)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.valid_to == future - datetime.timedelta(days=1)
    assert second.valid_to is None
    assert employee.schedule_assignments.count() == 2
