# Chainless V1 Spec Completion Evidence

## Workstream 1

Status: complete by local evidence-gated fallback

- Authority synchronization updated:
  - `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`
  - `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`
  - `PROBLEM_TODO_LIST.md`
  - `docs/operations-production.md`
  - `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
  - `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- Original authority documents were only amended with seven-line notices:
  `git diff --numstat -- docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md docs/aegis/plans/2026-06-02-chainless-implementation.md`
  returned `7 0` for each file.
- W1 assertion gate passed:
  - no ambiguous matrix owners
  - every `implemented-and-verified` row ends in `closed baseline`
  - `PROBLEM_TODO_LIST.md` has no unchecked problem items
  - matrix and historical checklist contain no non-ASCII authority text
  - scoped `git diff --check -- docs/aegis PROBLEM_TODO_LIST.md docs/operations-production.md` passed
- Review evidence:
  - Spec-compliance review approved after floating V1 requirements were mapped.
  - Stage 2 quality review found six fixable issues; all six were repaired.
  - Final sub-agent re-review was attempted but blocked by platform usage limit
    until 2026-06-06 03:12. This record does not claim sub-agent approval.
- Scope note:
  - `backend/app/api/v1/channels.py` has a pre-existing EOF blank-line
    `git diff --check` finding outside W1's document-only edit scope. It is
    not used as W1 completion evidence and remains available for W2/runtime
    cleanup if it intersects later work.

## Workstream 2

Status: complete by local evidence-gated fallback

- API contract owners added and wired:
  - `backend/app/api/contracts.py`
  - `backend/app/api/pagination.py`
  - `backend/app/middleware/error_handler.py`
- Test/runtime isolation added:
  - `backend/requirements.txt`
  - `backend/requirements-test.txt`
  - `backend/pytest.ini`
  - `backend/tests/conftest.py`
  - `docker-compose.test.yml`
  - `backend/scripts/spec_contract_probe.py`
  - `scripts/qa/api-client.cjs`
  - `scripts/qa/cleanup-registry.cjs`
  - `scripts/qa/suite-registry.cjs`
- Remote Docker test evidence:
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py`
  - Result: `15 passed in 5.65s`
- Test service evidence:
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml config`
    completed successfully.
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml build backend-test-server frontend-test`
    completed successfully.
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml up -d backend-test-server frontend-test`
    reached `backend_test_server_health=healthy`, `frontend_test_state=running`,
    and `frontend_ready=1`.
  - `docker exec chainless-backend-test-server python scripts/spec_contract_probe.py --base-url http://127.0.0.1:8000`
    returned `{"ok": true}`.
  - `docker exec chainless-frontend-test wget -qO- http://127.0.0.1:3000/login`
    returned the login page HTML.
- Live runtime evidence after backend/worker rebuild:
  - `docker-compose build backend worker` completed successfully.
  - `docker rm -f chainless-backend chainless-worker` followed by
    `docker-compose up -d --no-build backend worker` completed successfully.
  - `docker inspect -f '{{.State.Health.Status}}' chainless-backend` returned
    `healthy`.
  - `docker-compose exec -T backend python scripts/spec_contract_probe.py --base-url http://127.0.0.1:8000`
    returned `{"ok": true}` after adding proactive runs coverage.
  - Backend container OpenAPI check returned
    `{'ok': True, 'missing': [], 'paths': 29}`.
  - `GET /api/v1/system/health` returned `status: ok`, DB connected, Redis
    connected, worker ok, and sandbox status ok with pool size 2.
- Windows/local non-runtime evidence:
  - `git diff --check -- backend/app/api backend/app/core/proactive backend/app/middleware backend/Dockerfile backend/requirements.txt backend/requirements-test.txt backend/pytest.ini backend/tests backend/scripts/spec_contract_probe.py docker-compose.test.yml scripts docs/aegis PROBLEM_TODO_LIST.md docs/operations-production.md`
    exited `0` with CRLF warnings only.
  - Node syntax checks passed for `scripts/windows-browser-qa.cjs` and
    `scripts/qa/*.cjs`.
  - `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://118.196.142.31:3000 -Browser chrome -Headless -Suite smoke -TimeoutMs 30000`
    returned `ok: true`; report directory:
    `.gstack/qa-reports/local/smoke-2026-06-05T16-09-47-759Z/`.
- Cleanup evidence:
  - Test containers were removed after verification.
  - Final `docker-compose ps` listed only live runtime containers:
    backend, db, frontend, redis, sandbox, sandbox-proxy, and worker.
- Review evidence:
  - Sub-agent review was not claimed for W2 because platform quota remained
    blocked until 2026-06-06 03:12.
  - Completion authority is from the direct evidence above.
- Scope note:
  - Built-in tools and channel definitions are authenticated runtime API
    surfaces, not persistent tenant resources.
  - MCP manager state remains explicitly runtime-ephemeral for W2; MCP
    transport lifecycle hardening is owned by W8.

## Workstream 3

Status: complete by local evidence-gated fallback

- Canonical SSE owners added:
  - `backend/app/api/sse.py`
  - `backend/app/services/conversation_stream_service.py`
- Conversation route ownership reduced:
  - `backend/app/api/v1/conversations.py` now owns CRUD, context assembly, and
    request validation.
  - Stream formatting, agent event adaptation, heartbeat handling,
    confirmation persistence, and assistant-message persistence moved to
    `conversation_stream_service`.
- Public event contract repaired:
  - Backend public SSE emits canonical `tool_call`, `tool_result`, `sandbox`,
    `sandbox_output`, `confirmation_required`, `done`, `error`, `heartbeat`,
    and `text`.
  - Internal `tool_call_start` maps to public `tool_call`.
  - Internal `tool_error` maps to public `tool_result` with `status: "error"`.
  - SSE `error` frames use the shared API error envelope including
    `code`, `message`, and `detail`.
- Code-as-Action evidence path repaired:
  - `stream_code_as_action` emits sandbox lifecycle and output events while
    `execute_code_as_action` remains a compatible result-aggregation helper.
  - `run_agent` forwards `sandbox` and `sandbox_output` during Code-as-Action
    execution, then emits the final `tool_result`.
- Frontend parser updated without style changes:
  - `frontend/src/lib/api.ts` consumes canonical `tool_call` and
    `tool_result`; failed tools use `tool_result.status == "error"` or
    `tool_result.error`.
  - No frontend component, CSS, layout, visual style, or design token was
    changed in W3.
- Remote Docker test evidence:
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_sse_contract.py tests/test_api_contracts.py tests/test_tenant_isolation.py`
  - Result: `20 passed in 6.48s`
  - Coverage includes SSE formatting, canonical mapping, sandbox event emission,
    chat endpoint event order, assistant persistence once, and disconnect
    behavior that does not persist partial assistant messages.
- Live runtime evidence after backend/worker/frontend rebuild:
  - `docker-compose build backend worker frontend` completed successfully.
  - `docker-compose up -d --no-build backend worker frontend` completed
    successfully after removing stale live containers.
  - Backend health returned `healthy`.
  - `docker-compose exec -T backend python scripts/sse_contract_probe.py --base-url http://127.0.0.1:8000`
    returned `{"ok": true, "events": ["text", "done"]}`.
  - Backend OpenAPI check returned
    `{'ok': True, 'missing': [], 'paths': 29}` for chat and confirm routes.
  - `GET /api/v1/system/health` returned `status: ok`, DB connected, Redis
    connected, worker ok, and sandbox status ok with pool size 2.
- Browser regression evidence:
  - `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://118.196.142.31:3000 -Browser chrome -Headless -Suite workstream10 -TimeoutMs 60000`
    returned `ok: true`.
  - Report directory:
    `.gstack/qa-reports/local/workstream10-2026-06-05T16-35-32-189Z/`.
  - Steps passed: login, conversation create/rename/archive, chat SSE,
    tool-card web fetch, right-panel files, Code-as-Action, destructive
    confirmation deny, and cleanup-conversations.
- Local non-runtime evidence:
  - Node syntax checks passed for `scripts/windows-browser-qa.cjs` and
    `scripts/qa/*.cjs`.
  - Scoped `git diff --check` exited `0` with CRLF warnings only.
- Cleanup evidence:
  - Test containers were removed after W3 verification.
- Review evidence:
  - Sub-agent review was not claimed for W3 because platform quota remained
    blocked until 2026-06-06 03:12.
  - Completion authority is from the direct evidence above.

## Workstream 10

Status: complete by fresh direct evidence

- Production boundary:
  - Compose-managed `chainless-nginx` is the only public application service.
  - Frontend, API, SSE, docs, OpenAPI, health, and metrics use one origin.
  - Backend, frontend, database, Redis, sandbox-proxy, worker, and sandbox
    services do not publish production host ports.
  - Direct service ports remain available only through the localhost-bound
    debug override.
- Production configuration:
  - Production startup fails closed for placeholder database, JWT, encryption,
    proxy, and bootstrap-admin secrets.
  - `scripts/remote-w10-production-switch.sh` generates safe production values,
    rotates the historical bootstrap password, and recreates the canonical
    stack.
  - HTTP startup works without certificate files; the TLS override was proven
    with temporary certificates and then removed.
- Audit and startup:
  - Tenant-scoped admin-readable audit records cover mutations, authentication
    and security decisions, administration, destructive confirmations, and
    proactive actions without request bodies or secrets.
  - Clean derived startup applies migrations, performs idempotent seed, and
    proves login readiness.
- Sandbox boundary:
  - Sandbox execution uses network-none by default, read-only root filesystem,
    no-new-privileges, dropped capabilities, bounded CPU/memory/PID/time
    limits, scoped workspace mounts, and timeout/cancel cleanup.
  - Network whitelist and optional AppArmor boundaries are configurable without
    weakening the default profile.
  - The managed pool is bounded and self-heals to its configured minimum after
    expiry or unhealthy replacement.
  - Docker socket access remains inside sandbox-proxy; sandbox-proxy is not
    publicly reachable.
- Browser evidence:
  - `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://118.196.142.31 -Browser chrome -Headless -Suite workstream10 -TimeoutMs 60000`
    returned `ok: true`.
  - Report directory:
    `.gstack/qa-reports/local/workstream10-2026-06-06T15-17-11-199Z/`.
  - Login, conversation create/rename/archive, chat SSE, real web fetch,
    right-panel files, real Code-as-Action output `42`, destructive denial, and
    owner-scoped purge cleanup passed without console or page errors.
- Production boundary probe evidence:
  - `docker-compose exec -T backend python scripts/production_boundary_probe.py --base-url http://nginx`
    returned `ok: true`, proved tenant-scoped body-free audit records, returned
    real sandbox output `42`, and deleted the probe conversation.
- Retirement:
  - Direct ports retired as supported production URLs.
  - Unauthenticated placeholder production secrets, legacy `admin123`
    bootstrap behavior, unaudited mutation paths, and archive-only QA cleanup
    retired.
- Fresh final verification:
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml build backend-test`
    completed successfully.
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q`
    returned `43 passed in 11.13s`.
  - `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test python scripts/clean_start_probe.py`
    returned `{"ok": true, "migrations": "head", "seed": "idempotent", "login_ready": true}`.
  - `docker-compose exec -T backend python scripts/production_boundary_probe.py --base-url http://nginx`
    returned `ok: true`, sandbox output `42`, sandbox pool `2/2`, and
    `conversation-deleted`.
  - `docker-compose exec -T backend python scripts/cleanup_qa_conversations.py`
    returned `deleted_qa_conversations=0` after the final browser run.
  - Production health returned DB connected, Redis connected, worker ok, and
    sandbox pool `2/2`.
  - Base, debug, and TLS Compose configurations parsed successfully.
  - Final project container inspection found the eight canonical running
    containers and zero exited project containers.
  - Managed sandbox inspection found two containers with network-none,
    read-only root filesystems, 512 MiB memory limits, PID limit 128, dropped
    capabilities, and security options; Docker socket inspection found the
    socket only on sandbox-proxy.
  - Public listener inspection found no Chainless application ports other than
    Nginx port 80.
  - Bundled-Node syntax checks passed for `scripts/windows-browser-qa.cjs` and
    `scripts/qa/*.cjs`.
  - Scoped `git diff --check` exited `0` with CRLF warnings only.
- Scope restraint:
  - W10 made no frontend style, layout, spacing, color, or design changes.

## Workstream 4

Status: complete by fresh direct local-Docker evidence

- `SubAgentRuntime.finalize_parent_artifacts()` is the sole backend-owned
  lifecycle owner for `/workspace/runs/{parent}/sub_results`.
- Success, timeout, and error results are atomically persisted, observed as
  canonical `sandbox_output` artifact evidence, then removed at parent
  terminal. Owner markers, safe IDs, `O_NOFOLLOW`, and foreign-runtime tests
  prevent path escape and cross-run/cross-tenant cleanup.
- `spec_complete.json` uses a deterministic runtime probe rather than model
  self-reporting. A real disposable Code-as-Action parent makes two concurrent
  UDS `spawn_sub_agent` calls, proves overlap, aggregates both child results,
  observes canonical lifecycle/artifacts, and proves terminal cleanup.
- Fresh-image W4 gate:
  `169 passed, 3 skipped`.
- Fresh-image complete backend:
  `205 passed, 4 skipped`.
- Live local-Docker proof:
  `test_w4_live_proof.py` returned `1 passed`; `spec_complete` eval returned
  `1 / 1`, `100%`.
- Backend logs observed two success artifacts before cleanup and then reported
  `artifacts finalized ... count=2`. Proxy logs observed two child allocations,
  the real parent execute request, and run-scoped disposable parent start and
  confirmed deletion.
- The historical test-volume `runs/` residue created before the lifecycle
  owner existed was removed once from the derived test volume. A subsequent
  live proof and residue inspection found no run artifacts, disposable parent,
  control socket, or test-run container residue.
- Scope restraint:
  W4 final slice made no frontend file, style, layout, or behavior changes.

## Workstream 5 Slice 1

Status: complete by fresh direct local-Docker evidence

- Added additive migration `0004` and canonical tenant-scoped
  `llm_providers` / `channel_configurations` models.
- Provider API and gateway now resolve exclusively from PostgreSQL; default
  selection is used by subsequent chat, memory, worker, smoke, and eval
  runtime paths.
- Provider API keys and Feishu webhook/signing secrets use Fernet authenticated
  encryption derived from the operator-managed `SECRET_ENCRYPTION_KEY`.
  Responses expose only stable mask metadata; blank updates preserve stored
  secrets.
- Provider/channel list, read, mutation, default selection, and test routes are
  admin-only and tenant-isolated. Mutations are covered by audit middleware;
  test actions also write explicit body-free audit records.
- Published `/channels/feishu` and `/channels/feishu/test` routes remain only
  as thin adapters over the generic database owner.
- Retired duplicate owner paths: provider API/gateway `_providers`,
  `LLMGateway.register()`, `GLM_API_KEY/default_llm_*` config/Compose runtime,
  and raw secret-bearing exception output.
- Fresh-image settings/security gate:
  `25 passed`.
- Fresh-image complete backend:
  `211 passed, 4 skipped`.
- Clean database proof:
  migrations applied `0001 -> 0002 -> 0003 -> 0004`; seed was idempotent and
  login-ready.
- `spec_complete` eval remained runnable and passed `1 / 1`, `100%` after the
  eval harness was migrated to the database provider owner.
- Compose configuration, `git diff --check`, retired-owner grep, secret/log
  regression checks, and residue inspection passed.
- Scope restraint:
  W5 slice 1 changed no frontend file, style, layout, or behavior.

### W5 Slice 1 Follow-up Hardening

Status: complete by sub-agent review plus fresh controller verification

- Provider connectivity test audit records now use stable route templates and
  provider UUIDs only; client-controlled provider names are not written to
  audit path/details.
- Sandbox-proxy now sets `SANDBOX_PROXY_OWNER` and
  `chainless.sandbox.proxy_owner` on managed and disposable containers.
  Production uses `chainless-production`; live test uses `chainless-test`.
- Startup cleanup, disposable cleanup, and owner-scoped Docker listing now
  avoid cross-proxy pool adoption/removal.
- `/health` reconciles in-memory pool state against Docker live state before
  reporting, forgets externally removed containers, removes unpingable
  containers, and replenishes to `POOL_MIN`.
- Sub-agent spec review result:
  `PASS` for admin-only DB-backed settings, write-only encrypted secrets,
  DB-owned provider runtime, proactive DB-owned channels, provider-test audit
  redaction, and sandbox owner isolation.
- Fresh target evidence:
  - `tests/test_secret_redaction.py tests/test_sandbox_security.py tests/test_sandbox_pool_lifecycle.py`
    returned `55 passed`.
  - `tests/test_admin_authorization.py tests/test_audit.py tests/test_proactive_channel_owner.py tests/test_provider_runtime_consumers.py`
    returned `34 passed`.
  - After the health repair, `tests/test_sandbox_pool_lifecycle.py tests/test_sandbox_security.py`
    returned `49 passed`.
- Fresh full backend evidence:
  `247 passed, 4 skipped`.
- Live eval evidence:
  `spec_complete` returned `1 / 1`, `100%`, with real sandbox allocation,
  recycle, and parallel Code-as-Action sub-agent artifact evidence.
- Production runtime evidence:
  - `production_boundary_probe.py` returned `ok: true`, sandbox output `42`,
    sandbox health pool `2/2`, and `conversation-deleted`.
  - `clean_start_probe.py` returned `ok: true`, migrations `head`, seed
    `idempotent`, and login-ready.
  - `inspect_proactive_redis.py` returned zero tasks, zero runs, and zero
    unsafe records.
  - Final Docker inspection found no disposable containers and exactly two
    managed containers, both labelled
    `chainless.sandbox.proxy_owner=chainless-production`.
- Runtime note:
  `docs/remote-windows-runtime-notes.md` now records local Docker as the active
  runtime and documents the PowerShell/Docker label-template pitfall that
  caused a transient derived sandbox-pool cleanup overmatch. The pool was
  immediately rebuilt by `/health`; no persistent data was affected.

## Workstream 5 Slice 2

Status: backend contract foundation complete by sub-agent implementation and
fresh controller verification

- Added tenant-scoped passive skill metadata owner:
  - `backend/app/models/skill.py`
  - `backend/alembic/versions/0005_add_skills.py`
  - `backend/app/api/v1/skills.py`
- Skills API provides admin-only create/list/get/update/delete and deterministic
  enabled-skill trigger matching. It stores metadata only; no V2 skill
  precipitation or arbitrary skill-code execution was introduced.
- Added admin-only eval administration API:
  - suite listing from existing eval task files
  - status listing from bounded result summaries
  - dry-run validation by default
  - optional bounded subprocess execution that does not return raw stdout or
    stderr
  - explicit body-free audit records for eval list/status/run actions
- Router/model exports now include skills and eval routes/models.
- Fresh target evidence:
  `tests/test_skill_trigger_matching.py tests/test_admin_authorization.py tests/test_api_contracts.py`
  returned `16 passed`.
- Fresh full backend evidence:
  `250 passed, 4 skipped`.
- Clean-start evidence:
  `clean_start_probe.py` returned `ok: true`, migrations `head`, seed
  `idempotent`, and login-ready after migration `0005`.
- Production runtime smoke:
  a unique temporary `w5-smoke-*` tenant/admin was created inside the backend
  container, `/eval/suites` and `/eval/run` dry-run were validated, a passive
  skill was created/matched/deleted through the API, and the exact temporary
  tenant was deleted in `finally`. Follow-up query returned
  `remaining_w5_smoke_tenants: []`.
- Live eval evidence:
  `spec_complete` remained `1 / 1`, `100%`.
- Residue evidence:
  no disposable sandbox containers, proactive Redis task/run/unsafe counts all
  zero, and all managed sandbox containers were labelled
  `chainless-production`.
- Scope restraint:
  W5 slice 2 changed no frontend file, style, layout, or behavior.

## Workstream 5 Slice 3

Status: frontend settings shell complete by sub-agent implementation and fresh
controller/browser verification

- Added an admin-only `/settings` surface wired to the already-verified
  provider, channel, passive skills, eval, and system-health contracts.
- Added a `platform-store` client owner for settings data loading and mutation.
  Secrets remain write-only in forms and render only backend masked metadata.
- Added a Settings entry to the existing sidebar without replacing the sidebar,
  conversation list, delete/rename behavior, global color system, or page
  layout.
- Fixed form-button semantics found during controller review:
  non-submit buttons in provider/channel/skill rows now use `type="button"` so
  test/default/delete actions do not accidentally submit update forms.
- Fixed production frontend quality gates found during browser verification:
  - `chat/page.tsx` no longer leaves an unused `sendMessage` binding or calls
    `setState` synchronously inside auth effects.
  - `chat/page.tsx` and `settings/page.tsx` now use `useTokenPresent()` so
    server prerender/hydration do not disagree about localStorage token state.
  - `api.setToken()` and `api.clearToken()` now emit a local token-change event
    for the token snapshot hook.
- Removed build-time Google Fonts dependency without changing the intended font
  family: `layout.tsx` now uses Next's bundled local Geist/Geist Mono font
  files and keeps the existing `--font-geist-*` variables. This makes Docker
  frontend builds reproducible without external Google font fetches.
- Docker verification:
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml build frontend-test`
    passed.
  - `docker run --rm -v "E:\Chainless\frontend\src:/app/src" chainless-frontend-test npm run lint`
    passed with zero warnings/errors.
  - `docker compose build frontend` passed.
  - `docker compose up -d frontend nginx` restarted the production frontend.
- API/runtime smoke:
  - `http://localhost/` returned `200`.
  - `http://localhost/api/v1/system/health` returned `status: ok`,
    `db: connected`, `redis: connected`, `worker: ok`, and sandbox pool `3`.
  - Authenticated admin API smoke returned role `admin`, eval suite count `2`,
    system health `ok`, and sandbox pool `3`.
- Browser smoke:
  - Local Chrome at
    `C:\Program Files\Google\Chrome\Application\chrome.exe` logged into a
    temporary admin tenant through the real UI.
  - `/settings` loaded and all tabs opened: Provider, Channel, Skills, Eval,
    and System.
  - Filtered browser result had `consoleErrors: []` and `failedRequests: []`.
  - The earlier React hydration `#418` page error was reproduced before the
    token snapshot fix and absent after the fix.
- Test-data cleanup:
  all temporary `w5-browser-*` tenants created during browser QA were deleted
  by exact test prefix.
- Remaining W5 scope:
  Agent, Tools/MCP, Memories, and Proactive administration are still disabled
  placeholders in the settings shell and must be implemented in the next W5
  slice before W5 can close.

## Workstream 5 Slice 4a

Status: backend administration contracts complete by sub-agent implementation,
two-stage review, and fresh controller verification

- Hardened Agent administration:
  - `/api/v1/agents` list/create/get/update/delete now require admin role.
  - Agent list uses bounded pagination validation.
  - Agent path ids are `uuid.UUID`, so invalid ids use the stable validation
    envelope instead of DB-level failures.
  - Tenant filtering remains enforced.
- Hardened Tools/MCP administration:
  - `/api/v1/tools` list/register/test/delete now require admin role.
  - Tool listing remains paginated and includes builtin plus Code-as-Action and
    MCP tools with risk/tool_type metadata.
  - Real MCP lifecycle success is tested through
    `backend/scripts/mcp_echo_server.py`: register, list, test `echo`, delete,
    and confirm second delete returns `TOOL_NOT_FOUND`.
  - MCP register/test failures now log raw exceptions server-side and return
    stable public messages without raw command/env/exception text.
- Hardened Proactive administration:
  - `/api/v1/proactive-tasks` list/create/delete and run-history view now
    require admin role.
  - Existing tenant isolation and Redis secret-safety behavior remain covered.
- Scope decision:
  `/api/v1/memories` was intentionally left as the existing authenticated user
  capability; the admin Settings UI may consume it without converting the
  entire memory API to admin-only.
- Review evidence:
  - Spec compliance re-review passed after the MCP success-path coverage was
    added.
  - Code-quality re-review passed after fixing MCP exception leakage, agent
    pagination bounds, and UUID path validation.
- Controller verification:
  `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_admin_authorization.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_proactive_channel_owner.py`
  returned `47 passed`.
- Remaining W5 scope:
  Frontend Settings panels must now expose Agent, Tools/MCP, Memories, and
  Proactive using these contracts, followed by browser QA and test-data
  cleanup.

## Workstream 5 Slice 4b

Status: frontend administration panels complete by controller implementation,
local-Docker verification, and real Windows Chrome browser evidence

- Added live Settings sections for:
  - Agent list/create/update/delete using the hardened admin-only Agent API.
  - Tools/MCP list/register/test/delete using the hardened admin-only Tools API.
  - Memories list/create/update/search/merge/delete using the existing
    authenticated memory contracts.
  - Proactive task list/create/delete and run-history view using the hardened
    admin-only Proactive API.
- Preserved the existing frontend visual language:
  reused the current zinc classes, existing Card/Button/Input primitives,
  Settings shell structure, sidebar entry, and dark visual baseline; no global
  style/theme/layout redesign was introduced.
- Fixed a real runtime issue found during browser QA:
  Settings mutations called the full `loadSettings()` fan-out after every
  create/update/delete, causing ordinary admin UI flows to exceed the
  production `60/min` rate limit.
- Rate-limit repair:
  authenticated requests now use a tenant/user rate-limit key instead of only
  the upstream Docker/Nginx IP, while anonymous/login traffic still falls back
  to IP. The IP fallback now prefers trusted `X-Real-IP` over client-spoofable
  `X-Forwarded-For`.
- Request-fanout repair:
  Agent, Tools/MCP, Memory, and Proactive mutations now refresh only their
  owning section data instead of reloading all platform settings. After code
  quality review, Provider, Channel, and Skill mutations were also moved to
  section-local refreshes so no Settings mutation path calls full
  `loadSettings()`.
- Fresh Docker verification:
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_rate_limit_identity.py tests/test_admin_authorization.py tests/test_api_contracts.py`
    returned `20 passed`.
  - `docker run --rm -v "E:\Chainless\frontend\src:/app/src" chainless-frontend-test npm run lint`
    passed.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml build frontend-test`
    passed.
  - Production `backend` and `frontend` images were rebuilt and restarted, and
    `nginx` was restarted after each recreation to avoid stale upstream IPs.
- Runtime health evidence:
  `GET http://localhost/api/v1/system/health` returned `status: ok`, DB
  connected, Redis connected, worker ok, and sandbox pool `3`.
- Browser smoke:
  - Local Windows Chrome at
    `C:\Program Files\Google\Chrome\Application\chrome.exe` logged into a
    temporary admin tenant through the real UI.
  - `/settings` opened every tab: Provider, Agent, Tools, Memories, Channel,
    Proactive, Skills, Eval, and System.
  - Real UI actions passed: Agent create/delete, Tools visible with builtin
    tool names and risk/type metadata, Memory create/search/delete, and
    Proactive create/delete.
  - Browser result had `consoleErrors: []`, `pageErrors: []`,
    `failedRequests: []`, and `responses429: []`.
  - Report directory:
    `.gstack/qa-reports/local/w5-settings-slice4b-2026-06-14T08-46-16-485Z/`.
- Review evidence:
  - Spec-compliance review passed with no blockers.
  - Code-quality review initially failed on spoofable anonymous IP rate-limit
    identity and incomplete Settings local-refresh coverage; both blockers
    were fixed and re-verified.
- Test-data cleanup:
  the exact `w5-ui-*` temporary tenants were deleted; follow-up query returned
  `remaining_w5_ui_tenants: []`, and proactive Redis inspection returned zero
  tasks, zero runs, and zero unsafe records.
- Remaining W5 scope:
  default-provider real chat proof, active-agent selection semantics,
  tool activation/risk override administration, spec-required dark-mode toggle,
  context banner, and final every-section browser QA ledger remain for the next
  W5 slice before W5 can close.

## Workstream 5 Final

Status: W5 platform settings and administration surface complete by
local-Docker verification, Windows Chrome browser QA, cleanup proof, and
independent review routing

- Completed the remaining Settings/runtime capabilities:
  - Provider list/create/test/default is browser-operable and a newly selected
    default provider is used by a subsequent real chat request.
  - Agent create/active selection is browser-operable and reflected in the chat
    context banner.
  - Builtin/MCP tools expose enable/risk override administration, MCP register,
    MCP test, and cleanup.
  - Memories support create/search/merge/delete from Settings.
  - Feishu channel configuration keeps secret fields write-only/masked.
  - Proactive tasks support create/delete/run-history visibility.
  - Passive skills support create/list/match/delete without claiming V2 skill
    precipitation.
  - System exposes health/eval/theme controls; the dark theme remains default
    and the toggle persists.
  - Chat renders the active context banner in the existing visual language.
- Runtime repairs found by final verification:
  - Production Settings flows were still too close to the default rate-limit
    budget. `RATE_LIMIT_PER_MINUTE` default is now `300`, documented as the
    production-safe baseline, while identity-based limiting remains in place.
  - `sandbox-proxy` could keep the idle pool above `POOL_MIN` after eval/recycle
    paths. Health reconciliation and recycle now trim surplus idle containers
    back to the configured target without deleting active allocations.
  - Code-quality review found that Memory Settings and detailed system
    health/metrics still allowed non-admin access. Memory CRUD/search/merge and
    `/api/v1/system/health` plus `/api/v1/system/metrics` now require admin
    role; public liveness moved to `/api/v1/health`.
  - Provider and Feishu forms now clear secret/create inputs only after
    successful mutations, so failed requests keep the user's entered values for
    correction.
- Fresh Docker verification:
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest tests/test_sandbox_pool_lifecycle.py -q`
    returned `13 passed`.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q`
    returned `266 passed, 4 skipped`.
  - `docker compose run --rm frontend npm run lint` passed with exit `0`.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_admin_authorization.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_production_config.py`
    returned `43 passed`.
  - `docker compose build backend worker frontend` passed, including the
    production frontend build.
  - `docker compose build sandbox-proxy` passed earlier for the pool-trim fix,
    then production services were recreated with
    `docker compose up -d --force-recreate backend worker frontend nginx`.
  - `docker compose exec -T backend sh -lc "PYTHONPATH=/app python scripts/clean_start_probe.py"`
    returned `{"ok": true, "migrations": "head", "seed": "idempotent",
    "login_ready": true}`.
  - `docker compose exec -T backend python scripts/run-eval.py --suite spec_complete`
    returned `Pass: 1 / 1`, `Fail: 0 / 1`, `Pass Rate: 100.00%` on the final
    warmed-pool run.
  - Admin-boundary production probe returned: public `/api/v1/health` `200`,
    unauthenticated detailed health/metrics `401`, member detailed health
    `403`, member memory mutation `403`, admin detailed health/metrics `200`.
  - Follow-up target verification after enhancing the reusable production
    boundary probe:
    `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_production_config.py tests/test_admin_authorization.py`
    returned `17 passed`.
  - Follow-up full backend verification returned `266 passed, 4 skipped`.
  - Rebuilt `backend` and `worker`, recreated `backend`, `worker`, and `nginx`,
    then ran:
    `docker compose exec -T backend python scripts/production_boundary_probe.py --base-url http://nginx`.
    It returned `ok: true`, sandbox output `42`, sandbox pool `2/2`, and:
    public health `200`, no-auth detailed health/metrics `401`, member
    detailed health/metrics/memory mutation `403`, admin detailed
    health/metrics `200`, and `cleanup:
    conversation-and-temp-tenant-deleted`.
  - Follow-up residue checks after the enhanced probe returned DB temporary
    tenant count `0`, Redis `*w5-boundary-probe*` count `0`, and
    `/run/chainless-control` count `0`.
- Runtime health evidence:
  - `GET http://localhost/api/v1/health` returned `{"status":"ok"}`.
  - Admin `GET http://localhost/api/v1/system/health` returned `status: ok`
    with DB/Redis/worker/sandbox checks and sandbox `pool_size: 2`,
    `total_containers: 2`.
  - Direct sandbox-proxy health returned
    `{"status":"ok","pool_size":2,"total_containers":2}`.
- Final Windows Chrome browser QA:
  - Command:
    `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite settings -TimeoutMs 120000 -Tenant w5-final-qa-1781439166 -Username qa-admin -Password [REDACTED] -ChatUsername qa-chat -ChatPassword [REDACTED]`
  - Report:
    `.gstack/qa-reports/local/settings-2026-06-14T12-12-55-633Z/report.json`.
  - Result: `ok: true`.
  - Passed steps: login, all nine Settings sections, provider create/mask/default,
    agent create/active, tool risk override reset, MCP register/test, memory
    create/search/merge, Feishu secret surface, proactive create/run-history,
    skill create/match, eval dry-run, dark-mode toggle persistence, chat login,
    and context-banner provider-switch proof.
  - Runtime provider-switch proof:
    conversation `ff3d5734-cc57-44a6-a2a9-ee7e6b0fbb5b` used provider
    `w5-final-1781439175944-provider`; the mock OpenAI-compatible provider saw
    one `/chat/completions` call (`mockCalls: 1`) and returned
    `provider-switch-ok:w5-final-1781439175944`.
  - Browser signals: `consoleErrors: []`, `pageErrors: []`,
    `requestFailures: []`, `responses429: []`, `ignoredRequestFailures: []`.
- Test-data cleanup:
  - Browser cleanup deleted the W5 conversation, providers, agent, memory,
    skill, proactive task, MCP server, and reset the tool risk override.
  - The temporary tenant `w5-final-qa-1781439166` was deleted by exact name.
  - Redis scan for `*w5*` returned `0`.
  - `/run/chainless-control` entry count returned `0`.
  - Database residual scan for W5 tenants/users/providers/agents/memories/
    skills/conversations/messages/channel configs/tool configs returned zero
    for every category.
- No-style-drift gate:
  - Final W5 work only added functional controls to the existing Settings/chat
    surfaces and reused the existing zinc classes, button/input primitives, and
    dark baseline.
  - No global style/theme redesign, chat width change, sidebar width change, or
    scroll-behavior change was introduced.
- W5 stop condition:
  no must-ship platform feature remains API-only after this slice.
- Independent review closure:
  sub-agent Newton returned `CODE_QUALITY_REVIEW: PASS` with no Critical or
  Important findings. Its only Minor note, production-boundary probe
  reproducibility for the full W5 auth-boundary matrix, was fixed and verified
  in the follow-up evidence above.

## Workstream 6

Status: real artifacts/files/diff flow complete by local-Docker verification,
Windows Chrome browser QA, cleanup proof, and independent review closure

- Added durable artifact owners:
  - `backend/app/models/artifact.py`
  - `backend/alembic/versions/0007_add_artifacts.py`
  - `backend/app/core/artifacts/service.py`
  - `backend/app/api/v1/artifacts.py`
  - `frontend/src/stores/artifact-store.ts`
  - `frontend/src/components/chat/file-artifact-list.tsx`
  - `frontend/src/components/chat/diff-view.tsx`
- Artifact metadata is tenant, conversation, message, tool-call, and run scoped.
  Bounded content and unified diffs are stored in the managed artifact volume,
  with per-file limits, per-tenant quota enforcement, retention cleanup, and
  orphan cleanup for failed commits or stale managed directories.
- File writes inside `/workspace` capture before/after content, generate
  unified diffs for text modifications, mark binary/oversized/deleted/missing
  states, and emit artifact references through canonical tool results.
- The right panel now renders real persisted Files and Diff data in the
  existing visual language. Empty content and empty diffs are rendered as loaded
  states instead of indefinite loading.
- Preview security is enforced end-to-end. The backend exposes one preview
  contract and denies artifact content reads for blocked, iframe-only, binary,
  oversized, or otherwise non-previewable artifacts; the frontend only fetches
  content for allowed code/text artifacts and renders allowlisted iframe or
  blocked preview states without changing the style.
- Review findings fixed:
  - confirmed tool execution now preserves `ToolExecutionResult.artifacts`
    while sending only text content back to the resumed LLM tool message.
  - artifact commit failures delete already-written managed files.
  - orphan cleanup removes unmanaged artifact directories left without database
    rows.
  - UTF-8 diff truncation preserves codepoint boundaries and appends an
    explicit truncation marker.
  - artifact content/diff caches use key presence, so empty strings are valid
    loaded values.
- Runtime issues found and fixed during verification:
  - Windows browser QA no longer assumes `admin123`; it reads
    `BOOTSTRAP_ADMIN_PASSWORD` or QA credentials from `.env`/environment.
  - streamed LiteLLM tool-call chunks tolerate missing `name` and `arguments`
    fields instead of raising `TypeError`.
  - artifact QA assertions are scoped to `artifact-file-list` rows to avoid
    strict locator ambiguity when the same path appears in chat text.
  - the W6 artifact browser suite is now owned by
    `scripts/qa/artifacts-suite.cjs`; the main Windows QA launcher only
    registers it.
- Fresh test evidence:
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_artifacts.py tests/test_preview_security.py tests/test_sse_contract.py tests/test_llm_gateway_streaming.py`
    returned `24 passed`.
  - Full backend verification returned `282 passed, 4 skipped`.
  - Frontend lint passed with exit `0`.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml build frontend-test`
    passed.
  - Bundled Node syntax checks for `scripts/windows-browser-qa.cjs` and
    `scripts/qa/artifacts-suite.cjs` passed.
  - `docker compose build backend worker frontend` passed, including the
    production frontend build.
  - `docker compose up -d --force-recreate backend worker frontend nginx`
    recreated production services; backend and Nginx were healthy.
- Fresh production probe evidence:
  - `docker compose exec -T backend sh -lc "PYTHONPATH=/app python scripts/clean_start_probe.py"`
    returned `{"ok": true, "migrations": "head", "seed": "idempotent",
    "login_ready": true}`.
  - `docker compose exec -T backend python scripts/production_boundary_probe.py --base-url http://nginx`
    returned `ok: true`, public/admin auth boundary proof, audit proof, sandbox
    output `42`, sandbox health pool `2/2`, and
    `cleanup: conversation-and-temp-tenant-deleted`.
- Final Windows Chrome artifact QA:
  - Command:
    `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite artifacts -TimeoutMs 90000`
  - Report:
    `.gstack/qa-reports/local/artifacts-2026-06-14T14-43-26-195Z/report.json`.
  - Result: `ok: true`.
  - Passed steps: auth login, mock provider default, conversation create,
    chat-triggered file write, Files tab real artifact, Diff tab real unified
    diff, reload-persisted artifact list, observed two-call tool loop, and
    cleanup-conversations.
  - Browser signals: `consoleErrors: []`, `pageErrors: []`,
    `requestFailures: []`, `responses429: []`,
    `ignoredRequestFailures`: one Next.js `_rsc` `net::ERR_ABORTED` navigation
    abort.
- Test-data cleanup:
  - PostgreSQL residual checks returned zero W6 providers, W6 conversations,
    and W6 artifacts.
  - `/data/artifacts` contained no `w6-artifacts-*` files.
  - Browser-created `/workspace/w6/w6-artifacts-*.py` files were deleted by
    exact pattern and the follow-up inspection returned no matches.
- Scope restraint:
  W6 changed frontend behavior only where needed for real artifact loading,
  preview policy, and right-panel data rendering. It did not redesign global
  styles, chat/sidebar layout, colors, spacing, scroll behavior, or the
  established dark visual baseline.
- W6 stop condition:
  Preview, Terminal, Files, and Diff all have real verified behavior for the
  current V1 artifact/tool surfaces; no W6 tail item remains.

## Workstream 7

Status: rich input and keyboard shortcuts complete by local-Docker
verification, Windows Chrome browser QA, cleanup proof, and independent review
closure

- Added the spec-required input workflow while preserving the established chat
  visual language:
  - `Ctrl+N` creates a new conversation.
  - `Ctrl+K` opens the command palette.
  - `Ctrl+Enter` still sends the current message.
  - `@tool` opens a live tools-API-backed picker with keyboard navigation,
    Enter/Tab selection, listbox/option semantics, and active-option ARIA
    state on the focused textarea.
  - `+file` and drag/drop uploads use the real artifact/upload contract and
    attach uploaded artifact ids to subsequent chat sends.
- Backend upload and attachment safeguards are implemented:
  tenant/conversation ownership, attachment artifact state and operation
  checks, filename normalization, traversal rejection, unsafe-name rejection,
  oversized rejection, binary-disallowed rejection, quota boundary, and
  content-policy hook boundary.
- Historical uploaded attachments are rechecked before later context assembly,
  so deleted or unavailable artifacts are not re-injected into future LLM
  turns.
- Markdown/code behavior is verified in the browser: syntax-highlighted code
  blocks render, copy works, and fold/unfold controls work.
- Long conversation rendering now uses real dynamic-height DOM windowing rather
  than a marker-only/content-visibility placeholder. Final browser evidence
  rendered 12 rows for 34 total messages with `scrollHeight=3730` and
  `clientHeight=795`.
- Runtime/review defects found and fixed:
  - historical uploaded attachment replay could include deleted artifacts;
    fixed at conversation context assembly and covered by regression test.
  - shortcut unsafe contexts returned before `preventDefault`; fixed in the
    chat shortcut owner and covered by browser QA.
  - `@tool` picker was not fully keyboard accessible; fixed with active option
    navigation, Enter/Tab selection, and ARIA state on the focused textarea.
  - virtual scrolling was a false positive because the viewport expanded to
    content height; fixed with real windowing and flex height boundaries.
  - multi-file upload could hide successful uploads after a later rejection;
    fixed by per-file upload handling that preserves successful attachment
    chips.
- Fresh backend evidence:
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_file_upload_security.py tests/test_artifacts.py tests/test_preview_security.py tests/test_sse_contract.py`
    returned `38 passed, 1 warning`.
  - Full backend verification:
    `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q`
    returned `297 passed, 4 skipped, 1 warning`.
- Fresh frontend evidence:
  - `docker run --rm -v "E:\Chainless\frontend\src:/app/src" chainless-frontend-test npm run lint`
    passed.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps frontend-test npm run lint`
    passed.
  - `docker compose -f docker-compose.yml -f docker-compose.test.yml build --no-cache frontend-test`
    passed, including Next.js and TypeScript.
  - `docker compose build --no-cache frontend` passed, including the
    production frontend build.
  - Bundled Node syntax check for `scripts/qa/rich-input-suite.cjs` passed.
- Fresh runtime evidence:
  - Production frontend and Nginx were recreated from the rebuilt image with
    `docker compose up -d --no-build --force-recreate frontend nginx`.
  - `GET http://localhost/api/v1/health` returned `{"status":"ok"}`.
- Final Windows Chrome rich-input QA:
  - Command:
    `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite rich-input -TimeoutMs 120000`
  - Report:
    `.gstack/qa-reports/local/rich-input-2026-06-14T16-29-55-332Z/report.json`.
  - Result: `ok: true`.
  - Passed steps: auth login, mock provider default, `Ctrl+N` ignored inside
    input, `Ctrl+N` new conversation, `Ctrl+K` ignored inside input, `Ctrl+K`
    command palette, command-palette new conversation, keyboard `@tool`
    selection, file picker upload, drag/drop upload, chat with attachments,
    backend injected upload content, markdown code fold, markdown code copy,
    real long-conversation virtual window, and cleanup conversations.
  - Browser signals: `consoleErrors: []`, `pageErrors: []`,
    `requestFailures: []`, `ignoredRequestFailures: []`, and
    `responses429: []`.
- Test-data cleanup:
  - PostgreSQL residual checks returned `providers_w7=0`,
    `conversations_w7=0`, and `artifacts_w7=0`.
  - `/data/artifacts` contained zero files matching `*w7-rich*` or
    `*-drag.txt`.
- Diff and review closure:
  - Scoped `git diff --check` over W7 backend/frontend/QA files exited `0`
    with CRLF warnings only.
  - Sub-agent Gibbs returned `REVIEW: PASS` with no Critical or Important
    findings; its one Minor ARIA note was fixed.
  - Sub-agent Euler re-reviewed the ARIA fix and returned `REVIEW: PASS` with
    no Critical, Important, or Minor findings remaining for W7 closure.
- Scope restraint:
  W7 changed frontend behavior only to add the required rich-input,
  accessibility, upload, shortcut, markdown/code, and virtual-scroll behavior.
  It did not redesign global style, colors, spacing, sidebar/chat layout, or the
  established dark visual baseline.
- W7 stop condition:
  the rich input and keyboard requirements in the original P6/frontend spec are
  fully browser-verified, and no W7 tail item remains.
