#!/bin/bash
# restore.sh - restore a Chainless PostgreSQL SQL dump.
#
# Usage:
#   ./scripts/restore.sh /backups/chainless-YYYYmmdd-HHMMSS.sql
#
# Environment variables mirror backup.sh:
#   DB_USER, DB_HOST, DB_NAME, DB_PASSWORD

set -euo pipefail

RESTORE_FILE="${1:-${RESTORE_FILE:-}}"
DB_USER="${DB_USER:-chainless}"
DB_HOST="${DB_HOST:-db}"
DB_NAME="${DB_NAME:-chainless}"
DB_PASSWORD="${DB_PASSWORD:-chainless_dev}"

if [ -z "$RESTORE_FILE" ]; then
    echo "Usage: ./scripts/restore.sh /path/to/backup.sql" >&2
    exit 2
fi

if [ ! -f "$RESTORE_FILE" ]; then
    echo "ERROR: restore file not found: $RESTORE_FILE" >&2
    exit 2
fi

if ! command -v psql >/dev/null 2>&1; then
    echo "ERROR: psql is not installed in this container" >&2
    exit 127
fi

export PGPASSWORD="$DB_PASSWORD"

psql \
    -v ON_ERROR_STOP=1 \
    -U "$DB_USER" \
    -h "$DB_HOST" \
    -d "$DB_NAME" \
    -f "$RESTORE_FILE"

echo "Restore completed: ${RESTORE_FILE}"
