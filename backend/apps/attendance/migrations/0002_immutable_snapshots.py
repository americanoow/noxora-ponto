"""PostgreSQL: instantâneo do fechamento e versões de regras não mudam (só o status de reabertura)."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION attendance_closing_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Fechamentos não são apagados' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.snapshot_sha256 <> OLD.snapshot_sha256
        OR NEW.start <> OLD.start OR NEW."end" <> OLD."end" OR NEW.company_id <> OLD.company_id
        OR NEW.closed_by_id <> OLD.closed_by_id OR NEW.closed_at <> OLD.closed_at
        OR (OLD.status = 'reopened') THEN
        RAISE EXCEPTION 'Instantâneo do fechamento é imutável' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_periodclosing_guard BEFORE UPDATE OR DELETE ON attendance_periodclosing
    FOR EACH ROW EXECUTE FUNCTION attendance_closing_guard();

CREATE OR REPLACE FUNCTION attendance_ruleset_guard() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Versões de regras não são alteradas nem apagadas' USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER attendance_ruleset_guard BEFORE UPDATE OR DELETE ON attendance_calculationruleset
    FOR EACH ROW EXECUTE FUNCTION attendance_ruleset_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS attendance_periodclosing_guard ON attendance_periodclosing;
DROP TRIGGER IF EXISTS attendance_ruleset_guard ON attendance_calculationruleset;
DROP FUNCTION IF EXISTS attendance_closing_guard();
DROP FUNCTION IF EXISTS attendance_ruleset_guard();
"""


def _run(schema_editor, sql):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("attendance", "0001_initial")]
    operations = [
        migrations.RunPython(lambda a, s: _run(s, SQL), lambda a, s: _run(s, REVERSE)),
    ]
