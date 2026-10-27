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
        self._history(company, units, manager_user=manager)
        self.stdout.write(
            self.style.SUCCESS(
                "Empresa Demo criada: admin@demo.test / gestor@demo.test / funcionario@demo.test "
                "(senha em seed_demo.py); tablet 'Recepção Centro' com código de ativação acima."
            )
        )

    def _history(self, company, units, *, manager_user):
        """Tablet, portal do funcionário, assinatura em teste e 14 dias de marcações (via serviço oficial)."""
        import random
        import uuid
        from zoneinfo import ZoneInfo

        from django.utils import timezone

        from apps.billing import services as billing
        from apps.billing.models import Plan
        from apps.devices import services as device_services
        from apps.devices.models import Device
        from apps.timeclock import services as tc

        rng = random.Random(42)  # noqa: S311 (dados fictícios)
        unit = units["Centro"][0]
        unit.address = "Rua Fictícia, 100 — Centro"
        unit.save(update_fields=["address"])
        company.legal_name, company.tax_id_type, company.tax_id = (
            "Empresa Demo Ltda",
            "CNPJ",
            "11222333000181",
        )
        company.offline_policy = "registration_only"
        company.save()
        device = Device.objects.create(company=company, unit=unit, name="Recepção Centro")
        code, _ = device_services.new_activation_code(device)
        self.stdout.write(f"Código de ativação do tablet (15 min): {code}")
        history_device = Device.objects.create(company=company, unit=unit, name="Tablet histórico (demo)")
        hcode, _ = device_services.new_activation_code(history_device)
        history_device, _ = device_services.activate(hcode)
        Device.objects.filter(pk=history_device.pk).update(
            activated_at=timezone.now() - datetime.timedelta(days=30)
        )
        history_device.refresh_from_db()

        worker = User.objects.create_user("funcionario@demo.test", DEMO_PASSWORD)
        Membership.objects.create(user=worker, company=company, role=Role.EMPLOYEE, name="Funcionário Demo")
        employees = list(Employee.objects.filter(company=company, assignments__unit=unit).distinct()[:10])
        employees[0].access_user = worker
        employees[0].cpf = "52998224725"
        employees[0].save()

        tz = ZoneInfo(unit.timezone)
        today = timezone.localdate()
        for back in range(14, 0, -1):
            day = today - datetime.timedelta(days=back)
            if day.weekday() >= 5:
                continue
            for e in employees:
                if rng.random() < 0.05:
                    continue  # falta
                marks = [
                    (8, rng.randint(-6, 8)),
                    (12, rng.randint(0, 5)),
                    (13, rng.randint(0, 6)),
                    (17, rng.randint(-5, 50)),
                ]
                if rng.random() < 0.05:
                    marks = marks[:3]  # esqueceu a saída
                for hour, minute in marks:
                    local = datetime.datetime.combine(
                        day, datetime.time(hour), tzinfo=tz
                    ) + datetime.timedelta(minutes=minute)
                    tc._insert(
                        history_device,
                        e,
                        uuid.uuid4(),
                        "",
                        None,
                        tc.IdentificationResult("registration"),
                        occurred_at=local.astimezone(datetime.UTC),
                    )
        billing.start_subscription(company=company, plan=Plan.objects.get(code="profissional"))
