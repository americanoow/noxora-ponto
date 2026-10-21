import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.companies.models import Company, Membership, Role
from apps.operations import services
from apps.operations.models import Employee, Sector, Unit, WorkSchedule
from apps.operations.services import replace_schedule_days

NAMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gisele", "Hugo", "Isabela", "João"]
SURNAMES = ["Almeida", "Barros", "Cardoso", "Dias", "Esteves", "Farias"]
DEMO_PASSWORD = "demo-senha-12345"  # noqa: S105  (somente desenvolvimento)


class Command(BaseCommand):
    help = "Cria uma empresa fictícia para desenvolvimento. Só funciona com DJANGO_DEBUG=true."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo só pode ser executado com DJANGO_DEBUG=true.")
        if Company.objects.filter(name="Empresa Demo").exists():
            self.stdout.write("Empresa Demo já existe; nada a fazer.")
            return
        company = Company.objects.create(name="Empresa Demo")
        admin = User.objects.create_user("admin@demo.test", DEMO_PASSWORD)
        Membership.objects.create(user=admin, company=company, role=Role.COMPANY_ADMIN, name="Admin Demo")
        manager = User.objects.create_user("gestor@demo.test", DEMO_PASSWORD)
        mm = Membership.objects.create(user=manager, company=company, role=Role.MANAGER, name="Gestor Demo")

        sectors_by_unit = {
            "Centro": ["Atendimento", "Estoque"],
            "Zona Norte": ["Administrativo"],
            "Zona Sul": [],
        }
        units = {}
        for unit_name, sector_names in sectors_by_unit.items():
            unit = Unit.objects.create(company=company, name=unit_name)
            units[unit_name] = (
                unit,
                [Sector.objects.create(company=company, unit=unit, name=n) for n in sector_names],
            )
        mm.scope_units.add(units["Centro"][0])

        schedule = WorkSchedule.objects.create(company=company, name="Comercial 08-17")
        replace_schedule_days(
            schedule,
            [
                {
                    "weekday": d,
                    "start_time": datetime.time(8),
                    "end_time": datetime.time(17),
                    "break_minutes": 60,
                }
                for d in range(5)
            ],
        )

        start = datetime.date(2025, 1, 1)
        for i in range(30):
            unit, unit_sectors = list(units.values())[i % 3]
            employee = Employee.objects.create(
                company=company,
                registration=f"{1000 + i}",
                full_name=f"{NAMES[i % len(NAMES)]} {SURNAMES[i % len(SURNAMES)]} (demo)",
            )
            services.assign_unit(
                employee, company, unit, unit_sectors[i % len(unit_sectors)] if unit_sectors else None, start
            )
            services.assign_schedule(employee, company, schedule, start)
        self.stdout.write(
            self.style.SUCCESS(
                "Empresa Demo criada: admin@demo.test / gestor@demo.test (senha em seed_demo.py)."
            )
        )
