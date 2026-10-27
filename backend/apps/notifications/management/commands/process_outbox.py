import time

from django.core.management.base import BaseCommand

from apps.notifications import services


class Command(BaseCommand):
    help = "Envia e-mails da fila. --loop mantém o worker rodando (intervalo em segundos)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=0, help="Repetir a cada N segundos (0 = uma vez).")

    def handle(self, *args, loop=0, **options):
        while True:
            counts = services.process()
            if any(counts.values()):
                self.stdout.write(str(counts))
            if not loop:
                return
            time.sleep(loop)
