from .models import AuditLog

_SENSITIVE = ("password", "senha", "token", "secret", "biometr")


def _clean(metadata: dict) -> dict:
    return {k: v for k, v in metadata.items() if not any(s in k.lower() for s in _SENSITIVE)}


def record(request, action, *, company=None, actor=None, target=None, actor_email="", **metadata):
    """Registra um evento. `request` pode ser None (tarefas internas).

    O IP vem de REMOTE_ADDR; cabeçalhos X-Forwarded-For só devem ser considerados
    quando houver proxy confiável configurado (etapa 15).
    """
    if actor is None and request is not None and getattr(request.user, "is_authenticated", False):
        actor = request.user
    return AuditLog.objects.create(
        actor=actor,
        actor_email=(actor.email if actor else actor_email)[:254],
        company=company,
        action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        ip_address=request.META.get("REMOTE_ADDR") if request is not None else None,
        metadata=_clean(metadata),
    )
