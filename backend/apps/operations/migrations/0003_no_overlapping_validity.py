"""PostgreSQL: vigências de lotação e de jornada do mesmo funcionário não se sobrepõem (btree_gist).

Antes de criar as constraints, a migration procura sobreposições existentes e PARA com a lista de
funcionários afetados: nada é corrigido automaticamente (decisão humana). Ver `manage.py preflight`.
"""

from django.db import migrations

TABLES = {
    "operations_assignment": "assignment_no_overlap",
    "operations_employeeschedule": "employeeschedule_no_overlap",
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        for table, name in TABLES.items():
            cursor.execute(
                f"""
                SELECT DISTINCT a.employee_id FROM {table} a JOIN {table} b
                  ON a.employee_id = b.employee_id AND a.id < b.id
                 AND daterange(a.valid_from, a.valid_to, '[]') && daterange(b.valid_from, b.valid_to, '[]')
                """
            )
            rows = [r[0] for r in cursor.fetchall()]
            if rows:
                raise RuntimeError(
                    f"{table}: vigências sobrepostas para os funcionários {rows[:20]}. Corrija antes de migrar."
                )
            cursor.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} EXCLUDE USING gist "
                f"(employee_id WITH =, daterange(valid_from, valid_to, '[]') WITH &&)"
            )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, name in TABLES.items():
            cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [("operations", "0002_unit_address")]
    operations = [migrations.RunPython(forwards, backwards)]
