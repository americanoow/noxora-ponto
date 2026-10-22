from django.core.management.base import BaseCommand, CommandError

from apps.operations.models import Unit
from apps.timeclock.services import verify_unit_chain


class Command(BaseCommand):
    help = "Confere a integridade (NSR contíguo, encadeamento e hash) das marcações de cada unidade."

    def handle(self, *args, **options):
        failures = 0
        for unit in Unit.objects.order_by("pk"):
            for problem in verify_unit_chain(unit):
                failures += 1
                self.stderr.write(f"unidade {unit.pk}: {problem}")
        if failures:
            raise CommandError(f"{failures} problema(s) de integridade encontrados.")
        self.stdout.write(self.style.SUCCESS("Cadeias de marcação íntegras."))
