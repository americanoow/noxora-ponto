"""Worker único de tarefas periódicas: e-mails (10 s), cobrança (1 h) e verificação da cadeia (24 h).

Cada tarefa é idempotente; vários workers podem rodar (a fila de e-mail usa SKIP LOCKED).
"""

import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger("noxora.worker")

TASKS = [
    ("outbox", 10, lambda: call_command("process_outbox")),
    ("billing", 3600, lambda: call_command("run_billing")),
    ("verify_timeclock", 86400, lambda: call_command("verify_timeclock")),
]


class Command(BaseCommand):
    help = "Executa as tarefas periódicas do Noxora Ponto (use em um contêiner próprio)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Executa cada tarefa uma vez e sai.")

    def handle(self, *args, once=False, **options):
        last = {name: 0.0 for name, _, _ in TASKS}
        while True:
            now = time.monotonic()
            for name, every, task in TASKS:
                if once or now - last[name] >= every:
                    last[name] = now
                    try:
                        task()
                    except CommandError as exc:
                        # verify_timeclock falha quando acha problema: alerta, não derruba o worker.
                        logger.error("tarefa com alerta", extra={"task": name, "detail": str(exc)})
                    except Exception:
                        logger.exception("tarefa falhou", extra={"task": name})
            if once:
                return
            time.sleep(1)
