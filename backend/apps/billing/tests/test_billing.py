import datetime as dt
import json

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing import services
from apps.billing.gateways import SandboxGateway
from apps.billing.models import Invoice, Plan, Subscription, WebhookEvent
from apps.operations.models import Employee

pytestmark = pytest.mark.django_db


def start(tenant, code="essencial", trial=0):
    return services.start_subscription(
        company=tenant.company, plan=Plan.objects.get(code=code), trial_days=trial
    )


def expire(sub):
    Subscription.objects.filter(pk=sub.pk).update(current_period_end=timezone.now() - dt.timedelta(minutes=1))


def webhook(body, signature):
    return APIClient().post(
        "/api/billing/webhooks/sandbox/",
        body,
        content_type="application/json",
        HTTP_X_NOXORA_SIGNATURE=signature,
    )


def test_planos_padrao_e_painel_da_empresa(tenant_a):
    assert set(Plan.objects.values_list("code", flat=True)) >= {"essencial", "profissional", "empresarial"}
    admin = tenant_a.client("company_admin")
    body = admin.get(f"/api/companies/{tenant_a.company.pk}/billing/").json()
    assert body["subscription"] is None and len(body["plans"]) == 3 and "nunca bloqueia" in body["notice"]
    r = admin.post(
        f"/api/companies/{tenant_a.company.pk}/billing/plan/", {"plan_code": "essencial"}, format="json"
    )
    assert r.status_code == 200 and r.json()["status"] == "trialing" and r.json()["sandbox"] is True
    assert tenant_a.client("manager").get(f"/api/companies/{tenant_a.company.pk}/billing/").status_code == 403


def test_ciclo_fatura_pagamento_e_webhook_idempotente(tenant_a):
    sub = start(tenant_a)
    Employee.objects.create(company=tenant_a.company, registration="1", full_name="A")
    expire(sub)
    call_command("run_billing")
    invoice = Invoice.objects.get()
    plan = sub.plan
    assert invoice.amount_cents == plan.base_price_cents + plan.price_per_employee_cents
    call_command("run_billing")  # idempotente: período já renovado
    assert Invoice.objects.count() == 1
    gateway = SandboxGateway()
    body, sig = gateway.simulate_event("invoice.payment_failed", invoice.gateway_invoice_id)
    assert webhook(body, sig).status_code == 200
    sub.refresh_from_db()
    assert sub.status == "past_due"
    assert webhook(body, "sha256=errada").status_code == 403
    assert (
        webhook(body, sig).json()["result"] == "pagamento falhou"
    )  # reenvio: mesmo resultado, sem reprocessar
    assert WebhookEvent.objects.count() == 1
    paid, sig2 = gateway.simulate_event("invoice.paid", invoice.gateway_invoice_id)
    webhook(paid, sig2)
    sub.refresh_from_db()
    invoice.refresh_from_db()
    assert sub.status == "active" and invoice.status == "paid"
    late_fail, sig3 = gateway.simulate_event("invoice.payment_failed", invoice.gateway_invoice_id)
    assert webhook(late_fail, sig3).json()["result"] == "ignorado: fatura já paga"


def test_suspensao_restringe_cadastro_mas_nao_o_ponto(tenant_a):
    sub = start(tenant_a)
    Subscription.objects.filter(pk=sub.pk).update(
        status="past_due", past_due_since=timezone.now() - dt.timedelta(days=30)
    )
    assert services.enforce_grace() == 1
    admin = tenant_a.client("company_admin")
    r = admin.post(
        f"/api/companies/{tenant_a.company.pk}/employees/",
        {"registration": "9", "full_name": "Novo"},
        format="json",
    )
    assert r.status_code == 400 and "suspensa" in json.dumps(r.json(), ensure_ascii=False)
    # O núcleo de marcação não consulta cobrança.
    import inspect

    from apps.timeclock import services as tc

    assert "billing" not in inspect.getsource(tc)


def test_limite_do_plano(tenant_a):
    start(tenant_a)
    Plan.objects.filter(code="essencial").update(max_employees=1, max_devices=1)
    admin = tenant_a.client("company_admin")
    url = f"/api/companies/{tenant_a.company.pk}/employees/"
    assert admin.post(url, {"registration": "1", "full_name": "A"}, format="json").status_code == 201
    r = admin.post(url, {"registration": "2", "full_name": "B"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "plan_limit"
    r = admin.post(
        f"/api/companies/{tenant_a.company.pk}/billing/plan/", {"plan_code": "profissional"}, format="json"
    )
    assert r.status_code == 200
    assert admin.post(url, {"registration": "2", "full_name": "B"}, format="json").status_code == 201


def test_cancelamento_no_fim_do_periodo(tenant_a):
    sub = start(tenant_a)
    admin = tenant_a.client("company_admin")
    assert admin.post(
        f"/api/companies/{tenant_a.company.pk}/billing/cancel/", {"cancel": True}, format="json"
    ).json()["cancel_at_period_end"]
    expire(sub)
    services.renew(sub)
    sub.refresh_from_db()
    assert sub.status == "canceled" and not Invoice.objects.exists()


def test_plataforma(tenant_a, platform_admin):
    from conftest import login_client

    client = login_client(platform_admin)
    assert (
        client.post(
            f"/api/platform/companies/{tenant_a.company.pk}/subscription/",
            {"plan_code": "profissional", "trial_days": 0},
            format="json",
        ).status_code
        == 201
    )
    rows = client.get("/api/platform/subscriptions/").json()
    assert rows[0]["subscription"]["plan"]["code"] == "profissional"
    sub = Subscription.objects.get()
    expire(sub)
    assert client.post("/api/platform/billing/run/").json()["invoices_issued"] == 1
    invoice = Invoice.objects.get()
    r = client.post(f"/api/platform/invoices/{invoice.pk}/simulate/", {"event": "paid"}, format="json")
    assert r.json()["result"] == "fatura paga"
    assert (
        client.post(
            "/api/platform/plans/", {"code": "x", "name": "X", "base_price_cents": -1}, format="json"
        ).status_code
        == 400
    )
    assert tenant_a.client("company_admin").get("/api/platform/subscriptions/").status_code == 403
