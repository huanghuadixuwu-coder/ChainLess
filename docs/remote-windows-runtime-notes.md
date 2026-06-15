# Remote Runtime Notes for Windows Codex Sessions

These notes capture operational pitfalls from earlier remote-Docker work and
the current local-Docker Windows workflow. Read this before spending time on
Docker rebuilds, browser QA, or PowerShell-driven checks.

## Runtime Boundary

- Current active runtime is local Docker Desktop. Do not use the old remote
  server; it has been permanently shut down.
- Do not use host Python/Node as the app runtime. Run project commands inside
  Compose services.
- Historical remote Docker details are kept below only for archaeology:

```text
host: 118.196.142.31
user: dige
project: /home/dige/chainless
start: docker-compose up -d
```

Use local Windows only for browser automation through
`scripts/windows-browser-qa.ps1`.

## SSH From PowerShell

Password auth from non-interactive PowerShell needs `SSH_ASKPASS`; plain `ssh`
often hangs or fails to prompt correctly.

Use this pattern:

```powershell
$askpass = Join-Path $env:TEMP 'chainless_ssh_askpass.cmd'
if (-not (Test-Path $askpass)) {
  "@echo off`r`necho <remote-password>" | Set-Content -Path $askpass -Encoding ASCII
}
$env:SSH_ASKPASS = $askpass
$env:SSH_ASKPASS_REQUIRE = 'force'
$env:DISPLAY = 'codex'

ssh -o StrictHostKeyChecking=no dige@118.196.142.31 "cd /home/dige/chainless && docker-compose ps"
```

Avoid repeatedly rediscovering this. If SSH appears stuck, first confirm these
three env vars are set.

## PowerShell Quoting

PowerShell can mangle nested shell/Python/JSON quoting. Prefer one of these:

- Historical remote commands should not be used for active work. If reading old
  notes, translate the operation to local Docker first.
- For file edits, edit locally with `apply_patch`; do not copy files to the
  retired remote project.
- Do not rely on local Python or remote `python3`. Use container Python inside
  `docker-compose exec` or `docker-compose ... run`.
- Do not embed quoted SQL, JSON, or `python -c` expressions in SSH commands.
  Put the operation in a repository script and invoke the script path.
- Do not use Docker Go-template `index` lookups for labels containing dots from
  PowerShell, e.g. `{{index .Config.Labels "chainless.sandbox.proxy_owner"}}`.
  It can silently return blank and make cleanup filters overmatch. Prefer
  `docker inspect --format '{{json .Config.Labels}}' <id>` and filter the JSON
  output, or use `docker ps --filter label=key=value`.

Historical remote-only pattern, retained for archaeology and not for active
local-Docker work:

```powershell
ssh -o StrictHostKeyChecking=no dige@118.196.142.31 @'
cd /home/dige/chainless
python3 - <<'PY'
print("remote python ok")
PY
'@
```

If JSON quoting is painful, put the logic in a repo script and copy it to the
remote host rather than building a giant one-liner.

For local Docker container Python probes from PowerShell, prefer piping a
single-quoted here-string into container stdin instead of embedding Python in a
quoted `sh -lc` string:

```powershell
@'
print("container python ok")
'@ | docker compose exec -T backend sh -lc "PYTHONPATH=/app python -"
```

## Syncing Files to Remote

When editing locally, sync only the files changed for the slice:

```powershell
scp -o StrictHostKeyChecking=no path\to\file dige@118.196.142.31:/home/dige/chainless/path/to/file
```

Create remote directories first when syncing new folders:

```powershell
ssh -o StrictHostKeyChecking=no dige@118.196.142.31 "mkdir -p /home/dige/chainless/scripts"
```

## Docker Compose Rebuild Pitfall

On this remote host, `docker-compose up -d --build backend` previously produced
anonymous exited backend containers instead of restoring the canonical
`chainless-backend` container.

Compose v1 may fail with `KeyError: 'ContainerConfig'` while recreating a
service. Remove only the named service container first, then create it without
dependencies:

```bash
cd /home/dige/chainless
docker-compose build backend
docker rm -f chainless-backend
docker-compose up -d --no-build --no-deps backend
docker-compose ps
```

Frontend rebuild flow that worked:

```bash
cd /home/dige/chainless
docker build -t chainless_frontend:latest ./frontend
docker rm -f chainless-frontend >/dev/null 2>&1 || true
docker-compose up -d --no-build --no-deps frontend
docker-compose ps
```

After any rebuild, verify the canonical container names, not just any container
with a similar image.

Historical note: before W11, when `backend` was recreated, restarting `nginx`
was required because static upstream DNS could keep the old backend container
IP and return `502 Bad Gateway`.

Current W11 state: [nginx/conf.d/chainless.conf](../nginx/conf.d/chainless.conf)
uses Docker DNS resolver variables, so the expected verification is to rebuild
or recreate backend while leaving Nginx running, then prove both public and
internal health:

```powershell
curl -fsS http://127.0.0.1/api/v1/health
docker-compose exec -T nginx wget -qO- http://backend:8000/api/v1/health
```

## Health and Metrics Checks

Use public liveness as the first-line verification:

```bash
curl -fsS http://127.0.0.1/api/v1/health
```

Expected public response:

```json
{"status":"ok"}
```

Detailed health and metrics are admin-only Settings endpoints. Use an admin
bearer token when checking operational internals:

```bash
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1/api/v1/system/health
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1/api/v1/system/metrics | head -n 20
```

Expected admin-only healthy signals include:

- `status: ok`
- `db: connected`
- `redis: connected`
- `worker: ok`
- sandbox `status: ok`
- metrics gauges for db, redis, worker, and sandbox all `1`

For rate-limit probes, clear test keys first if the test requires a clean
window:

```bash
docker-compose exec -T redis redis-cli --scan --pattern 'ratelimit:*' | xargs -r docker-compose exec -T redis redis-cli del
```

Settings browser QA can legitimately make many authenticated API calls. If a
normal Settings workflow hits `429`, do not just retry. First inspect Redis
keys:

```bash
docker compose exec -T redis sh -lc "redis-cli --scan --pattern 'ratelimit:*' | sort"
```

Expected post-fix keys use `ratelimit:user:<tenant_id>:<user_id>` for
authenticated requests and `ratelimit:ip:<addr>` for anonymous/login traffic.
If one UI action fans out into many unrelated settings endpoints, fix the
frontend to refresh only the affected section instead of raising limits.

## Browser QA Pitfalls

Use the repo-local Windows QA launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite workstream10 -TimeoutMs 90000
```

Current local-Docker runtime should use `http://localhost` instead of the
retired remote-server URL:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite workstream5 -TimeoutMs 90000
```

Known Playwright pitfalls:

- Avoid strict ambiguous locators like `getByText(/url/i)` when the same text can
  appear in both chat and the right panel.
- Scope right-panel checks with `getByRole("complementary")`.
- Use `.first()` when the app intentionally has repeated labels such as
  `New Chat`.
- Treat `_next/webpack-hmr` as a dev-only signal; production frontend should not
  emit it.
- Keep cleanup in `finally` so failed QA runs still remove test conversations.
- Browser QA uses a fixed non-admin QA tenant by default and purges its created
  conversations through `DELETE ...?purge=true`.
- If using Playwright directly in this Windows session, pass the installed
  Chrome executable path:
  `C:\Program Files\Google\Chrome\Application\chrome.exe`. The bundled
  Playwright package may exist even when its downloaded browser binary does not.
- Avoid asserting only the first active Settings tab. Browser smoke for
  Settings must click Provider, Channel, Skills, Eval, and System.
- React hydration `#418` can be caused by reading `localStorage` directly
  during render. Use the token snapshot hook instead of ad-hoc render-time
  `api.getToken()` checks.
- Mounting the whole frontend directory into a Docker image can hide the
  container's `node_modules` on Windows. For linting current source against a
  built image, mount only `frontend\src` to `/app/src`.

## PowerShell / Docker Command Pitfalls

- Do not pipe Docker output to Unix tools on the Windows host unless the tool is
  actually installed. For example, `docker-compose exec redis redis-cli --scan |
  grep ...` runs `grep` on the host and fails. Put the pipe inside the container:
  `docker-compose exec -T redis sh -lc "redis-cli --scan | grep -E 'prefix' || true"`.
- PowerShell expands `$key:` before Docker sees it. If a loop needs shell
  variables, wrap the entire container script in single quotes or avoid shell
  variables entirely.
- Do not use PowerShell heredocs as if they were Bash heredocs. If a container
  command needs `python - <<'PY'`, wrap that heredoc inside `sh -lc "..."`.
- The default `backend-test pytest -q` can run stale `/app` code from the image.
  To test the current worktree mounted at `/repo/backend`, use:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"`.
- `node` may not be in host `PATH`. The Windows browser QA launcher uses the
  Codex bundled Node automatically; for manual syntax checks use the bundled
  Node printed by `scripts\windows-browser-qa.ps1`.

## Frontend Build Pitfall

Do not reintroduce `next/font/google` without an explicit offline build plan.
It made Docker builds depend on live Google Fonts fetches and failed
intermittently. The current runtime uses Next's bundled local Geist font files
through `next/font/local`, preserving the existing font variables while keeping
Docker builds reproducible.

After QA, check for leftover generated conversations:

```bash
docker-compose exec -T backend python scripts/cleanup_qa_conversations.py
```

## Test Data Discipline

- Browser QA must delete conversations it creates.
- Do not bulk-delete real user data.
- Only delete known test records by exact id or by a test-specific title prefix
  such as `WS10 QA`.
- Confirm cleanup with a read-only list check before closing the workstream.

## Build Dependency Pitfall

The sandbox-proxy build previously hung because its Dockerfile used an
unmirrored, unpinned `pip install`. Keep `sandbox-proxy/requirements.txt`
pinned and use the configured Tsinghua mirror. If a build appears stuck, inspect
the remote process tree before retrying; do not launch a second build blindly.

## Current GStack Boundary

This Windows session has a repo-local Playwright QA path. It is not the exact
upstream `gstack /qa` browser daemon path. Do not spend time trying to use the
macOS-specific `chrome-cdp` helper here; use `scripts/windows-browser-qa.ps1`
unless a new Windows-compatible gstack driver is explicitly installed.
