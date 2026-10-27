"""Planos, assinaturas, faturas e eventos de webhook (etapa 13).

Cobrança NUNCA bloqueia marcação de ponto (Portaria 671, art. 74): uma assinatura suspensa só restringe
operações administrativas que ampliam o uso (novos funcionários e tablets).
"""

from django.db import models


class Plan(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    base_price_cents = models.PositiveIntegerField(default=0)
    price_per_employee_cents = models.PositiveIntegerField(default=0)
    max_employees = models.PositiveIntegerField(null=True, blank=True)  # vazio = sem limite
    max_devices = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=list, blank=True)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["base_price_cents", "id"]


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Em teste"
    ACTIVE = "active", "Ativa"
    PAST_DUE = "past_due", "Pagamento pendente"
    SUSPENDED = "suspended", "Suspensa"
    CANCELED = "canceled", "Cancelada"


class Subscription(models.Model):
    company = models.OneToOneField("companies.Company", on_delete=models.PROTECT, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=10, choices=SubscriptionStatus.choices, default=SubscriptionStatus.TRIALING
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)
    past_due_since = models.DateTimeField(null=True, blank=True)
    gateway = models.CharField(max_length=20)
    gateway_customer_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class InvoiceStatus(models.TextChoices):
    OPEN = "open", "Em aberto"
    PAID = "paid", "Paga"
    FAILED = "failed", "Falhou"
    VOID = "void", "Cancelada"


class Invoice(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+")
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="invoices")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    plan_code = models.CharField(max_length=40)
    active_employees = models.PositiveIntegerField()
    amount_cents = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=InvoiceStatus.choices, default=InvoiceStatus.OPEN)
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    gateway = models.CharField(max_length=20)
    gateway_invoice_id = models.CharField(max_length=80, unique=True)
    payment_url = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["subscription", "period_start"], name="uniq_invoice_period"),
        ]


class WebhookEvent(models.Model):
    """Evento recebido do gateway. `event_id` único torna o processamento idempotente."""

    gateway = models.CharField(max_length=20)
    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [models.UniqueConstraint(fields=["gateway", "event_id"], name="uniq_webhook_event")]
