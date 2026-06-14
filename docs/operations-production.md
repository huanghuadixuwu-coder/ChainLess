# Chainless Production Operations

This document records the current single-machine runtime and the approved
Chainless V1 production topology. Remaining production implementation is owned
only by
`docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`.

## Supported Deployment

The supported local-Docker deployment command is:

```bash
docker-compose up -d
```

For Windows Codex sessions, also read
`docs/remote-windows-runtime-notes.md` before rebuilding or running QA. It
records known PowerShell quoting, compose rebuild, health-check, and browser
automation pitfalls. Historical remote-server details in that note are not an
active runtime target.

The verified compose stack starts Nginx, PostgreSQL, Redis, backend, frontend,
ARQ worker, sandbox proxy, and the sandbox image holder. Nginx is the only
service that publishes a production host port.

Public access:

- Application: `http://<host>/`
- API: `http://<host>/api/v1/`
- Liveness: `http://<host>/api/v1/health`
- Admin health: `http://<host>/api/v1/system/health`
- Admin metrics: `http://<host>/api/v1/system/metrics`

DB, Redis, backend, frontend, sandbox-proxy, worker, and sandbox do not publish
production host ports. Use `docker-compose.debug.yml` only when localhost-bound
direct ports are explicitly required for debugging.

## Reverse Proxy / TLS

Compose-managed Nginx routes `/api/v1/*`, `/docs`, and `/openapi.json` to the
backend and all other traffic to the frontend. SSE buffering is disabled and
timeouts are extended.

HTTP is the default profile and does not reference certificate files. To enable
TLS, provide `nginx/certs/fullchain.pem` and `nginx/certs/privkey.pem`, then run:

```bash
docker-compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

The TLS override was verified with temporary test certificates; those
certificates are not retained in the repository or production checkout.

Backend and worker have a non-published egress network for LLM, web, and
channel delivery. Data and sandbox control networks remain internal, and
sandbox execution defaults to `network_mode=none`.

## Production Secrets

Production startup fails closed for placeholder DB, JWT, encryption, proxy, or
bootstrap-admin credentials. Populate `.env` before first startup. The
bootstrap admin password is used only to create the default admin and to rotate
the historical `admin123` password once; an already-customized password is not
overwritten.

## Accepted Runtime Versions

The working runtime versions are accepted implementation drift and must not be
downgraded merely to match the historical 2026-06-02 documents:

- Next.js `16.2.7`
- React `19.2.4`
- PostgreSQL `16` via `pgvector/pgvector:pg16`

## Health

Public liveness for Docker, Nginx, and external probes:

```bash
curl http://localhost/api/v1/health
```

Expected:

```json
{"status": "ok"}
```

Detailed operational health is an admin Settings endpoint. Use an admin bearer
token:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost/api/v1/system/health
```

Expected healthy shape:

```json
{
  "status": "ok",
  "db": "connected",
  "redis": "connected",
  "worker": "ok",
  "sandbox_pool": 2,
  "checks": {
    "db": {"status": "connected"},
    "redis": {"status": "connected"},
    "worker": {"status": "ok"},
    "sandbox": {"status": "ok"}
  }
}
```

The worker check is backed by a Redis heartbeat written on worker startup and
each scheduler cron tick.

## Metrics

Metrics are also admin-only:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost/api/v1/system/metrics
```

The endpoint emits Prometheus-style gauges for:

- `chainless_db_up`
- `chainless_redis_up`
- `chainless_worker_up`
- `chainless_sandbox_up`
- `chainless_sandbox_pool_size`
- `chainless_sandbox_total_containers`
- `chainless_rate_limit_enabled`
- `chainless_rate_limit_per_minute`

## Rate Limiting

HTTP rate limiting is enabled by default with `RATE_LIMIT_ENABLED=true` and
`RATE_LIMIT_PER_MINUTE=300`. The default is intentionally high enough for a
normal authenticated admin to traverse the settings console without spurious
429s while still bounding request floods.

Probe example:

```bash
for i in $(seq 1 310); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    http://localhost/api/v1/system/metrics
done
```

The response should eventually return `429` for the same client IP inside the
one-minute window. Public liveness and OpenAPI documentation paths are
excluded.

## Backup

Backups are written to the named Docker volume mounted at `/backups`.

Run:

```bash
docker-compose exec backend ./scripts/backup.sh
```

List artifacts:

```bash
docker-compose exec backend ls -lh /backups
```

Each backup is a plain SQL dump named:

```text
chainless-YYYYmmdd-HHMMSS.sql
```

## Restore

Before restore, stop application writers if possible:

```bash
docker-compose stop backend worker frontend
docker-compose up -d db redis
```

Restore a selected backup:

```bash
docker-compose run --rm backend ./scripts/restore.sh /backups/chainless-YYYYmmdd-HHMMSS.sql
```

Restart the app:

```bash
docker-compose up -d
```

Validate:

```bash
curl http://localhost/api/v1/health
```

Restore is intentionally explicit and does not drop the database for you. If a
full destructive restore is needed, first create a fresh backup, then recreate
the database volume in a maintenance window.
