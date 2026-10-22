from .models import AuditLog

_SENSITIVE = ("password", "senha", "token", "secret", "biometr", "authorization", "cookie")


def _clean(metadata):
    if isinstance(metadata, dict):
        return {k: _clean(v) for k, v in metadata.items() if not any(s in k.lower() for s in _SENSITIVE)}
    if isinstance(metadata, (list, tuple)):
        return [_clean(value) for value in metadata]
    return metadata


def record(request, action, *, company=None, actor=None, target=None, actor_email="", **metadata):
    """Registra um evento. `request` pode ser None (tarefas internas).

    O IP vem de REMOTE_ADDR; cabeçalhos X-Forwarded-For só devem ser considerados
    quando houver proxy confiável configurado (etapa 15).
    """
    # Quando o autor já vem identificado (ex.: dispositivo), não se consulta request.user: durante a
    # autenticação isso reentraria nos autenticadores.
    if actor is None and not actor_email and request is not None:
        if getattr(request.user, "is_authenticated", False):
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
