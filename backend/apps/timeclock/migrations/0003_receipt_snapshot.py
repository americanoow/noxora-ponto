from importlib import import_module

from django.db import migrations, models

triggers = import_module("apps.timeclock.migrations.0002_immutability_triggers")


class Migration(migrations.Migration):
    dependencies = [("timeclock", "0002_immutability_triggers")]
    # SQLite pode reconstruir a tabela ao alterar o esquema. Reinstalar os
    # gatilhos na mesma migration atômica, inclusive no caminho reverso.
    operations = [
        migrations.RunPython(triggers.drop_triggers, triggers.create_triggers),
        migrations.AddField(
            model_name="timerecord", name="receipt_snapshot",
            field=models.JSONField(null=True, editable=False),
        ),
        migrations.AlterField(
            model_name="timerecord", name="clock_skew_seconds",
            field=models.BigIntegerField(null=True, blank=True),
        ),
        migrations.RunPython(triggers.create_triggers, triggers.drop_triggers),
    ]
