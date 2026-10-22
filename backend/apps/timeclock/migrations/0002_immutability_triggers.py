"""Gatilhos que tornam as marcações imutáveis no próprio banco (Anexo IX, item 7: "não devem ser
apagados ou alterados, direta ou indiretamente"). Valem também para SQL direto e para o ORM.

Limite conhecido: quem tem privilégio de DDL (dono das tabelas/superusuário) pode remover o gatilho.
Em produção o usuário da aplicação NÃO deve ser dono das tabelas nem ter DROP/TRIGGER (etapa 14/15).
"""

from django.db import migrations

TABLE = "timeclock_timerecord"
MESSAGE = "Marcações de ponto são imutáveis"


def create_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(
            f"""
            CREATE FUNCTION timeclock_block_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{MESSAGE}' USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        schema_editor.execute(
            f"CREATE TRIGGER timeclock_timerecord_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION timeclock_block_mutation()"
        )
        schema_editor.execute(
            f"CREATE TRIGGER timeclock_timerecord_no_truncate BEFORE TRUNCATE ON {TABLE} "
            "FOR EACH STATEMENT EXECUTE FUNCTION timeclock_block_mutation()"
        )
    elif vendor == "sqlite":
        for event in ("UPDATE", "DELETE"):
            schema_editor.execute(
                f"CREATE TRIGGER timeclock_timerecord_no_{event.lower()} BEFORE {event} ON {TABLE} "
                f"BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END"
            )


def drop_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(f"DROP TRIGGER IF EXISTS timeclock_timerecord_immutable ON {TABLE}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS timeclock_timerecord_no_truncate ON {TABLE}")
        schema_editor.execute("DROP FUNCTION IF EXISTS timeclock_block_mutation()")
    elif vendor == "sqlite":
        for event in ("update", "delete"):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS timeclock_timerecord_no_{event}")


class Migration(migrations.Migration):
    dependencies = [("timeclock", "0001_initial")]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
