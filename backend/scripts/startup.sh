#!/bin/bash
# startup.sh — entrypoint for the Chainless backend Docker container.
#
# Runs database migrations and seeding before handing control to uvicorn.
# All steps are idempotent.
#
# Usage:
#   ./scripts/startup.sh          (development, with --reload)
#   APP_RELOAD=0 ./scripts/startup.sh   (production, without --reload)

set -e

RELOAD_FLAG="--reload"
if [ "${APP_RELOAD:-1}" = "0" ] || [ "${APP_RELOAD}" = "false" ]; then
    RELOAD_FLAG=""
fi

echo ">>> Running database migrations..."
alembic upgrade head
echo ">>> Migrations applied."

echo ">>> Seeding default data..."
python scripts/seed.py
echo ">>> Seed complete."

echo ">>> Starting uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ${RELOAD_FLAG}
