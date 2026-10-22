from django.core.management.base import BaseCommand, CommandError

from apps.biometrics.services import purge_inactive


class Command(BaseCommand):
    help = (
        "Exclui templates biométricos de funcionários inativos há N dias. "
        "Não há prazo padrão: a política de retenção depende de validação jurídica."
    )

    def add_arguments(self, parser):
        parser.add_argument("--inactive-days", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = options["inactive_days"]
        if days < 0:
            raise CommandError("--inactive-days deve ser >= 0.")
        count = purge_inactive(days=days, dry_run=options["dry_run"])
        verb = "seriam excluídos" if options["dry_run"] else "excluídos"
        self.stdout.write(f"{count} template(s) {verb}.")
