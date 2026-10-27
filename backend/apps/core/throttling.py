"""Limite de taxa em janela fixa com contador ATÔMICO no cache (`add` + `incr`).

Correto entre processos e servidores quando o cache é compartilhado (Redis em produção). O
`SimpleRateThrottle` do DRF faz ler-modificar-gravar e perde tentativas sob concorrência.
"""

import time

from rest_framework.throttling import SimpleRateThrottle


class AtomicWindowThrottle(SimpleRateThrottle):
    def allow_request(self, request, view):
        if self.rate is None:
            return True
        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True
        now = time.time()
        window = int(now // self.duration)
        key = f"{self.key}:{window}"
        self.cache.add(key, 0, timeout=self.duration + 5)
        try:
            count = self.cache.incr(key)
        except ValueError:  # expirou entre add e incr
            self.cache.add(key, 1, timeout=self.duration + 5)
            count = 1
        self._retry_after = (window + 1) * self.duration - now
        return count <= self.num_requests

    def wait(self):
        return max(0.0, getattr(self, "_retry_after", self.duration))


class AtomicScopedRateThrottle(AtomicWindowThrottle):
    """Equivalente atômico do `ScopedRateThrottle` (escopo definido na view; IP ou usuário)."""

    scope_attr = "throttle_scope"

    def __init__(self):
        pass  # a taxa depende da view

    def allow_request(self, request, view):
        self.scope = getattr(view, self.scope_attr, None)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
