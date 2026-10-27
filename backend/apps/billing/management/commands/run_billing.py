from django.core.management.base import BaseCommand

from apps.billing import services
from apps.billing.models import Subscription, SubscriptionStatus


class Command(BaseCommand):
    help = (
        "Renova assinaturas vencidas (emite faturas) e suspende as em atraso além da carência. Idempotente."
    )

    def handle(self, *args, **options):
        invoices = 0
        for sub in Subscription.objects.exclude(status=SubscriptionStatus.CANCELED):
            if services.renew(sub) is not None:
                invoices += 1
        suspended = services.enforce_grace()
        self.stdout.write(f"faturas emitidas: {invoices}; assinaturas suspensas: {suspended}")
