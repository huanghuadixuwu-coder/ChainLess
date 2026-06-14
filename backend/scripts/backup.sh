#!/bin/bash
# backup.sh - PostgreSQL database backup script.
#
# Creates a timestamped SQL dump in BACKUP_DIR.
#
# Usage:
#   ./scripts/backup.sh
#
# Environment variables:
#   DB_USER      PostgreSQL user (default: chainless)
#   DB_HOST      database host (default: db)
#   DB_NAME      database name (default: chainless)
#   DB_PASSWORD  PostgreSQL password (default: chainless_dev)
#   BACKUP_DIR   output directory (default: /backups)

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d-%H%M%S)

DB_USER="${DB_USER:-chainless}"
DB_HOST="${DB_HOST:-db}"
DB_NAME="${DB_NAME:-chainless}"
DB_PASSWORD="${DB_PASSWORD:-chainless_dev}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

mkdir -p "$BACKUP_DIR"

if ! command -v pg_dump >/dev/null 2>&1; then
    echo "ERROR: pg_dump is not installed in this container" >&2
    exit 127
fi

export PGPASSWORD="$DB_PASSWORD"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}-${TIMESTAMP}.sql"
TMP_FILE="${BACKUP_FILE}.partial"

pg_dump \
    --format=plain \
    --no-owner \
    --no-privileges \
    -U "$DB_USER" \
    -h "$DB_HOST" \
    "$DB_NAME" > "$TMP_FILE"

mv "$TMP_FILE" "$BACKUP_FILE"

echo "Backup: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
