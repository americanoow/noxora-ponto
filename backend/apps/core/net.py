from django.conf import settings


def client_ip(request) -> str | None:
    """IP do cliente. Só confia em X-Forwarded-For com proxies declarados (`TRUSTED_PROXY_COUNT`)."""
    remote = request.META.get("REMOTE_ADDR")
    proxies = settings.TRUSTED_PROXY_COUNT
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if proxies and xff:
        addresses = [a.strip() for a in xff.split(",") if a.strip()]
        if len(addresses) >= proxies:
            return addresses[-proxies]
    return remote
