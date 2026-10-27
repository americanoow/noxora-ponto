"""Guarda da cadeia no PostgreSQL (D41, etapa 14): toda inserção na ARP precisa continuar a sequência.

- INSERT em `timeclock_timerecord`: NSR = último NSR da unidade + 1, `prev_hash` = último hash, e
  `record_hash` = SHA-256 recalculado no banco sobre os mesmos campos de `hashing.compute_hash`.
- UPDATE em `timeclock_nsrcounter`: só avança 1 por vez e só para um registro existente com o mesmo hash.
  DELETE do contador é bloqueado; INSERT só nasce zerado.

Isso impede inserir marcações fora de ordem, com lacuna, com hash inválido ou adulterar o contador,
inclusive por SQL direto ou `bulk_create`. Não impede quem tem DDL de remover os gatilhos: em produção o
papel da aplicação não é dono das tabelas (ver docs/operacao.md). Só PostgreSQL.
"""

from django.db import migrations

HASH_VERSION = "v1-anexo-v-historico"

SQL = f"""
CREATE OR REPLACE FUNCTION timeclock_format_dh(moment timestamptz, offset_minutes integer) RETURNS text AS $$
    SELECT to_char((moment AT TIME ZONE 'UTC') + make_interval(mins => offset_minutes), 'YYYY-MM-DD"T"HH24:MI')
        || ':00'
        || CASE WHEN offset_minutes >= 0 THEN '+' ELSE '-' END
        || lpad((abs(offset_minutes) / 60)::text, 2, '0')
        || lpad((abs(offset_minutes) % 60)::text, 2, '0')
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION timeclock_chain_guard() RETURNS trigger AS $$
DECLARE
    counter RECORD;
    payload text;
BEGIN
    SELECT last_nsr, last_hash INTO counter FROM timeclock_nsrcounter WHERE unit_id = NEW.unit_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Cadeia: contador da unidade inexistente' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.nsr <> counter.last_nsr + 1 THEN
        RAISE EXCEPTION 'Cadeia: NSR % fora de sequência (esperado %)', NEW.nsr, counter.last_nsr + 1
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.prev_hash <> counter.last_hash THEN
        RAISE EXCEPTION 'Cadeia: hash anterior não confere' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.hash_version <> '{HASH_VERSION}' THEN
        RAISE EXCEPTION 'Cadeia: versão de hash desconhecida' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    payload := lpad(NEW.nsr::text, 9, '0') || '7'
        || timeclock_format_dh(NEW.occurred_at, NEW.occurred_offset_minutes)
        || lpad(NEW.cpf, 12, '0')
        || timeclock_format_dh(NEW.recorded_at, NEW.recorded_offset_minutes)
        || NEW.collector_code
        || CASE WHEN NEW.offline THEN '1' ELSE '0' END
        || NEW.prev_hash;
    IF NEW.record_hash <> encode(sha256(convert_to(payload, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'Cadeia: hash do registro não confere' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION timeclock_counter_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Contador de NSR não pode ser apagado' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.last_nsr <> 0 OR NEW.last_hash <> '' THEN
            RAISE EXCEPTION 'Contador de NSR deve começar zerado' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.unit_id <> OLD.unit_id OR NEW.last_nsr <> OLD.last_nsr + 1 OR NOT EXISTS (
        SELECT 1 FROM timeclock_timerecord
        WHERE unit_id = NEW.unit_id AND nsr = NEW.last_nsr AND record_hash = NEW.last_hash
    ) THEN
        RAISE EXCEPTION 'Contador de NSR só avança junto com uma marcação gravada'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER timeclock_timerecord_chain BEFORE INSERT ON timeclock_timerecord
    FOR EACH ROW EXECUTE FUNCTION timeclock_chain_guard();
CREATE TRIGGER timeclock_nsrcounter_guard BEFORE INSERT OR UPDATE OR DELETE ON timeclock_nsrcounter
    FOR EACH ROW EXECUTE FUNCTION timeclock_counter_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS timeclock_timerecord_chain ON timeclock_timerecord;
DROP TRIGGER IF EXISTS timeclock_nsrcounter_guard ON timeclock_nsrcounter;
DROP FUNCTION IF EXISTS timeclock_chain_guard();
DROP FUNCTION IF EXISTS timeclock_counter_guard();
DROP FUNCTION IF EXISTS timeclock_format_dh(timestamptz, integer);
"""


def _run(schema_editor, sql):
    # Cursor sem parâmetros: o SQL contém '%' (RAISE) que não é marcador de parâmetro.
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(sql)


def forwards(apps, schema_editor):
    _run(schema_editor, SQL)


def backwards(apps, schema_editor):
    _run(schema_editor, REVERSE)


class Migration(migrations.Migration):
    dependencies = [("timeclock", "0005_timerecord_sync_flags")]
    operations = [migrations.RunPython(forwards, backwards)]
