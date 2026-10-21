import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.operations.models import Employee


@pytest.mark.django_db
def test_seed_demo_so_em_debug_e_e_idempotente(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo")
    settings.DEBUG = True
    call_command("seed_demo")
    call_command("seed_demo")
    assert Employee.objects.count() == 30
