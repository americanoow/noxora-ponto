"""PostgreSQL: o livro-razão do banco de horas é somente de inclusão (corrige-se por estorno)."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION attendance_hourbank_guard() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Lançamentos do banco de horas não são alterados nem apagados: faça um estorno'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_hourbank_guard BEFORE UPDATE OR DELETE ON attendance_hourbankentry
    FOR EACH ROW EXECUTE FUNCTION attendance_hourbank_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS attendance_hourbank_guard ON attendance_hourbankentry;
DROP FUNCTION IF EXISTS attendance_hourbank_guard();
"""


def _run(schema_editor, sql):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("attendance", "0003_hour_bank")]
    operations = [
        migrations.RunPython(lambda a, s: _run(s, SQL), lambda a, s: _run(s, REVERSE)),
    ]
