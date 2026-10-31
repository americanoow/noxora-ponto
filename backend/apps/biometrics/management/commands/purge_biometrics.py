from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.biometrics.services import purge_ephemeral, purge_inactive


class Command(BaseCommand):
    help = (
        "Retenção da biometria (LGPD, art. 16): apaga o rosto cadastrado de quem está inativo há N dias "
        "(padrão: BIOMETRIC_INACTIVE_RETENTION_DAYS), desafios vencidos e tentativas não usadas antigas "
        "(BIOMETRIC_ATTEMPT_RETENTION_DAYS). Roda todo dia pelo worker."
    )

    def add_arguments(self, parser):
        parser.add_argument("--inactive-days", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true", help="Só conta os rostos; não apaga nada.")

    def handle(self, *args, **options):
        days = options["inactive_days"]
        days = settings.BIOMETRIC_INACTIVE_RETENTION_DAYS if days is None else days
        if days < 0:
            raise CommandError("--inactive-days deve ser >= 0.")
        count = purge_inactive(days=days, dry_run=options["dry_run"])
        verb = "seriam excluídos" if options["dry_run"] else "excluídos"
        self.stdout.write(f"{count} template(s) {verb}.")
        if not options["dry_run"]:
            other = purge_ephemeral(attempt_days=settings.BIOMETRIC_ATTEMPT_RETENTION_DAYS)
            self.stdout.write(
                f"{other['challenges']} desafio(s) e {other['attempts']} tentativa(s) removidos."
            )
