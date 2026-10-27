"""Cria (ou promove) a conta da equipe Noxora. A senha vem de NOXORA_ADMIN_PASSWORD ou é pedida no terminal."""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Cria ou promove um administrador da plataforma Noxora (sem acesso aos dados internos das empresas)."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        password = os.environ.get("NOXORA_ADMIN_PASSWORD") or getpass.getpass("Senha: ")
        user = User.objects.filter(email__iexact=email).first() or User(email=email)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
        user.set_password(password)
        user.is_platform_admin = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Administrador da plataforma pronto: {user.email}"))
