from importlib import import_module

from django.db import migrations, models

triggers = import_module("apps.timeclock.migrations.0002_immutability_triggers")
guard = import_module("apps.timeclock.migrations.0004_sqlite_replace_guard")


def drop_all(apps, schema_editor):
    guard.drop_guard(apps, schema_editor)
    triggers.drop_triggers(apps, schema_editor)


def create_all(apps, schema_editor):
    triggers.create_triggers(apps, schema_editor)
    guard.create_guard(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("timeclock", "0004_sqlite_replace_guard")]
    # O SQLite reconstrói a tabela ao adicionar coluna com padrão e perderia os gatilhos de imutabilidade
    # (0002) e a guarda contra REPLACE (0004): remover antes e reinstalar depois, na mesma migration atômica.
    operations = [
        migrations.RunPython(drop_all, create_all),
        migrations.AddField(
            model_name="timerecord",
            name="sync_flags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(create_all, drop_all),
    ]
