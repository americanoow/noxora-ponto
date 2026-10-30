import datetime as dt

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.companies.models import Company
from apps.devices.models import Device
from apps.operations.models import Employee

from .gateways import get_gateway
from .models import Invoice, InvoiceStatus, Subscription, SubscriptionStatus, WebhookEvent

PERIOD = dt.timedelta(days=30)


def usage(company) -> dict:
    return {
        "active_employees": Employee.objects.filter(company=company, is_active=True).count(),
        "active_devices": Device.objects.filter(company=company).exclude(status="revoked").count(),
    }


def subscription_for(company):
    return Subscription.objects.select_related("plan").filter(company=company).first()


def check_limit(company, resource: str, adding: int = 1):
    """Recusa ampliar o uso além do plano ou com assinatura suspensa/cancelada.

    Sem assinatura (instalação sem cobrança configurada) não há limite. Nunca afeta marcações.
    """
    # Verificação e inclusão acontecem sob o mesmo bloqueio da empresa (mesmo do fechamento): dois cadastros
    # simultâneos não enxergam a mesma vaga livre. Exige transação aberta (quem chama já a abre).
    Company.objects.select_for_update(no_key=True).get(pk=company.pk)
    sub = subscription_for(company)
    if sub is None:
        return
    if sub.status in (SubscriptionStatus.SUSPENDED, SubscriptionStatus.CANCELED):
        raise ValidationError(
            {
                "detail": "Assinatura suspensa ou cancelada: regularize para cadastrar novos itens.",
                "code": "billing",
            }
        )
    current = usage(company)
    limit, count = (
        (sub.plan.max_employees, current["active_employees"])
        if resource == "employees"
        else (sub.plan.max_devices, current["active_devices"])
    )
    if limit is not None and count + adding > limit:
        label = "funcionários ativos" if resource == "employees" else "tablets"
        raise ValidationError(
            {
                "detail": f"Limite do plano {sub.plan.name}: {limit} {label}. Mude de plano para ampliar.",
                "code": "plan_limit",
            }
        )


def start_subscription(*, company, plan, trial_days=None):
    trial_days = settings.BILLING_TRIAL_DAYS if trial_days is None else trial_days
    now = timezone.now()
    gateway = get_gateway()
    try:
        with transaction.atomic():
            return Subscription.objects.create(
                company=company,
                plan=plan,
                status=SubscriptionStatus.TRIALING if trial_days else SubscriptionStatus.ACTIVE,
                trial_ends_at=now + dt.timedelta(days=trial_days) if trial_days else None,
                current_period_start=now,
                current_period_end=now + (dt.timedelta(days=trial_days) if trial_days else PERIOD),
                gateway=gateway.name,
                gateway_customer_id=gateway.create_customer(company),
            )
    except IntegrityError:
        raise ValidationError({"detail": "A empresa já possui assinatura."}) from None


@transaction.atomic
def change_plan(*, subscription, plan):
    if not plan.is_active:
        raise ValidationError({"plan": "Plano indisponível."})
    Company.objects.select_for_update(no_key=True).get(pk=subscription.company_id)
    current = usage(subscription.company)
    if plan.max_employees is not None and current["active_employees"] > plan.max_employees:
        raise ValidationError({"plan": "A empresa tem mais funcionários ativos do que o plano permite."})
    if plan.max_devices is not None and current["active_devices"] > plan.max_devices:
        raise ValidationError({"plan": "A empresa tem mais tablets do que o plano permite."})
    subscription.plan = plan
    subscription.save(update_fields=["plan", "updated_at"])
    return subscription


def amount_for(plan, active_employees) -> int:
    return plan.base_price_cents + plan.price_per_employee_cents * active_employees


@transaction.atomic
def renew(subscription, now=None):
    """Fecha o período vencido: cancela (se pedido) ou emite a fatura do próximo período. Idempotente."""
    now = now or timezone.now()
    sub = Subscription.objects.select_for_update().select_related("plan", "company").get(pk=subscription.pk)
    if sub.current_period_end > now or sub.status == SubscriptionStatus.CANCELED:
        return None
    if sub.cancel_at_period_end:
        sub.status = SubscriptionStatus.CANCELED
        sub.save(update_fields=["status", "updated_at"])
        return None
    start, end = sub.current_period_end, sub.current_period_end + PERIOD
    employees = usage(sub.company)["active_employees"]
    invoice = Invoice(
        company=sub.company,
        subscription=sub,
        period_start=start,
        period_end=end,
        plan_code=sub.plan.code,
        active_employees=employees,
        amount_cents=amount_for(sub.plan, employees),
        due_at=start + dt.timedelta(days=settings.BILLING_DUE_DAYS),
        gateway=sub.gateway,
    )
    invoice.gateway_invoice_id, invoice.payment_url = get_gateway().create_invoice(invoice)
    invoice.save()
    if sub.status == SubscriptionStatus.TRIALING:
        sub.status = SubscriptionStatus.ACTIVE
    sub.current_period_start, sub.current_period_end = start, end
    sub.save(update_fields=["status", "current_period_start", "current_period_end", "updated_at"])
    return invoice


@transaction.atomic
def enforce_grace(now=None):
    """Assinaturas em atraso além da carência ficam suspensas (só restringe ampliação de uso)."""
    now = now or timezone.now()
    limit = now - dt.timedelta(days=settings.BILLING_GRACE_DAYS)
    return Subscription.objects.filter(status=SubscriptionStatus.PAST_DUE, past_due_since__lte=limit).update(
        status=SubscriptionStatus.SUSPENDED
    )


def handle_event(*, gateway: str, payload: dict) -> WebhookEvent:
    """Processa um evento uma única vez. Reenvio do mesmo `id` devolve o registro existente."""
    event_id = payload.get("id")
    event_type = payload.get("type")
    if not isinstance(event_id, str) or not event_id or not isinstance(event_type, str):
        raise ValidationError({"detail": "Evento inválido."})
    with transaction.atomic():
        event, created = WebhookEvent.objects.get_or_create(
            gateway=gateway, event_id=event_id, defaults={"event_type": event_type, "payload": payload}
        )
        if not created:
            return event
        invoice_id = (payload.get("data") or {}).get("invoice_id")
        invoice = (
            Invoice.objects.select_for_update()
            .select_related("subscription")
            .filter(gateway=gateway, gateway_invoice_id=invoice_id)
            .first()
            if isinstance(invoice_id, str)
            else None
        )
        now = timezone.now()
        if invoice is None:
            event.result = "ignorado: fatura desconhecida"
        elif event_type == "invoice.paid":
            if invoice.status != InvoiceStatus.PAID:
                invoice.status, invoice.paid_at = InvoiceStatus.PAID, now
                invoice.save(update_fields=["status", "paid_at"])
            sub = Subscription.objects.select_for_update().get(pk=invoice.subscription_id)
            if not Invoice.objects.filter(
                subscription=sub, status__in=[InvoiceStatus.OPEN, InvoiceStatus.FAILED]
            ).exclude(pk=invoice.pk).exists() and sub.status in (
                SubscriptionStatus.PAST_DUE,
                SubscriptionStatus.SUSPENDED,
            ):
                sub.status, sub.past_due_since = SubscriptionStatus.ACTIVE, None
                sub.save(update_fields=["status", "past_due_since", "updated_at"])
            event.result = "fatura paga"
        elif event_type == "invoice.payment_failed":
            if invoice.status == InvoiceStatus.PAID:
                event.result = "ignorado: fatura já paga"
            else:
                invoice.status = InvoiceStatus.FAILED
                invoice.save(update_fields=["status"])
                sub = Subscription.objects.select_for_update().get(pk=invoice.subscription_id)
                if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING):
                    sub.status, sub.past_due_since = SubscriptionStatus.PAST_DUE, now
                    sub.save(update_fields=["status", "past_due_since", "updated_at"])
                event.result = "pagamento falhou"
        else:
            event.result = "ignorado: tipo não tratado"
        event.processed_at = now
        event.save(update_fields=["result", "processed_at"])
        return event
