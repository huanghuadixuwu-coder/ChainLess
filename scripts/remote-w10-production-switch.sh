#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

DB_NEW="$(openssl rand -hex 24)"
SECRET_NEW="$(openssl rand -hex 32)"
ENC_NEW="$(openssl rand -hex 32)"
PROXY_NEW="$(openssl rand -hex 32)"
ADMIN_NEW="$(openssl rand -hex 24)"
ENV_BACKUP=".env.pre-w10-$(date +%Y%m%d%H%M%S)"
cp .env "$ENV_BACKUP"

docker exec -i chainless-db psql \
  -U chainless \
  -d chainless \
  -v ON_ERROR_STOP=1 \
  -v new_password="$DB_NEW" <<'SQL' >/dev/null
ALTER USER chainless WITH PASSWORD :'new_password';
SQL

set_key() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

set_key DB_PASSWORD "$DB_NEW"
set_key SECRET_KEY "$SECRET_NEW"
set_key SECRET_ENCRYPTION_KEY "$ENC_NEW"
set_key PROXY_AUTH_TOKEN "$PROXY_NEW"
set_key BOOTSTRAP_ADMIN_PASSWORD "$ADMIN_NEW"
set_key APP_ENV production
chmod 600 .env

# Retire the old holder and all legacy dynamic sandboxes before the labeled pool starts.
docker ps -aq --filter ancestor=chainless_sandbox:latest | xargs -r docker rm -f >/dev/null 2>&1 || true
docker rm -f \
  chainless-nginx \
  chainless-backend \
  chainless-worker \
  chainless-frontend \
  chainless-sandbox-proxy \
  chainless-db \
  chainless-redis \
  chainless-sandbox >/dev/null 2>&1 || true

docker-compose up -d --no-build

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1/api/v1/health >/tmp/chainless-w10-health.json 2>/dev/null; then
    cat /tmp/chainless-w10-health.json
    printf '\n'
    docker-compose ps
    exit 0
  fi
  sleep 5
done

echo "Production health did not become ready; environment backup: $ENV_BACKUP" >&2
docker-compose ps >&2
docker-compose logs --tail=100 backend sandbox-proxy nginx >&2
exit 1
