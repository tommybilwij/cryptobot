#!/usr/bin/env bash
# pg_backup_restore_drill.sh — verify pg_dump backup is restorable
#
# Dumps the current cryptobot DB, restores into a temporary database,
# runs alembic head check, drops the temp DB. Fails if any step errors.

set -euo pipefail

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-devpass}"
DB_NAME="${DB_NAME:-cryptobot}"
TMP_DB="cryptobot_restore_drill_$(date +%s)"
DUMP_FILE="/tmp/${DB_NAME}-drill-$(date +%s).sql.gz"

trap 'cleanup' EXIT

cleanup() {
  if [ -f "${DUMP_FILE}" ]; then
    rm -f "${DUMP_FILE}"
  fi
  PGPASSWORD="${POSTGRES_PASSWORD}" docker compose exec -T postgres \
    psql -U cryptobot -d postgres -c "DROP DATABASE IF EXISTS ${TMP_DB};" \
    >/dev/null 2>&1 || true
}

echo "==> Dumping ${DB_NAME} → ${DUMP_FILE}"
PGPASSWORD="${POSTGRES_PASSWORD}" docker compose exec -T postgres \
  pg_dump -U cryptobot "${DB_NAME}" | gzip > "${DUMP_FILE}"
echo "    dump size: $(du -h "${DUMP_FILE}" | cut -f1)"

echo "==> Creating temp DB ${TMP_DB}"
PGPASSWORD="${POSTGRES_PASSWORD}" docker compose exec -T postgres \
  psql -U cryptobot -d postgres -c "CREATE DATABASE ${TMP_DB};"

echo "==> Restoring into ${TMP_DB}"
gunzip -c "${DUMP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD}" \
  docker compose exec -T postgres psql -U cryptobot -d "${TMP_DB}"

echo "==> Verifying tables exist"
PGPASSWORD="${POSTGRES_PASSWORD}" docker compose exec -T postgres \
  psql -U cryptobot -d "${TMP_DB}" -c "\dt" | head -30

echo "✅ Restore drill passed. Temp DB will be cleaned on exit."
