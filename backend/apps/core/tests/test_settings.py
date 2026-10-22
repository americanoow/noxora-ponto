import runpy
from pathlib import Path

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

SETTINGS = Path(__file__).resolve().parents[3] / "config" / "settings.py"
TEST_KEY = "only-for-settings-tests-0123456789-abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def env(monkeypatch):
    for name in (
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_COOKIE_SECURE",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_producao_exige_chave(env):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        runpy.run_path(str(SETTINGS))


@pytest.mark.parametrize(
    "key", ["   ", "inseguro-somente-desenvolvimento", "troque-isto-em-ambientes-reais", "a" * 60]
)
def test_producao_rejeita_chave_insegura(env, key):
    env.setenv("DJANGO_SECRET_KEY", key)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        runpy.run_path(str(SETTINGS))


def test_producao_exige_postgresql(env):
    env.setenv("DJANGO_SECRET_KEY", TEST_KEY)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        runpy.run_path(str(SETTINGS))


@pytest.mark.parametrize("hosts", ["", "*"])
def test_producao_rejeita_hosts_abertos(env, hosts):
    env.setenv("DJANGO_SECRET_KEY", TEST_KEY)
    env.setenv("DJANGO_ALLOWED_HOSTS", hosts)
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        runpy.run_path(str(SETTINGS))


def test_producao_cookies_seguros_e_permissoes(env):
    env.setenv("DJANGO_SECRET_KEY", TEST_KEY)
    env.setenv("DATABASE_URL", "postgresql://localhost/noxora_test")
    env.setenv("DJANGO_COOKIE_SECURE", "false")
    config = runpy.run_path(str(SETTINGS))
    assert config["DEBUG"] is False
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["CSRF_COOKIE_SECURE"] is True
    assert config["REST_FRAMEWORK"]["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


def test_debug_permite_sqlite_sem_chave(env):
    env.setenv("DJANGO_DEBUG", "true")
    config = runpy.run_path(str(SETTINGS))
    assert config["DATABASES"]["default"]["ENGINE"] == "django.db.backends.sqlite3"


@override_settings(DEBUG=False, ALLOWED_HOSTS=["localhost"])
def test_host_nao_autorizado_rejeitado():
    assert APIClient().get("/api/health/", HTTP_HOST="atacante.invalid").status_code == 400


def test_console_email_proibido_fora_de_debug(env):
    env.setenv("DJANGO_SECRET_KEY", TEST_KEY)
    env.setenv("DATABASE_URL", "postgresql://localhost/noxora_test")
    env.setenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
    with pytest.raises(RuntimeError, match="tokens"):
        runpy.run_path(str(SETTINGS))


def test_console_email_permitido_em_debug(env):
    env.setenv("DJANGO_DEBUG", "true")
    env.setenv("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
    config = runpy.run_path(str(SETTINGS))
    assert config["EMAIL_BACKEND"].endswith("console.EmailBackend")


def test_origens_de_desenvolvimento_so_em_debug(env):
    env.setenv("DJANGO_DEBUG", "true")
    assert "http://localhost:5173" in runpy.run_path(str(SETTINGS))["CSRF_TRUSTED_ORIGINS"]
    env.setenv("DJANGO_DEBUG", "false")
    env.setenv("DJANGO_SECRET_KEY", TEST_KEY)
    env.setenv("DATABASE_URL", "postgresql://localhost/noxora_test")
    env.setenv("DJANGO_CSRF_TRUSTED_ORIGINS", "https://ponto.exemplo.com")
    config = runpy.run_path(str(SETTINGS))
    assert config["CSRF_TRUSTED_ORIGINS"] == ["https://ponto.exemplo.com"]  # sem origens de desenvolvimento
