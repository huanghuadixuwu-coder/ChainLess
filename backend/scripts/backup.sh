#!/bin/bash
# backup.sh — PostgreSQL database backup script.
#
# Creates a timestamped SQL dump in the BACKUP_DIR directory.
# Designed to be run as a cron job or on-demand.
#
# Usage:
#   ./scripts/backup.sh
#
# Environment variables (optional):
#   DB_USER      — PostgreSQL user (default: chainless)
#   DB_HOST      — database host   (default: db)
#   DB_NAME      — database name   (default: chainless)
#   DB_PASSWORD  — PostgreSQL password (default: chainless_dev)
#   BACKUP_DIR   — output directory (default: /backups)

set -e

TIMESTAMP=$(date +%Y%m%d-%H%M%S)

DB_USER="${DB_USER:-chainless}"
DB_HOST="${DB_HOST:-db}"
DB_NAME="${DB_NAME:-chainless}"
DB_PASSWORD="${DB_PASSWORD:-chainless_dev}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

mkdir -p "$BACKUP_DIR"

export PGPASSWORD="$DB_PASSWORD"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}-${TIMESTAMP}.sql"

pg_dump -U "$DB_USER" -h "$DB_HOST" "$DB_NAME" > "$BACKUP_FILE"

echo "Backup: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
