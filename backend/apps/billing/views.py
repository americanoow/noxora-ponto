import json

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.companies.models import Company
from apps.operations.views import admin_company

from . import services
from .gateways import GATEWAYS, get_gateway, verify_signature
from .models import Invoice, Plan, Subscription


def plan_dict(p):
    return {
        "id": p.pk,
        "code": p.code,
        "name": p.name,
        "base_price_cents": p.base_price_cents,
        "price_per_employee_cents": p.price_per_employee_cents,
        "max_employees": p.max_employees,
        "max_devices": p.max_devices,
        "features": p.features,
        "is_public": p.is_public,
        "is_active": p.is_active,
    }


def invoice_dict(i):
    return {
        "id": i.pk,
        "period_start": i.period_start,
        "period_end": i.period_end,
        "plan_code": i.plan_code,
        "active_employees": i.active_employees,
        "amount_cents": i.amount_cents,
        "status": i.status,
        "due_at": i.due_at,
        "paid_at": i.paid_at,
        "gateway": i.gateway,
        "payment_url": i.payment_url,
    }


def subscription_dict(s):
    if s is None:
        return None
    return {
        "id": s.pk,
        "company_id": s.company_id,
        "plan": plan_dict(s.plan),
        "status": s.status,
        "status_label": s.get_status_display(),
        "trial_ends_at": s.trial_ends_at,
        "current_period_start": s.current_period_start,
        "current_period_end": s.current_period_end,
        "cancel_at_period_end": s.cancel_at_period_end,
        "past_due_since": s.past_due_since,
        "gateway": s.gateway,
        "sandbox": getattr(GATEWAYS.get(s.gateway), "is_sandbox", False),
    }


# ---------- Empresa ----------


class CompanyBillingView(APIView):
    def get(self, request, company_id):
        company = admin_company(request, company_id)
        sub = services.subscription_for(company)
        return Response(
            {
                "subscription": subscription_dict(sub),
                "usage": services.usage(company),
                "invoices": [invoice_dict(i) for i in Invoice.objects.filter(company=company)[:24]],
                "plans": [plan_dict(p) for p in Plan.objects.filter(is_active=True, is_public=True)],
                "notice": "Cobrança nunca bloqueia o registro de ponto dos funcionários.",
            }
        )


class CompanyPlanChangeView(APIView):
    def post(self, request, company_id):
        company = admin_company(request, company_id)
        plan = Plan.objects.filter(code=request.data.get("plan_code"), is_active=True, is_public=True).first()
        if plan is None:
            raise ValidationError({"plan_code": "Plano inválido."})
        with transaction.atomic():
            sub = Subscription.objects.select_for_update().filter(company=company).first()
            if sub is None:
                sub = services.start_subscription(company=company, plan=plan)
            else:
                before = sub.plan.code
                services.change_plan(subscription=sub, plan=plan)
                audit.record(request, "billing.plan_changed", company=company, before=before, after=plan.code)
        return Response(subscription_dict(services.subscription_for(company)))


class CompanyCancelView(APIView):
    """POST {cancel: true|false}: cancela no fim do período ou desfaz o pedido."""

    def post(self, request, company_id):
        company = admin_company(request, company_id)
        cancel = request.data.get("cancel")
        if not isinstance(cancel, bool):
            raise ValidationError({"cancel": "Use verdadeiro ou falso."})
        with transaction.atomic():
            sub = Subscription.objects.select_for_update().filter(company=company).first()
            if sub is None:
                raise Http404
            sub.cancel_at_period_end = cancel
            sub.save(update_fields=["cancel_at_period_end", "updated_at"])
            audit.record(
                request, "billing.cancel_requested" if cancel else "billing.cancel_reverted", company=company
            )
        return Response(subscription_dict(services.subscription_for(company)))


# ---------- Plataforma Noxora ----------


def _platform(request):
    if not request.user.is_platform_admin:
        raise PermissionDenied("Operação restrita à equipe da plataforma.")


class PlatformPlanListView(APIView):
    def get(self, request):
        _platform(request)
        return Response([plan_dict(p) for p in Plan.objects.all()])

    def post(self, request):
        _platform(request)
        d = request.data
        code, name = d.get("code"), d.get("name")
        if not isinstance(code, str) or not code.replace("-", "").isalnum() or len(code) > 40:
            raise ValidationError({"code": "Código inválido."})
        if not isinstance(name, str) or not name.strip():
            raise ValidationError({"name": "Informe o nome."})
        ints = {}
        for field in ("base_price_cents", "price_per_employee_cents", "max_employees", "max_devices"):
            value = d.get(field)
            if value is None and field.startswith("max_"):
                ints[field] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError({field: "Informe um inteiro não negativo."})
            ints[field] = value
        if Plan.objects.filter(code=code).exists():
            raise ValidationError({"code": "Código já usado."})
        plan = Plan.objects.create(code=code, name=name.strip(), features=d.get("features") or [], **ints)
        audit.record(request, "platform.plan_created", target=plan, code=code)
        return Response(plan_dict(plan), status=201)


class PlatformSubscriptionListView(APIView):
    def get(self, request):
        _platform(request)
        rows = []
        for company in Company.objects.all().order_by("name"):
            sub = services.subscription_for(company)
            rows.append(
                {
                    "company": {"id": company.pk, "name": company.name, "is_active": company.is_active},
                    "subscription": subscription_dict(sub),
                    "usage": services.usage(company),
                    "open_invoices": Invoice.objects.filter(
                        company=company, status__in=["open", "failed"]
                    ).count(),
                }
            )
        return Response(rows)


class PlatformCompanySubscriptionView(APIView):
    def post(self, request, company_id):
        _platform(request)
        company = Company.objects.filter(pk=company_id).first()
        plan = Plan.objects.filter(code=request.data.get("plan_code"), is_active=True).first()
        if company is None:
            raise Http404
        if plan is None:
            raise ValidationError({"plan_code": "Plano inválido."})
        trial = request.data.get("trial_days")
        if trial is not None and (
            isinstance(trial, bool) or not isinstance(trial, int) or not 0 <= trial <= 90
        ):
            raise ValidationError({"trial_days": "Entre 0 e 90 dias."})
        with transaction.atomic():
            sub = services.start_subscription(company=company, plan=plan, trial_days=trial)
            audit.record(request, "platform.subscription_started", company=company, plan=plan.code)
        return Response(subscription_dict(sub), status=201)


class PlatformRunBillingView(APIView):
    def post(self, request):
        _platform(request)
        issued = 0
        for sub in Subscription.objects.exclude(status="canceled"):
            for _ in range(12):
                if services.renew(sub) is None:
                    break
                issued += 1
        suspended = services.enforce_grace()
        audit.record(request, "platform.billing_run", issued=issued, suspended=suspended)
        return Response({"invoices_issued": issued, "subscriptions_suspended": suspended})


class PlatformSimulatePaymentView(APIView):
    """SOMENTE SANDBOX: simula o gateway enviando `invoice.paid` ou `invoice.payment_failed` ao webhook."""

    def post(self, request, invoice_id):
        _platform(request)
        invoice = Invoice.objects.filter(pk=invoice_id).first()
        if invoice is None:
            raise Http404
        gateway = get_gateway()
        if not getattr(gateway, "is_sandbox", False) or invoice.gateway != gateway.name:
            raise ValidationError({"detail": "Simulação disponível apenas no ambiente de testes."})
        event = {"paid": "invoice.paid", "failed": "invoice.payment_failed"}.get(request.data.get("event"))
        if event is None:
            raise ValidationError({"event": "Use paid ou failed."})
        body, signature = gateway.simulate_event(event, invoice.gateway_invoice_id)
        if not verify_signature(body, signature):
            raise ValidationError({"detail": "Segredo do webhook não configurado."})
        result = services.handle_event(gateway=gateway.name, payload=json.loads(body))
        return Response({"event_id": result.event_id, "result": result.result})


# ---------- Webhook ----------


class WebhookView(APIView):
    """Recebe eventos do gateway. Assinatura HMAC obrigatória; idempotente por id do evento."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request, gateway):
        if gateway not in GATEWAYS:
            raise Http404
        body = request.body
        if len(body) > 65536:
            raise ValidationError({"detail": "Evento grande demais."})
        if not verify_signature(body, request.headers.get("X-Noxora-Signature", "")):
            raise PermissionDenied("Assinatura inválida.")
        try:
            payload = json.loads(body)
        except ValueError:
            raise ValidationError({"detail": "JSON inválido."}) from None
        if not isinstance(payload, dict):
            raise ValidationError({"detail": "Evento inválido."})
        event = services.handle_event(gateway=gateway, payload=payload)
        return Response({"received": True, "result": event.result})
