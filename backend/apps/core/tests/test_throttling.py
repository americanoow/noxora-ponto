import pytest
from django.core.cache import cache
from rest_framework.test import APIRequestFactory

from apps.core.net import client_ip
from apps.core.throttling import AtomicWindowThrottle


class TenPerMinute(AtomicWindowThrottle):
    rate = "3/min"
    scope = "teste"

    def get_cache_key(self, request, view):
        return "thr:teste:1"


def test_janela_atomica_conta_cada_tentativa():
    cache.clear()
    request = APIRequestFactory().get("/")
    results = [TenPerMinute().allow_request(request, None) for _ in range(5)]
    assert results == [True, True, True, False, False]
    throttle = TenPerMinute()
    throttle.allow_request(request, None)
    assert 0 < throttle.wait() <= 60


@pytest.mark.parametrize(
    "proxies,xff,expected",
    [
        (0, "1.1.1.1", "9.9.9.9"),
        (1, "1.1.1.1, 2.2.2.2", "2.2.2.2"),
        (2, "1.1.1.1, 2.2.2.2", "1.1.1.1"),
        (2, "x", "9.9.9.9"),
    ],
)
def test_ip_do_cliente_so_confia_em_proxy_declarado(settings, proxies, xff, expected):
    settings.TRUSTED_PROXY_COUNT = proxies
    request = APIRequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR="9.9.9.9")
    assert client_ip(request) == expected


def test_request_id(client):
    r = client.get("/api/health/", HTTP_X_REQUEST_ID="abc12345")
    assert r["X-Request-ID"] == "abc12345"
    assert len(client.get("/api/health/", HTTP_X_REQUEST_ID="<script>")["X-Request-ID"]) == 32
