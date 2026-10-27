"""Pré-verificação antes de migrar/implantar sobre um banco com dados existentes. Só LÊ.

Usa SQL direto (funciona mesmo antes de aplicar as migrations pendentes) e falha com código ≠ 0 se
encontrar algo que impediria uma migration ou violaria uma garantia do produto. Nada é corrigido
automaticamente: cada item exige decisão humana.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

_OVERLAP = (
    "SELECT DISTINCT a.employee_id FROM {t} a JOIN {t} b ON a.employee_id = b.employee_id AND a.id < b.id "
    "AND a.valid_from <= COALESCE(b.valid_to, '9999-12-31') "
    "AND b.valid_from <= COALESCE(a.valid_to, '9999-12-31')"
)

# (título, SQL, tabelas necessárias, bloqueante)
CHECKS = [
    (
        "accounts.0002: e-mails duplicados ignorando maiúsculas",
        "SELECT lower(email), count(*) FROM accounts_user GROUP BY lower(email) HAVING count(*) > 1",
        ["accounts_user"],
        True,
    ),
    (
        "devices.0003: localização ligada sem justificativa (ou só espaços)",
        "SELECT id FROM devices_device WHERE collect_location AND trim(location_justification) = ''",
        ["devices_device"],
        True,
    ),
    (
        "operations.0003: lotações com vigências sobrepostas",
        _OVERLAP.format(t="operations_assignment"),
        ["operations_assignment"],
        True,
    ),
    (
        "operations.0003: jornadas com vigências sobrepostas",
        _OVERLAP.format(t="operations_employeeschedule"),
        ["operations_employeeschedule"],
        True,
    ),
    (
        "timeclock.0003: marcações legadas sem instantâneo do comprovante (informativo)",
        "SELECT id FROM timeclock_timerecord WHERE receipt_snapshot IS NULL",
        ["timeclock_timerecord"],
        False,
    ),
]


class Command(BaseCommand):
    help = "Verifica dados existentes que impediriam migrations ou violariam garantias (somente leitura)."

    def handle(self, *args, **options):
        existing = set(connection.introspection.table_names())
        blocking = 0
        for title, sql, tables, is_blocking in CHECKS:
            if not set(tables) <= existing:
                self.stdout.write(f"- {title}: tabela ausente (ainda não migrada), ignorado")
                continue
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            if rows:
                mark = "BLOQUEIA" if is_blocking else "aviso"
                self.stdout.write(f"- [{mark}] {title}: {len(rows)} ocorrência(s); exemplos: {rows[:5]}")
                blocking += int(is_blocking)
            else:
                self.stdout.write(f"- ok: {title}")
        if {"timeclock_timerecord", "timeclock_nsrcounter"} <= existing:
            try:
                call_command("verify_timeclock", stdout=self.stdout)
            except CommandError as exc:
                self.stdout.write(f"- [BLOQUEIA] cadeia de marcações: {exc}")
                blocking += 1
        if blocking:
            raise CommandError(f"{blocking} verificação(ões) bloqueante(s). Corrija antes de migrar.")
        self.stdout.write(self.style.SUCCESS("Pré-verificação sem bloqueios."))
