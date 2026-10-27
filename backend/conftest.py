from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company, Membership, Role

PASSWORD = "senha-forte-12345"  # noqa: S105  (senha de teste)


GUARDED_TABLES = (
    "timeclock_timerecord",
    "timeclock_nsrcounter",
    "audit_auditlog",
    "attendance_periodclosing",
    "attendance_calculationruleset",
)


@pytest.fixture(scope="session", autouse=True)
def _postgresql_flush_immutable_test_tables():
    """Só o flush de teardown pode truncar ARP no banco descartável de testes.

    Os gatilhos permanecem ativos durante todos os testes, incluindo SQL direto.
    A alteração e o TRUNCATE do flush executam na mesma transação do Django.
    """
    from django.db.backends.postgresql.operations import DatabaseOperations

    original = DatabaseOperations.sql_flush

    def sql_flush(self, style, tables, **kwargs):
        statements = original(self, style, tables, **kwargs)
        guarded = [t for t in GUARDED_TABLES if t in tables]
        if guarded:
            return [
                *(f'ALTER TABLE "{t}" DISABLE TRIGGER USER;' for t in guarded),
                *statements,
                *(f'ALTER TABLE "{t}" ENABLE TRIGGER USER;' for t in guarded),
            ]
        return statements

    with patch.object(DatabaseOperations, "sql_flush", sql_flush):
        yield


@pytest.fixture(autouse=True)
def _limpar_cache_e_emails(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    # Hasher rápido só nos testes; produção usa o padrão do Django (PBKDF2).
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    cache.clear()
    yield
    cache.clear()


def make_user(email, **extra):
    return User.objects.create_user(email, PASSWORD, **extra)


def login_client(user):
    client = APIClient()
    client.force_login(user)
    return client


class Tenant:
    """Empresa de teste com um usuário de cada papel."""

    def __init__(self, slug):
        self.company = Company.objects.create(name=f"Empresa {slug}")
        self.users = {}
        self.memberships = {}
        for role in Role.values:
            user = make_user(f"{role}@{slug}.test", first_name=role)
            self.users[role] = user
            self.memberships[role] = Membership.objects.create(user=user, company=self.company, role=role)

    def client(self, role):
        return login_client(self.users[role])


@pytest.fixture
def tenant_a(db):
    return Tenant("a")


@pytest.fixture
def tenant_b(db):
    return Tenant("b")


@pytest.fixture
def platform_admin(db):
    return make_user("plataforma@noxora.test", is_platform_admin=True)
