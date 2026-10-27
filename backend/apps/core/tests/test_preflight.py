import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_preflight_limpo(capsys):
    call_command("preflight")
    assert "sem bloqueios" in capsys.readouterr().out


def test_preflight_acusa_email_duplicado(capsys):
    if connection.vendor != "postgresql":
        pytest.skip("SQL de PostgreSQL")
    User.objects.create_user("a@x.test", "senha-forte-12345")
    with connection.cursor() as cursor:
        # Simula um banco antigo, anterior à constraint de e-mail sem diferenciar maiúsculas.
        cursor.execute("DROP INDEX IF EXISTS accounts_user_email_ci_unique")
        cursor.execute(
            "INSERT INTO accounts_user (password, is_superuser, first_name, last_name, is_staff, is_active, "
            "date_joined, email, is_platform_admin) "
            "VALUES ('x', false, '', '', false, true, now(), 'A@x.test', false)"
        )
    with pytest.raises(CommandError):
        call_command("preflight")
    assert "BLOQUEIA" in capsys.readouterr().out
