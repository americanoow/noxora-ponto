from django.db import migrations


def create_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        # REPLACE pode apagar a linha sem disparar DELETE quando
        # recursive_triggers está desligado. Rejeitar antes da substituição.
        schema_editor.execute("""
            CREATE TRIGGER timeclock_timerecord_no_replace
            BEFORE INSERT ON timeclock_timerecord
            WHEN EXISTS (
                SELECT 1 FROM timeclock_timerecord
                WHERE id = NEW.id OR (unit_id = NEW.unit_id AND nsr = NEW.nsr)
                    OR (device_id = NEW.device_id AND client_event_id = NEW.client_event_id)
            )
            BEGIN SELECT RAISE(ABORT, 'Marcações de ponto são imutáveis'); END
        """)


def drop_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS timeclock_timerecord_no_replace")


class Migration(migrations.Migration):
    dependencies = [("timeclock", "0003_receipt_snapshot")]
    operations = [migrations.RunPython(create_guard, drop_guard)]
