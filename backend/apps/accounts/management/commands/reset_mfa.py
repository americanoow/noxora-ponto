from django.core.management.base import BaseCommand, CommandError

from apps.accounts import mfa
from apps.accounts.models import User
from apps.audit import services as audit


class Command(BaseCommand):
    help = "Remove o segundo fator de um usuário que perdeu o autenticador e os códigos (suporte; auditado)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, email, reason, **options):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError("Usuário não encontrado.")
        mfa.disable(user)
        audit.record(None, "auth.mfa_reset_by_support", actor=user, reason=reason[:200])
        self.stdout.write(self.style.SUCCESS(f"Segundo fator removido de {user.email}."))
