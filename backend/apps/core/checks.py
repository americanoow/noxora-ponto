from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def production_checks(app_configs, **kwargs):
    """`manage.py check --deploy`: o que precisa estar configurado para produção multiprocesso."""
    problems = []
    if not settings.REDIS_URL:
        problems.append(
            Error(
                "REDIS_URL ausente: limites de taxa e deduplicação exigem cache compartilhado.",
                id="core.E001",
            )
        )
    if not settings.BILLING_WEBHOOK_SECRET:
        problems.append(
            Warning("BILLING_WEBHOOK_SECRET ausente: webhooks de cobrança serão recusados.", id="core.W001")
        )
    if settings.EMAIL_BACKEND.endswith("locmem.EmailBackend"):
        problems.append(Error("Backend de e-mail em memória não envia mensagens.", id="core.E002"))
    return problems
