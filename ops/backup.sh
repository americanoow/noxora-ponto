#!/usr/bin/env bash
# Backup lógico do PostgreSQL (pg_dump formato custom) com manifesto e SHA-256.
# Uso: DATABASE_URL=postgres://... BACKUP_DIR=/caminho ./ops/backup.sh
# Opcional: BACKUP_PASSFILE=/run/secrets/backup_pass cifra o arquivo (AES-256, openssl, PBKDF2).
set -euo pipefail
: "${DATABASE_URL:?defina DATABASE_URL}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$BACKUP_DIR/noxora-$stamp"

pg_dump --format=custom --no-owner --no-privileges --file "$base.dump" "$DATABASE_URL"

# Manifesto: contagens das tabelas críticas no momento do backup (conferidas na restauração).
psql "$DATABASE_URL" -At -F ' ' -c "
  SELECT 'timeclock_timerecord', count(*) FROM timeclock_timerecord
  UNION ALL SELECT 'audit_auditlog', count(*) FROM audit_auditlog
  UNION ALL SELECT 'operations_employee', count(*) FROM operations_employee
  UNION ALL SELECT 'attendance_periodclosing', count(*) FROM attendance_periodclosing
  UNION ALL SELECT 'max_nsr_sum', COALESCE(sum(last_nsr), 0) FROM timeclock_nsrcounter" > "$base.manifest"

if [[ -n "${BACKUP_PASSFILE:-}" ]]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$base.dump" -out "$base.dump.enc" -pass "file:$BACKUP_PASSFILE"
  rm -f "$base.dump"
  file="$base.dump.enc"
else
  file="$base.dump"
fi
sha256sum "$file" > "$file.sha256"
echo "backup: $file"
echo "manifesto: $base.manifest"
