from django.db import migrations


def create(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    # Preços são PLACEHOLDERS até a decisão comercial (centavos de real).
    for code, name, base, per, max_e, max_d, features in [
        ("essencial", "Essencial", 4900, 590, 30, 2, ["ponto", "espelho", "portal"]),
        ("profissional", "Profissional", 9900, 790, 200, 10, ["ponto", "espelho", "portal", "facial", "disponibilidade"]),
        ("empresarial", "Empresarial", 29900, 690, None, None, ["tudo", "afd", "folha", "suporte_prioritario"]),
    ]:
        Plan.objects.get_or_create(
            code=code,
            defaults=dict(
                name=name, base_price_cents=base, price_per_employee_cents=per,
                max_employees=max_e, max_devices=max_d, features=features,
            ),
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
