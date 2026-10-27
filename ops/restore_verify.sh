#!/usr/bin/env bash
# Restaura um backup num banco TEMPORÁRIO e verifica: integridade do arquivo, migrations em dia,
# cadeia de marcações (NSR + hash) e contagens do manifesto. Apaga o banco temporário ao final.
# Uso: ADMIN_DATABASE_URL=postgres://usuario@host/postgres ./ops/restore_verify.sh backups/noxora-XXXX.dump[.enc]
# (o usuário precisa poder criar banco). BACKUP_PASSFILE para arquivos .enc.
set -euo pipefail
file="${1:?informe o arquivo de backup}"
: "${ADMIN_DATABASE_URL:?defina ADMIN_DATABASE_URL (banco de administração, ex.: .../postgres)}"
here="$(cd "$(dirname "$0")/.." && pwd)"
python="${PYTHON:-$here/backend/.venv/bin/python}"

sha256sum --check "$file.sha256"
manifest="${file%.enc}"; manifest="${manifest%.dump}.manifest"
tmpdb="noxora_restore_$(date +%s)"
work="$(mktemp -d)"
cleanup() { psql "$ADMIN_DATABASE_URL" -qc "DROP DATABASE IF EXISTS $tmpdb" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

dump="$file"
if [[ "$file" == *.enc ]]; then
  : "${BACKUP_PASSFILE:?arquivo cifrado: defina BACKUP_PASSFILE}"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$file" -out "$work/restore.dump" -pass "file:$BACKUP_PASSFILE"
  dump="$work/restore.dump"
fi

psql "$ADMIN_DATABASE_URL" -qc "CREATE DATABASE $tmpdb"
target="${ADMIN_DATABASE_URL%/*}/$tmpdb"
pg_restore --no-owner --no-privileges --exit-on-error --dbname "$target" "$dump"

cd "$here/backend"
DATABASE_URL="$target" DJANGO_DEBUG=true "$python" manage.py migrate --check
DATABASE_URL="$target" DJANGO_DEBUG=true "$python" manage.py verify_timeclock

status=0
# Proteções no banco precisam voltar com o restore (pós-dados do pg_restore).
for trig in timeclock_timerecord_immutable timeclock_timerecord_chain timeclock_nsrcounter_guard audit_auditlog_append_only attendance_periodclosing_guard; do
  if [[ "$(psql "$target" -At -c "SELECT count(*) FROM pg_trigger WHERE tgname = '$trig'")" == "1" ]]; then
    echo "ok   gatilho $trig"
  else
    echo "ERRO gatilho $trig ausente"; status=1
  fi
done
while read -r name expected; do
  case "$name" in
    max_nsr_sum) sql="SELECT COALESCE(sum(last_nsr),0) FROM timeclock_nsrcounter" ;;
    *) sql="SELECT count(*) FROM $name" ;;
  esac
  got="$(psql "$target" -At -c "$sql")"
  if [[ "$got" == "$expected" ]]; then echo "ok   $name = $got"; else echo "ERRO $name: esperado $expected, restaurado $got"; status=1; fi
done < "$manifest"
[[ $status -eq 0 ]] && echo "RESTAURAÇÃO VERIFICADA: $file" || echo "RESTAURAÇÃO COM DIVERGÊNCIAS: $file"
exit $status
