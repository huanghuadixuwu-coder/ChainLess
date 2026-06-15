# Chainless V1 Complete Spec Execution Plan

**Status**: Engineering-review locked; ready for execution  
**Type**: Final V1 Spec Completion Plan  
**Created**: 2026-06-05  
**Approved Spec**: `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`

## Runtime Amendment

As of 2026-06-14, the old remote server is permanently retired. Execute this
plan against local Docker Desktop only, with Windows used only for browser
automation. Any historical command that references `118.196.142.31`,
`/home/dige/chainless`, or a remote Docker host must be translated to the local
checkout and `http://localhost` before use.

Public liveness is `/api/v1/health`. Detailed `/api/v1/system/health` and
`/api/v1/system/metrics` are admin-only endpoints and require an admin bearer
token in probes.

## Goal

Complete every V1 must-ship requirement in the approved reconciliation spec in
one controlled execution pass. Preserve the already-verified runtime and
frontend visual language while closing API contracts, canonical SSE, dynamic
sub-agents, platform configuration UI, real diff/artifact flows, proactive
safety, multi-tenant isolation, integrated Nginx, and final production QA.

No workstream may finish with a tail item. New issues discovered inside a
workstream must be recorded, fixed, and reverified before that workstream closes.

## Architecture

The supported V1 production topology after this plan:

```text
Client
  |
  v
chainless-nginx :80/:443
  |-- /api/v1/* ----------------------> chainless-backend :8000
  |-- /docs, /openapi.json -----------> chainless-backend :8000
  `-- /* -----------------------------> chainless-frontend :3000

chainless-backend
  |-- PostgreSQL + pgvector
  |-- Redis
  |-- sandbox-proxy -> sandbox containers
  |-- canonical SSE contract
  `-- agent / tool / memory owners

chainless-worker
  `-- proactive scheduling and delivery
```

Owner boundaries introduced by this plan:

- API errors: `backend/app/api/contracts.py`
- Pagination: `backend/app/api/pagination.py`
- SSE formatting and canonical event names: `backend/app/api/sse.py`
- Dynamic sub-agent runtime: `backend/app/core/agent/subagents.py`
- Diff/artifact contract: `backend/app/core/artifacts/`
- Audit contract and persistence: `backend/app/core/audit/`
- Code-as-Action sub-agent bridge: backend-owned, run-scoped capability endpoint
- Frontend platform configuration state: `frontend/src/stores/platform-store.ts`
- Settings route and sections: `frontend/src/app/settings/`,
  `frontend/src/components/settings/`
- Browser QA suites: a thin `scripts/windows-browser-qa.cjs` launcher plus
  mandatory suite/client/cleanup modules under `scripts/qa/`
- Integrated gateway: `nginx/nginx.conf`, `nginx/conf.d/`, `nginx/certs/`
- Destructive/integration test isolation: dedicated test database and Compose
  test profile; never the live runtime database

## Tech Stack

- Backend: FastAPI, SQLAlchemy async, Redis, ARQ, pgvector
- Frontend: Next.js, React, Zustand, current Tailwind/zinc visual system
- Agent runtime: ReAct, Code-as-Action, Docker sandbox, MCP
- Deployment: Docker Compose plus compose-managed Nginx
- Verification: local Docker runtime and local Windows Playwright browser QA

## Baseline / Authority Refs

- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-02-chainless-implementation.md`
- `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`
- `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`
- `PROBLEM_TODO_LIST.md`
- `docs/remote-windows-runtime-notes.md`
- `AGENTS.md`

## Compatibility Boundary

- Do not change the established frontend style, spacing language, scroll
  behavior, or interaction feel.
- Preserve verified login, conversation CRUD, SSE chat, tools, confirmation,
  memory, scheduler, Feishu-compatible delivery, health, metrics, backup, and
  Windows QA behavior.
- Local Docker Desktop is the runtime source of truth. Local Windows is the
  browser QA and control plane only.
- Canonical SSE event names become the public contract. Existing internal event
  names may survive only behind an adapter with tests and a retirement note.
- Compose-managed Nginx becomes the supported production entrypoint. Database,
  Redis, sandbox proxy, backend, and frontend ports are internal-only in the
  production profile; direct ports may be published only by an explicit debug
  profile bound to localhost.
- No live tenant or user data deletion is authorized. QA cleanup may delete
  only records created by that QA run using captured IDs or test prefixes.
- V1 non-goals remain: OpenAPI Bridge, Skill Precipitation, MinIO, LDAP/SAML,
  billing, mobile app, and channels beyond Feishu.

## Verification

Every workstream requires all applicable evidence:

- targeted automated tests
- local Docker build/restart and health check
- local API/eval probe
- Windows browser QA for user-facing behavior
- test data cleanup confirmation
- `PROBLEM_TODO_LIST.md` update
- gap matrix update
- exact evidence paths or command output recorded in this plan

Final completion requires:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost `
  -Browser chrome -Headless -Suite spec-complete -TimeoutMs 120000
```

and local Docker:

```powershell
cd E:\Chainless
docker-compose up -d --build
docker-compose ps
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
docker-compose exec -T backend python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0
docker-compose exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
curl.exe -fsS http://127.0.0.1/api/v1/health
```

## Plan Basis

### Facts

- Core runtime and Workstreams 5-10 have strong live evidence.
- The gap matrix is stale for several already-verified items.
- `backend/app/api/v1/conversations.py` is approximately 935 lines and owns too
  many SSE/confirmation/persistence concerns.
- `frontend/src/stores/chat-store.ts` is approximately 752 lines and must not
  become the settings/dashboard store.
- No structured backend test suite currently exists under `backend/tests/`
  outside eval fixtures; one standalone root-level gateway test exists.
- No `nginx/` owner exists.
- No frontend routes exist beyond `/`, `/login`, and `/chat`.
- `code_executor.py` declares sub-agent limits but does not implement
  `spawn_sub_agent`.
- Diff is an empty placeholder.

### Assumptions

- Existing API implementations are the starting point and should be repaired,
  not replaced wholesale.
- The current default tenant/admin seed remains supported.
- HTTP port 80 is the default production profile. TLS is a separate opt-in
  Compose profile/config that is never loaded when certificate files are
  absent.
- Real Feishu group receipt remains credential-dependent.
- Artifact metadata is durable and tenant/conversation/run scoped. Bounded
  content and diffs use a managed artifact volume with retention and quota.
- Passive skill metadata and trigger matching ship in V1; skill precipitation
  remains V2.

### Assigned Discovery Questions

- Whether every current route already enforces tenant isolation.
- Which current provider/agent/channel paths still use in-memory state and must
  be migrated to tenant-scoped persistence. Owner: Workstream 2.
- Which current sandbox-proxy security settings fail the original
  seccomp/capability/read-only/no-new-privileges/network claims. Owner:
  Workstream 10.

These questions have fixed owners and must be fully answered and repaired before
their assigned workstream closes.

## Architecture Integrity Lens

- Invariant: one operable platform, not API-only subsystems.
- Canonical owner: backend route owners define contracts; frontend settings
  consumes them; chat store owns only chat execution state.
- Responsibility overlap risk: `conversations.py`, `chat-store.ts`, and the
  current QA script are already pressure points.
- Higher-level simplification: extract contract/runtime owners before adding
  features.
- Retirement: stale event names, stale matrix states, direct-port production
  claim, and placeholder-only diff must be retired.
- Verdict: proceed with owner extraction before feature expansion.

## Engineering Review Lock-In

The `/plan-eng-review` pass found that the original ordering would add and test
new browser features against direct port `3000`, then change the supported
network topology near the end. It also left destructive tests, sub-agent
bridging, artifact durability, and production security as implementation-time
choices. Those paths would create avoidable rework or hidden tail items.

The following decisions are locked before execution:

1. Mandatory execution order is `W1 -> W2 -> W3 -> W10 -> W4 -> W5 -> W6 ->
   W7 -> W8 -> W9 -> W11`. Nginx and production network/security boundaries
   ship before browser-heavy feature expansion.
2. The frontend API base is the same-origin origin only, for example
   `window.location.origin`; callers continue to provide `/api/v1/...` paths.
   Never configure the base itself as `/api/v1`.
3. Code-as-Action never receives backend, database, Redis, Docker, or LLM
   credentials. `spawn_sub_agent` uses a backend-owned, short-lived,
   run/tenant-scoped capability with an allowlisted operation and no general
   backend access.
4. Sub-agent artifacts live under a per-run path and are removed by a verified
   lifecycle owner. A shared immortal `/workspace/_sub_results` directory is
   not an accepted production design.
5. Artifact metadata is persisted; artifact content/diffs are bounded by size,
   tenant quota, retention, and cleanup policy.
6. Destructive, restore, and multi-tenant tests run only against an isolated
   derived test database/environment.
7. Original approved design/implementation documents remain historical
   evidence. They may receive a superseded/amended authority header and links,
   but must not be rewritten to erase prior decisions.
8. Production closure includes audit logs, auto-migration/idempotent seed,
   dark-mode toggle with the current dark style as default, passive skill
   trigger matching, sandbox negative security tests, a real isolated restore
   drill, and the original HackerNews Code-as-Action `<5s` performance gate.
9. Provider keys and channel secrets are write-only/masked at API and UI
   boundaries. MCP registration/testing and other administrative actions are
   admin-only and audited.
10. Accepted implementation-version drift, including current Next.js/React and
    PostgreSQL versions, is recorded explicitly; no unplanned downgrade is
    permitted.

## Test and Evidence Architecture

```text
Pinned source and test images
  |
  +--> Unit/contract tests in backend-test
  |      - deterministic owners, error paths, security negatives
  |
  +--> Isolated integration environment
  |      - distinct DB/Redis/volumes, backend-test-server
  |      - migrations, restore, concurrency, tenant isolation
  |
  +--> Local Docker production-profile runtime
  |      - real Compose networks, Nginx, worker, sandbox-proxy, sandbox
  |      - API/SSE/eval/performance probes
  |
  `--> Local Windows browser against local Nginx
         - user-visible flows, style/scroll regression, cleanup
```

No layer may substitute for another. In-process API tests do not prove Compose
networking; local production-profile probes do not prove cross-tenant negatives; browser QA does
not prove secret redaction or sandbox isolation.

Performance budgets:

- Original HackerNews top-10 Code-as-Action flow: one warmup plus five measured
  runs against a pinned provider/model; every measured run is end-to-end
  `<5000ms` and sandbox/code evidence proves it was not answered from LLM text.
- Internal health, auth, and CRUD probes: p95 `<1000ms` from the local Docker
  network under the three-tenant test load.
- Three-tenant probe: zero unexpected 5xx/timeouts and every operation finishes
  within its configured product timeout.
- Sub-agent call: hard timeout `15s`, cancellation leaves no orphan.
- Artifact list/diff for allowed-size text artifacts: p95 `<1000ms`.

## Plan Pressure Test

- Owner / contract / retirement: public API, SSE, deployment, and UI owners are
  changing; retirement is explicit in Workstreams 1, 2, 3, 6, and 10.
- Architecture integrity / higher-level path: separate platform configuration
  from chat execution and extract SSE/sub-agent/artifact owners.
- Verification scope: broad, requiring backend tests, local Docker, browser
  QA, eval, and isolation probes.
- Task executability: each workstream is independently closable in dependency
  order.
- Pressure result: proceed.

## Plan-Time Complexity Check

- High-pressure files:
  - `backend/app/api/v1/conversations.py`
  - `frontend/src/stores/chat-store.ts`
  - `scripts/windows-browser-qa.cjs`
- Owner fit:
  - API routes remain route owners but delegate contract formatting.
  - chat store remains chat-only.
  - QA launcher delegates suites/helpers.
- Better file boundary:
  add `contracts.py`, `sse.py`, `subagents.py`, `artifacts/`,
  `platform-store.ts`, settings components, and QA helper modules.
- Recommendation:
  extract owners first; do not add more branches to the three pressure files.

## Execution Rules

1. Workstreams run in the mandatory order locked in Engineering Review, not
   numeric heading order.
2. Only one workstream may be in progress.
3. A workstream closes only when every checkbox and verification gate passes.
4. Any discovered issue is appended to `PROBLEM_TODO_LIST.md`, fixed in the same
   workstream, and marked resolved with evidence.
5. Browser/API QA must clean up its own records in `finally`.
6. Do not create persistent subagents in the Codex UI; runtime sub-agents are
   application behavior only.
7. Before Docker/browser commands, read `docs/remote-windows-runtime-notes.md`;
   its historical remote-server notes are not active runtime instructions.
8. Do not modify frontend styling except the minimum classes needed to place
   spec-required controls inside the existing visual system.
9. High-risk workstreams must record the pre-change rollback point and prove
   rollback instructions before retiring compatibility behavior.
10. Do not run destructive, restore, or multi-tenant tests against live data.
11. Every new or repaired module must include happy-path, error-path, and
    edge-case automated tests before its workstream can close.

---

## Workstream 1: Authority and Current-Truth Sync

### Goal

Make the approved reconciliation and current runtime truth the only execution
authority before changing contracts.

### Files

- Modify: `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`
- Modify: `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`
- Modify: `PROBLEM_TODO_LIST.md`
- Modify: `docs/operations-production.md`
- Modify authority header/link only:
  `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- Modify authority header/link only:
  `docs/aegis/plans/2026-06-02-chainless-implementation.md`

### Tasks

- [x] Mark verified Workstream 8-10 matrix rows as
  `implemented-and-verified`, citing evidence.
- [x] Mark Nginx as `missing / ship`, dynamic sub-agent as `missing / ship`,
  dashboard/settings and real diff as `missing / ship`.
- [x] Remove MinIO and Skill Precipitation from V1 must-ship topology/API claims
  while preserving their V2 status.
- [x] Preserve passive skill metadata/trigger matching as a V1 requirement and
  map it to Workstream 5.
- [x] Record Compose-managed Nginx as the approved production topology.
- [x] Record accepted Next.js/React/PostgreSQL version drift without downgrading
  the working stack.
- [x] Mark the original design and implementation documents as historical
  authority amended by the reconciliation; do not rewrite their history.
- [x] Add this execution plan as the only active remaining-work tracker.
- [x] Scan for floating unresolved claims outside the matrix and add them.

### Verification

```powershell
$matrix = 'docs\aegis\plans\2026-06-03-spec-runtime-gap-matrix.md'
$historicalChecklist = 'docs\aegis\plans\2026-06-03-spec-gap-closure-checklist.md'
$problemList = 'PROBLEM_TODO_LIST.md'
$originalDocs = @(
  'docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md',
  'docs/aegis/plans/2026-06-02-chainless-implementation.md'
)

if (Select-String -Path $matrix -Pattern '\| (W[0-9]+, W[0-9]+|[0-9]+|[0-9]+, [0-9]+) \|$') {
  throw 'Matrix contains an ambiguous owner.'
}
if (Select-String -Path $matrix -Pattern '\| implemented-and-verified \|' |
    Where-Object { $_.Line -notmatch '\| closed baseline \|$' }) {
  throw 'A verified matrix row is not closed baseline.'
}
if (Select-String -Path $problemList -Pattern '^- \[ \]') {
  throw 'Problem list contains an unresolved checkbox.'
}
$numstat = git diff --numstat -- $originalDocs
if (($numstat | Where-Object { $_ -notmatch '^7\s+0\s+' }).Count -ne 0 -or
    $numstat.Count -ne 2) {
  throw 'Historical authority documents changed beyond their seven-line notices.'
}
if (Select-String -Path @($matrix, $historicalChecklist) -Pattern '[^\x00-\x7F]' -Encoding utf8) {
  throw 'Authority documents contain malformed or non-ASCII text.'
}
if (Select-String -Path $matrix -Pattern 'missing \| ship \|.*(Workstream 8|Workstream 9|Workstream 10)') {
  throw 'Matrix contains stale verified-baseline state.'
}
git diff --check -- docs/aegis PROBLEM_TODO_LIST.md docs/operations-production.md
if ($LASTEXITCODE -ne 0) {
  throw 'W1 authority-document diff check failed.'
}
```

Expected:

- No stale `missing` state remains for already-verified W8-W10 runtime items.
- Every remaining item maps to one later workstream in this plan.

### Stop Condition

No remaining V1 requirement floats outside the approved reconciliation, matrix,
or this plan.

---

## Workstream 2: Canonical API Contracts and Automated Contract Tests

### Goal

Make error envelopes, pagination, tenant scoping, and OpenAPI route truth
consistent across every V1 API family.

### Files

- Create: `backend/app/api/contracts.py`
- Create: `backend/tests/test_api_contracts.py`
- Create: `backend/tests/test_tenant_isolation.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/requirements.txt`
- Create: `backend/requirements-test.txt`
- Create: `docker-compose.test.yml`
- Create: `backend/scripts/spec_contract_probe.py`
- Create: `scripts/qa/api-client.cjs`
- Create: `scripts/qa/cleanup-registry.cjs`
- Create: `scripts/qa/suite-registry.cjs`
- Modify: `backend/Dockerfile`
- Modify: `frontend/Dockerfile`
- W9 uses standalone Docker QA entrypoint `scripts/qa/multitenant.cjs`.
  `scripts/windows-browser-qa.cjs` is intentionally not modified because W9
  has no browser interaction surface and the browser launcher is a separate
  high-pressure owner.
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/pagination.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/app/api/v1/agents.py`
- Modify: `backend/app/api/v1/channels.py`
- Modify: `backend/app/api/v1/conversations.py`
- Modify: `backend/app/api/v1/llm_providers.py`
- Modify: `backend/app/api/v1/memories.py`
- Modify: `backend/app/api/v1/proactive.py`
- Modify: `backend/app/api/v1/tools.py`
- Modify: `backend/app/api/v1/system.py`

### Contract

```json
{"error":{"code":"STABLE_CODE","message":"Human-readable message","detail":null}}
```

```json
{"items":[],"total":0,"limit":20,"offset":0,"next":null}
```

### Tasks

- [x] Add contract helpers for error envelope creation and normalized exception
  handling.
- [x] Move backend dependencies out of the inline Dockerfile install command
  into reproducible pinned production/test requirement owners.
- [x] Add `pytest`, `pytest-asyncio`, and the chosen FastAPI test client only to
  the backend test image/requirements, then prove tests execute there.
- [x] Add isolated backend-test runner, backend-test-server, and frontend-test
  image targets/services so verification tooling is not installed into or run
  inside live containers.
- [x] Add a dedicated test database/service and fixtures that cannot resolve to
  the live database URL; fail closed if isolation variables are absent.
- [x] Split the browser QA launcher now into suite, API-client, and cleanup
  owners before adding more suites.
- [x] Add global handlers for validation errors, HTTP errors, and unexpected
  errors without leaking secrets.
- [x] Convert every list endpoint to the canonical pagination helper.
- [x] Confirm every resource read/update/delete filters by authenticated tenant.
- [x] Remove or hide OpenAPI routes that are not implemented.
- [x] Add contract tests for success, 401, 404, 422, and unexpected error paths.
- [x] Verify and repair the complete auth lifecycle: login, expiration, refresh,
  role enforcement, disabled users, and stable auth error envelopes.
- [x] Add tenant-isolation tests for agents, conversations, memories, tools,
  providers, channels, and proactive tasks.
- [x] Identify and migrate every in-memory V1 resource path to tenant-scoped
  persistence or explicitly prove its intended ephemeral lifecycle.
- [x] Add a local-Docker contract probe that lists each route family and asserts
  envelope shapes.

### Repair Track

- Root cause: envelope and pagination logic is distributed across route files.
- Canonical owner: `backend/app/api/contracts.py` and
  `backend/app/api/pagination.py`.
- Minimal stable repair: route files provide domain error codes; shared owners
  format responses.

### Retirement Track

- Retire route-local inconsistent response envelopes.
- Retire list responses that return a bare list or partial pagination fields.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py
docker-compose exec -T backend python scripts/spec_contract_probe.py --base-url http://nginx
curl -fsS http://127.0.0.1/openapi.json > openapi.json
```

Expected:

- All tests pass.
- Tests prove their database is not the live runtime database.
- Probe reports every V1 route family passing.
- Cross-tenant reads fail with unified 404/authorization envelope.

### Stop Condition

No V1 API route has an untested error envelope, pagination shape, tenant
boundary, or ambiguous persistence owner, and the reusable QA/test isolation
foundation is proven.

---

## Workstream 3: Canonical SSE Protocol and Conversation Owner Extraction

### Goal

Implement the design-spec SSE contract and reduce `conversations.py` ownership
pressure without regressing existing chat behavior.

### Files

- Create: `backend/app/api/sse.py`
- Create: `backend/app/services/conversation_stream_service.py`
- Create: `backend/tests/test_sse_contract.py`
- Create: `backend/scripts/sse_contract_probe.py`
- Modify: `backend/app/api/v1/conversations.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/stores/chat-store.ts`

### Canonical Events

- `text`
- `tool_call`
- `tool_result`
- `sandbox`
- `sandbox_output`
- `confirmation_required`
- `done`
- `error`
- `heartbeat` may remain transport-only.

### Tasks

- [x] Add typed SSE formatting helpers and event payload definitions.
- [x] Extract stream orchestration/persistence from `conversations.py` into the
  conversation stream service.
- [x] Map internal `tool_call_start` and `tool_error` to canonical public events.
- [x] Emit `sandbox` and `sandbox_output` during Code-as-Action execution.
- [x] Ensure SSE `error` uses the unified error envelope.
- [x] Update frontend stream parser to canonical events.
- [x] Preserve heartbeat, reconnect, and last-event/resume behavior; add tests
  for dropped connections and duplicate-event avoidance.
- [x] Keep compatibility aliases only if required by a verified current caller.
- [x] Add API probe and automated tests for event order and JSON shape.
- [x] Re-run existing Workstream 10 browser suite.

### Retirement Track

- Old public event names are contract-carrying code.
- Delete them from the public stream after frontend and probes consume canonical
  events; retain only internal event names behind the adapter.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_sse_contract.py
docker-compose exec -T backend python scripts/sse_contract_probe.py --base-url http://127.0.0.1:8000
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost -Browser chrome -Headless `
  -Suite workstream10 -TimeoutMs 60000
```

This browser run uses the supported compose-managed Nginx entrypoint.

Expected:

- Canonical event probe passes.
- Existing chat/tool/confirmation browser regression remains `ok: true`.
- Forced connection drop resumes safely without duplicate persisted messages or
  tool execution.

### Stop Condition

The frontend/backend stream contract matches the reconciled spec, and no
public consumer depends on legacy event names.

---

## Workstream 4: Dynamic Runtime Sub-Agents

### Goal

Implement genuine application-level `spawn_sub_agent` inside Code-as-Action.

### Files

- Create: `backend/app/core/agent/subagents.py`
- Create: `backend/tests/test_subagents.py`
- Create: `backend/tests/test_subagent_security.py`
- Create: `backend/tests/eval/tasks/spec_complete.json`
- Modify: `sandbox-proxy/main.py`
- Modify: `backend/app/core/agent/code_executor.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `backend/app/core/sandbox/manager.py`
- Modify: `backend/app/config.py`
- Modify: `backend/scripts/run-eval.py`

### Runtime Contract

```python
async def spawn_sub_agent(
    prompt: str,
    context: str = "",
    *,
    parent_run_id: str,
    depth: int,
) -> SubAgentResult:
    ...
```

Constraints:

- max depth 1
- max parallelism 5
- timeout 15 seconds
- shared parent budget
- isolated sandbox/runtime context
- host-mediated per-run Unix control socket mounted at
  `/run/chainless/subagent.sock`
- short-lived tenant/run-scoped capability accepted only by that socket
- result files under a per-run path such as
  `/workspace/runs/{run_id}/sub_results/`

### Tasks

- [x] Define `SubAgentResult`, budget accounting, timeout, and concurrency owner.
- [x] Expose an allowlisted `spawn_sub_agent` RPC through the sandbox-proxy
  per-run control socket; do not enable sandbox network access.
- [x] Prove the capability cannot call arbitrary backend routes, cross tenants,
  outlive the parent run, or reveal backend/LLM/database/Docker credentials.
- [x] Reject depth greater than 1 and parallelism greater than 5.
- [x] Write each result/timeout/error to the per-run result path and remove it
  through the run/artifact lifecycle owner.
- [x] Stream sub-agent lifecycle through canonical `sandbox`/`sandbox_output`
  events.
- [x] Apply cancellation when the parent run is cancelled or disconnected.
- [x] Add deterministic unit tests for parallel success, depth rejection,
  timeout, partial result, and shared budget exhaustion.
- [x] Add negative security tests for expired/foreign capabilities, arbitrary
  RPC attempts, network access, secret access, and orphaned runs.
- [x] Add eval task requiring at least two parallel sub-agent calls.
- [x] Add live local-Docker proof that backend logs/artifacts show real sub-agent runs.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_subagents.py tests/test_subagent_security.py
docker-compose exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
docker-compose exec -T backend find /workspace/runs -maxdepth 4 -type f -print
```

Expected:

- Real parallel sub-agent execution is proven.
- Timeout and partial-result tests pass.
- Sandbox remains network-isolated and receives no platform secret.
- Parent cancellation leaves no active sub-agent or stale control capability.
- No persistent Codex UI subagents are created by this runtime feature.

### Stop Condition

AD14 and design spec Section 4.3 are implemented and verified, not simulated by
LLM text.

---

## Workstream 5: Platform Settings and Administration Surface

### Goal

Make all configurable platform capabilities operable from the Web UI while
preserving the current frontend style.

### Files

- Create: `frontend/src/app/settings/page.tsx`
- Create: `frontend/src/stores/platform-store.ts`
- Create: `frontend/src/components/settings/settings-shell.tsx`
- Create: `frontend/src/components/settings/providers-section.tsx`
- Create: `frontend/src/components/settings/agents-section.tsx`
- Create: `frontend/src/components/settings/tools-section.tsx`
- Create: `frontend/src/components/settings/memories-section.tsx`
- Create: `frontend/src/components/settings/channels-section.tsx`
- Create: `frontend/src/components/settings/proactive-section.tsx`
- Create: `frontend/src/components/settings/skills-section.tsx`
- Create: `frontend/src/components/settings/system-section.tsx`
- Create: `frontend/src/components/settings/shared-state.tsx`
- Create: `frontend/src/components/chat/context-banner.tsx`
- Create: `backend/app/api/v1/skills.py`
- Create: `backend/app/api/v1/eval.py`
- Create: `backend/app/core/secrets.py`
- Create: `backend/app/models/skill.py`
- Create: `backend/alembic/versions/<revision>_add_skills.py`
- Create: `backend/tests/test_admin_authorization.py`
- Create: `backend/tests/test_secret_redaction.py`
- Create: `backend/tests/test_skill_trigger_matching.py`
- Modify: `frontend/src/components/layout/sidebar.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/core/agent/prompt_builder.py`
- Modify: affected backend API routes only where UI-required CRUD/test contracts
  are incomplete

### Tasks

- [x] Add one Settings entry to the existing left sidebar without redesigning
  the sidebar.
- [x] Build a settings shell using existing zinc classes/components.
- [x] Implement provider list/create/update/test/default selection.
- [x] Prove a newly selected default provider is used by a subsequent real chat.
- [x] Implement agent list/create/update/delete and active-agent selection.
- [x] Implement builtin/MCP tool list/register/test/activate/risk display.
- [x] Make MCP registration/testing, provider configuration, risk overrides,
  eval execution, and system administration admin-only and audited.
- [x] Implement memory list/create/update/search/merge/delete.
- [x] Implement passive skill metadata CRUD/list and trigger matching; do not
  implement V2 skill precipitation.
- [x] Implement Feishu channel configure/test.
- [x] Implement proactive task list/create/delete/run-history view.
- [x] Implement system health, metrics summary, and eval status/run action.
- [x] Add explicit backend contracts for every UI action; no settings control
  may depend on an undocumented or missing route.
- [x] Treat provider keys and channel secrets as write-only: return only masked
  metadata, encrypt them at rest with an operator-managed key, and add no-leak
  tests for persistence, API errors, logs, metrics, and UI.
- [x] Add the spec-required dark-mode toggle with current dark mode as the
  default and without redesigning either theme.
- [x] Add the context banner for active injected instruction/memory summary
  using the existing chat visual language and without changing chat layout,
  widths, or scroll behavior.
- [x] Add loading, empty, success, and error states for every section.
- [x] Keep platform configuration state out of `chat-store.ts`.
- [x] Add browser QA suite for every settings section and cleanup all test data.

### No-Style-Drift Gate

- Reuse current typography, zinc colors, borders, button/input primitives, and
  spacing scale.
- Do not change chat/sidebar widths, scroll behavior, or global visual theme.
- Before/after screenshots must show chat layout unchanged.

### Verification

```bash
docker build -t chainless_frontend:latest ./frontend
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_admin_authorization.py tests/test_secret_redaction.py tests/test_skill_trigger_matching.py
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost -Browser chrome -Headless `
  -Suite settings -TimeoutMs 90000
```

Expected:

- Every section is browser-operable.
- Non-admin users cannot access administrative actions.
- No raw provider/channel secret is returned or rendered.
- Provider switching and passive skill trigger matching are proven at runtime.
- QA-created provider/agent/tool/memory/channel/task records are removed.
- No style/scroll regression is visible.

### Stop Condition

No must-ship platform feature remains API-only.

---

## Workstream 6: Real Artifacts, Files, and Diff Flow

### Goal

Replace the placeholder Diff tab and argument-only Files tab with real
artifact-producing behavior.

### Files

- Create: `backend/app/core/artifacts/__init__.py`
- Create: `backend/app/core/artifacts/service.py`
- Create: `backend/app/api/v1/artifacts.py`
- Create: `backend/app/models/artifact.py`
- Create: `backend/alembic/versions/<revision>_add_artifacts.py`
- Create: `backend/tests/test_artifacts.py`
- Create: `backend/tests/test_preview_security.py`
- Create: `frontend/src/stores/artifact-store.ts`
- Create: `frontend/src/components/chat/diff-view.tsx`
- Create: `frontend/src/components/chat/file-artifact-list.tsx`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/core/tools/builtin/file_ops.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `frontend/src/components/chat/preview-panel.tsx`
- Modify: `frontend/src/app/chat/page.tsx`
- Modify: `frontend/src/lib/api.ts`

### Tasks

- [x] Define artifact metadata contract for created/modified files and diffs.
- [x] Persist tenant/conversation/run-scoped artifact metadata and store bounded
  content/diffs in the managed artifact volume.
- [x] Define and enforce per-file size limit, per-tenant quota, retention,
  deletion, and orphan cleanup policy.
- [x] Capture before/after content for file writes inside `/workspace`.
- [x] Generate unified diff for modified text files with size limits.
- [x] Add tenant/conversation-scoped artifact list/get endpoints.
- [x] Emit artifact references through canonical tool/sandbox events.
- [x] Render real files in Files tab.
- [x] Render real unified diff in Diff tab using existing style.
- [x] Complete and verify safe iframe/file preview, URL/content allowlisting,
  terminal ANSI rendering, and syntax-highlighted code preview without changing
  the established right-panel visual language.
- [x] Handle binary, oversized, missing, and deleted artifact states.
- [x] Prove artifacts survive page reload and never cross tenant boundaries.
- [x] Add tests and browser scenario that changes a file and proves real diff.
- [x] Clean QA artifacts after verification.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_artifacts.py tests/test_preview_security.py
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost -Browser chrome -Headless `
  -Suite artifacts -TimeoutMs 90000
```

Expected:

- Files tab shows real artifact entries.
- Diff tab shows actual before/after changes, not placeholder text.
- Reload preserves the artifact list/diff, and retention cleanup removes only
  expired artifacts.

### Stop Condition

Preview, Terminal, Files, and Diff all have real verified behavior.

---

## Workstream 7: Rich Input and Keyboard Shortcuts

### Goal

Complete the spec-required input workflow without changing the established
composer style.

### Files

- Create: `frontend/src/components/chat/command-palette.tsx`
- Create: `frontend/src/components/chat/tool-picker.tsx`
- Create: `frontend/src/components/chat/file-attachment.tsx`
- Create: `backend/tests/test_file_upload_security.py`
- Create: `backend/app/api/v1/uploads.py`
- Modify: `frontend/src/components/chat/input-area.tsx`
- Modify: `frontend/src/app/chat/page.tsx`
- Modify: `frontend/src/lib/api.ts`

### Tasks

- [x] Add `Ctrl+N` new conversation.
- [x] Add `Ctrl+K` command palette.
- [x] Preserve `Ctrl+Enter` send.
- [x] Add `@tool` picker backed by live tools API.
- [x] Add `+file` attachment backed by the real artifact/upload contract.
- [x] Enforce upload size/type/path validation, tenant/conversation ownership,
  filename normalization, quota, and malware/content-policy hook boundary.
- [x] Ensure shortcuts do not fire while modal/input context makes them unsafe.
- [x] Add accessible labels and keyboard-only flows.
- [x] Add browser QA for shortcuts, file attachment, and tool selection.
- [x] Verify Markdown rendering, syntax-highlighted code blocks, copy/fold
  controls, long-conversation virtual scrolling, and drag/drop upload while
  preserving the established visual style and scroll behavior.
- [x] Add negative tests for traversal, oversized/binary-disallowed content,
  foreign artifact IDs, and unsafe filenames.

### Verification

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost -Browser chrome -Headless `
  -Suite rich-input -TimeoutMs 120000
```

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_file_upload_security.py
```

Expected:

- All shortcuts and input affordances work through the real browser.
- Composer styling and scrolling remain unchanged.

### Stop Condition

The rich input and keyboard requirements in the original P6/frontend spec are
fully browser-verified.

---

## Workstream 8: Proactive Safety, Feishu, Eval, and Hallucination Guard

### Goal

Close remaining proactive safety and evaluation requirements beyond the already
verified scheduler runtime.

### Files

- Create: `backend/tests/test_proactive_authorization.py`
- Create: `backend/tests/test_eval_contract.py`
- Create: `backend/tests/test_observability_contract.py`
- Create: `backend/tests/test_agent_runtime_limits.py`
- Create: `backend/tests/test_instruction_reload.py`
- Create: `backend/tests/test_proactive_event_triggers.py`
- Create: `backend/tests/test_memory_source_contract.py`
- Create: `backend/tests/test_mcp_transports.py`
- Create: `backend/tests/test_tool_cancellation.py`
- Create: `backend/tests/test_delayed_proactive_tasks.py`
- Create: `.github/workflows/eval.yml`
- Modify: `backend/app/api/v1/proactive.py`
- Modify: `backend/app/core/proactive/scheduler.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `backend/app/core/channel/feishu.py`
- Modify: `backend/scripts/run-eval.py`
- Modify: `backend/tests/eval/tasks/basic.json`
- Modify: `backend/tests/eval/tasks/spec_complete.json`

### Tasks

- [x] Add pre-authorized tool list to proactive task contract.
- [x] Block and log any proactive tool outside the pre-authorized list.
- [x] Record attempts, delivery status, error, and blocked-tool details.
- [x] Verify retry and deleted/disabled task behavior.
- [x] Expand eval to tools, MCP, sub-agent, confirmation, memory citations,
  proactive safety, and canonical SSE.
- [x] Prove the complexity router deterministically selects direct-tool, ReAct,
  and Code-as-Action paths and safely falls back when a selected path fails.
- [x] Enforce and prove the original bounded main-agent token budget and circuit
  breaker, including observable termination instead of runaway loops.
- [x] Prove persistent-memory filesystem source-of-truth and `MEMORY.md` index,
  configurable injection budget, and configurable embedding model/fallback.
- [x] Prove short-term conversation context uses Redis or the documented durable
  equivalent, including tenant scope, expiry/cleanup, and reload behavior.
- [x] Prove layered instruction sources reload safely after file changes without
  requiring a process restart or leaking cross-tenant state.
- [x] Prove MCP idle lifecycle, reconnect after failure, unavailable-server
  behavior, and default `risky` classification.
- [x] Implement and prove MCP stdio and HTTP/SSE transport behavior.
- [x] Register and invoke the original filesystem MCP gate, including
  `mcp__fs__list_directory`, discovery, failure, and cleanup.
- [x] Validate every builtin tool definition against the required OpenAI
  function schema.
- [x] Prove risky-tool retroactive cancellation and destructive rejection-reason
  alternative behavior.
- [x] Implement and verify proactive event-trigger execution with the same
  pre-authorization and audit boundary as cron execution.
- [x] Implement and verify one-shot delayed `execute_at` tasks and cleanup.
- [x] Add a GitHub Actions eval gate using the pinned test environment and prove
  it fails on a deliberately failing threshold.
- [x] Add hallucination/citation checks for factual claims derived from tools,
  memory, and context.
- [x] Prove the original memory gate with at least five memories across
  different types and a real `cosine_distance` query.
- [x] Add metrics/log coverage for sub-agent lifecycle, SSE disconnect/error,
  artifact failures/quota, proactive blocked actions, delivery failures, and
  eval outcomes without leaking prompts or secrets.
- [x] Re-run Feishu-compatible live webhook receiver proof.
- [x] Real Feishu credentials were not supplied; external group receipt proof is
  credential-dependent and the live receiver proof remains the V1 evidence.
- [x] Delete QA proactive tasks and prove no subsequent run.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_proactive_authorization.py tests/test_eval_contract.py tests/test_observability_contract.py tests/test_agent_runtime_limits.py tests/test_instruction_reload.py tests/test_memory_source_contract.py tests/test_mcp_transports.py tests/test_tool_cancellation.py tests/test_proactive_event_triggers.py tests/test_delayed_proactive_tasks.py
docker-compose exec -T backend python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0
docker-compose exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
```

Expected:

- Unauthorized proactive tool is blocked and logged.
- Both eval suites pass.
- Required metrics/log signals exist and contain no tenant data or secrets.
- Test tasks are deleted and do not rerun.

### Stop Condition

Proactive execution is safe, observable, evaluated, and credential-ready.

---

## Workstream 9: Three-Tenant Concurrency and Isolation

### Goal

Prove the original success criterion that three tenants can concurrently use
the platform without errors or data leakage.

### Files

- Create: `backend/tests/test_multitenant_concurrency.py`
- Create: `backend/scripts/multitenant_probe.py`
- Create: `backend/scripts/assert_test_environment.py`
- Modify: affected models/routes/services where isolation defects are found
- Create: `scripts/qa/multitenant.cjs`
- Modify: `scripts/windows-browser-qa.cjs`

### Tasks

- [x] Fail closed unless the probe proves it is connected to the isolated test
  database/environment.
- [x] Create three uniquely prefixed QA tenants only in that isolated flow.
- [x] Run at least five concurrent chat/tool/memory/provider/channel/proactive
  operations per tenant with fixed product timeouts and p95 internal
  health/auth/CRUD latency below `1000ms`.
- [x] Attempt cross-tenant reads and mutations for every resource family.
- [x] Verify metrics and errors do not expose sensitive tenant data.
- [x] Fix all discovered isolation issues in the same workstream.
- [x] Destroy only the derived test environment after evidence is captured.

### Data Destruction Guard

Do not create or delete test tenants in the live database. The test environment
must use a distinct database identity and volume and must fail closed if that
identity cannot be proven.

### Verification

```bash
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_multitenant_concurrency.py
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test python scripts/multitenant_probe.py --base-url http://backend-test-server:8000 --tenants 3 --parallel-per-tenant 5
```

Expected:

- Three tenants complete parallel operations.
- Zero unexpected 5xx/timeouts and p95 internal latency is below `1000ms`.
- Every cross-tenant access is denied.
- No QA tenant/data remains in the isolated test environment.

### Stop Condition

Multi-tenant concurrency and isolation are proven across every V1 resource.

Status: complete by fresh local-Docker evidence. Final probe returned
`ok: true`, `check_count: 42`, `p95_ms: 393.4`, `failures: []`, and deleted
its exact derived test data.

---

## Workstream 10: Production Gateway, Network, Sandbox, and Audit Hardening

### Goal

Make integrated Nginx the supported production entrypoint, close public
internal-service ports, and prove the original production, sandbox, migration,
seed, and audit requirements before feature expansion.

### Files

- Create: `nginx/nginx.conf`
- Create: `nginx/conf.d/chainless.conf`
- Create: `nginx/conf.d/chainless-tls.conf`
- Create: `nginx/certs/README.md`
- Create: `nginx/certs/.gitkeep`
- Create: `docker-compose.debug.yml`
- Create: `docker-compose.tls.yml`
- Create: `backend/app/core/audit/service.py`
- Create: `backend/app/models/audit_log.py`
- Create: `backend/app/middleware/audit.py`
- Create: `backend/app/api/v1/audit.py`
- Create: `backend/alembic/versions/<revision>_add_audit_logs.py`
- Create: `backend/tests/test_audit.py`
- Create: `backend/tests/test_sandbox_security.py`
- Create: `backend/tests/test_sandbox_pool_lifecycle.py`
- Create: `backend/tests/test_sandbox_network_policy.py`
- Create: `backend/tests/test_production_config.py`
- Create: `backend/scripts/clean_start_probe.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `frontend/src/lib/api.ts`
- Modify: `sandbox-proxy/main.py`
- Modify: `backend/app/core/sandbox/manager.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/scripts/seed.py`
- Modify: `docs/operations-production.md`
- Modify: `docs/remote-windows-runtime-notes.md`
- Modify: `Makefile`

### Required Routing

- `/` and frontend assets -> `frontend:3000`
- `/api/v1/*` -> `backend:8000`
- `/docs`, `/openapi.json` -> `backend:8000`
- SSE proxy buffering disabled
- forwarded headers set
- HTTP works by default
- TLS config is loaded only by the opt-in TLS Compose override/profile
- production publishes only Nginx ports; internal services use private networks

### Tasks

- [x] Add Nginx service with canonical name `chainless-nginx`.
- [x] Route frontend and API through one origin.
- [x] Disable buffering and extend timeouts for SSE.
- [x] Update frontend API base to `window.location.origin`/configured origin;
  keep `/api/v1` in caller paths and prevent doubled `/api/v1/api/v1`.
- [x] Remove production host publication for DB, Redis, sandbox-proxy, backend,
  and frontend; publish localhost-only direct ports through the explicit debug
  override.
- [x] Split internal networks so only required service-to-service paths exist.
- [x] Make production startup fail closed for default/empty `SECRET_KEY`,
  database password, proxy token, and secret-encryption key.
- [x] Set same-origin CORS and production security headers without breaking SSE
  or the established frontend behavior.
- [x] Add Nginx health check.
- [x] Make TLS a separate opt-in override that validates only when certificate
  files are present; prove HTTP startup does not reference missing certs.
- [x] Apply and verify sandbox limits: network disabled, read-only rootfs,
  no-new-privileges, dropped capabilities, seccomp, CPU/memory/PID/time limits,
  scoped workspace mount, and cleanup on timeout/cancel.
- [x] Prove sandbox pool warmup, checkout/return, unhealthy replacement,
  timeout/cancel cleanup, bounded size, and leak-free repeated execution.
- [x] Implement and prove the configurable sandbox network whitelist and
  AppArmor policy boundary without weakening the default network-none profile.
- [x] Keep Docker socket access inside sandbox-proxy only; prove sandbox and
  backend cannot access it and sandbox-proxy is not publicly reachable.
- [x] Persist and expose admin-readable tenant-scoped audit records for
  POST/PUT/PATCH/DELETE, login/security decisions, MCP/provider administration,
  destructive confirmations, and proactive actions without secret bodies.
- [x] Make startup migrations and idempotent seed produce a login-ready system
  on a clean derived environment without manual commands.
- [x] Verify `docker-compose up -d --build` from the local checkout.
- [x] Verify canonical containers and no anonymous exited replacements.
- [x] Run browser QA through `http://localhost`, not direct service ports
  `3000/8000`.

### Retirement Track

- Retire direct ports as the supported production URL.
- Retain direct ports only in the localhost-bound debug override.
- Retire unaudited administrative mutations and manual-only migration/seed.

### Verification

```bash
docker-compose up -d --build
docker-compose ps
docker-compose config
docker-compose -f docker-compose.yml -f docker-compose.debug.yml config
docker-compose -f docker-compose.yml -f docker-compose.tls.yml config
curl -fsS http://127.0.0.1/api/v1/system/health
curl -fsS http://127.0.0.1/api/v1/system/metrics
curl -fsS http://127.0.0.1/login > /dev/null
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q tests/test_audit.py tests/test_sandbox_security.py tests/test_sandbox_pool_lifecycle.py tests/test_sandbox_network_policy.py tests/test_production_config.py
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test python scripts/clean_start_probe.py
```

Expected:

- Nginx is up and healthy.
- Public application and API work through port 80.
- SSE browser flow works through Nginx.
- Internal services are not reachable from the public host interface.
- HTTP-only startup works without certificates; TLS override validates with
  supplied test certificates.
- Sandbox negative tests and audit tests pass.
- Production defaults/secrets fail-closed tests and security-header tests pass.
- Clean derived startup auto-migrates, seeds once, and supports login.

### Stop Condition

`docker-compose up -d` creates the complete supported V1 production entrypoint
with private internal services, hardened sandbox execution, durable audit, and
automatic migration/idempotent seed.

---

## Workstream 11: Final Spec-Complete QA, Cleanup, and Evidence Bundle

### Goal

Run the entire spec as a release gate and leave no unresolved V1 requirement,
test data, stale authority, or hidden tail item.

### Files

- Create: `backend/scripts/spec_complete_probe.py`
- Create: `backend/scripts/restore_drill.py`
- Create: `backend/scripts/performance_probe.py`
- Create: `docs/aegis/work/2026-06-05-v1-spec-completion/original-gate-ledger.md`
- Create or split: `scripts/qa/spec-complete.cjs`
- Modify: `scripts/windows-browser-qa.cjs`
- Modify: `scripts/windows-browser-qa.ps1`
- Modify: `PROBLEM_TODO_LIST.md`
- Modify: `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`
- Modify: `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`
- Modify: `docs/operations-production.md`
- Modify: approved spec/implementation docs only to reflect verified final truth

### Final Browser Coverage

- public Nginx entrypoint
- auth and token refresh
- conversation CRUD/reload
- chat SSE and error state
- tool cards and risks
- sandbox/code output
- destructive approve/deny/timeout
- dynamic sub-agent proof
- settings providers/agents/tools/memories/channels/proactive/system
- admin/member authorization, secret masking, passive skill trigger, and dark
  mode toggle
- real files/diff artifacts
- rich input and keyboard shortcuts
- cleanup verification

### Final Local-Docker Coverage

- fresh compose build/up
- all service health
- API contract probe
- canonical SSE probe
- builtin/MCP tools
- memory/context
- proactive safety and delivery
- both eval suites
- three-tenant concurrency/isolation
- rate limit
- audit persistence and sensitive-data redaction
- sandbox negative security suite
- clean-start auto-migration/idempotent seed
- backup artifact
- isolated real restore drill
- HackerNews Code-as-Action end-to-end latency `<5s`
- no stale QA tasks/conversations/memories/tools/channels/tenants

### Tasks

- [x] Build one `spec-complete` Windows QA suite with `finally` cleanup.
- [x] Build one local-Docker `spec_complete_probe.py` orchestrator that reports every
  required gate as JSON.
- [x] Run all targeted tests and full tests.
- [x] Run all browser suites through Nginx.
- [x] Run both eval suites.
- [x] Produce a backup and restore it into a temporary isolated database, then
  query expected seeded and fixture records before destroying that database.
- [x] Run the original HackerNews top-10 Code-as-Action flow repeatedly and
  record GLM-4.5 Air as the provider/model, one warmup, five measured
  end-to-end latencies, and sandbox/code evidence; every measured run must pass
  `<5s`.
- [x] Run the original Fibonacci Code-as-Action verification and prove the
  sandbox result is exactly `55`.
- [x] Audit every new/repaired module for happy-path, error-path, and edge-case
  tests; add any missing cases before closure.
- [x] Build a one-to-one ledger for every original P1-P6 verification gate and
  explicit `Verify:` step, execute each non-deferred gate, and attach exact
  evidence; similar substitute scenarios do not count.
- [x] Measure and enforce every budget in Test and Evidence Architecture.
- [x] Run sandbox, audit, authorization, secret-redaction, clean-start, and
  multi-tenant negative suites.
- [x] Confirm no QA data remains.
- [x] Update every matrix row to `implemented-and-verified` or original V1
  non-goal.
- [x] Close every unchecked item in `PROBLEM_TODO_LIST.md` or prove it is not a
  V1 requirement.
- [x] Inspect actual diff for complexity/owner regressions.
- [x] Record evidence paths and exact command results.

W11 completion note:
the local Docker runtime has no configured live GLM provider
(`GLM_API_KEY_SET|False`, `default_providers|0`, `all_providers|0`). W11
therefore verifies the configurable OpenAI-compatible provider path with
disposable mock providers and records live GLM as an external-credential proof
boundary rather than claiming a real GLM API call.

### Verification

```powershell
cd E:\Chainless
docker-compose up -d --build
docker-compose ps
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test pytest -q
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm frontend-test npm run lint
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm frontend-test npm run build
docker-compose exec -T backend python scripts/spec_complete_probe.py --base-url http://chainless-nginx
docker-compose exec -T backend python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0
docker-compose exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
docker-compose exec -T backend ./scripts/backup.sh
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test sh -lc "PYTHONPATH=/repo/backend python /repo/backend/scripts/restore_drill.py"
docker-compose exec -T backend python scripts/performance_probe.py --base-url http://chainless-nginx --scenario hackernews-code-action --measured-runs 5 --max-ms 5000
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost -Browser chrome -Headless `
  -Suite spec-complete -TimeoutMs 120000
```

Expected:

- Every command exits successfully.
- Final browser report has `ok: true`.
- Final local-Docker API probe has `ok: true`.
- Isolated restore drill proves expected records and leaves live data untouched.
- All five measured HackerNews Code-as-Action end-to-end runs are below
  `5000ms` and include real sandbox/code evidence.
- Matrix has no V1 `missing` or `implemented-but-unverified` rows.
- Original gate ledger has no unmapped or unexecuted non-deferred row.
- Problem list has no unresolved V1 issue.
- Live GLM and real Feishu group receipt are not falsely claimed when the
  required external credentials are absent; the verified state is recorded as
  an external proof boundary.

### Stop Condition

The approved reconciliation spec is fully implemented and verified. There are
no V1 tail items, no QA-created data, no stale authority rows, and no unverified
production claim.

---

## Risks

- Frontend scope could tempt a redesign. Guard: use existing style and require
  screenshot/scroll regressions.
- Contract normalization could break current callers. Guard: extract adapters,
  test frontend and local probes before retiring aliases.
- Dynamic sub-agents can create runaway cost/concurrency. Guard: depth,
  parallelism, timeout, scoped capability, cancellation, and shared-budget
  enforcement with tests.
- Multi-tenant/restore testing can damage real data. Guard: mandatory isolated
  derived test environment that fails closed if identity is not proven.
- Nginx can break SSE buffering/timeouts. Guard: canonical SSE browser test
  through Nginx before closure.
- Administrative UI can expose secrets or privileged MCP execution. Guard:
  admin-only authorization, write-only secrets, redaction, and audit tests.
- Artifact/upload flows can exhaust storage or escape paths. Guard: quotas,
  retention, normalization, bounded content, and traversal tests.
- Plan breadth can produce hidden tails. Guard: workstream stop conditions and
  current-workstream issue resolution rule.

## Retirement

- Retire stale gap matrix states.
- Retire public legacy SSE event names after compatibility proof.
- Retire placeholder-only Diff behavior.
- Retire direct-port-only production topology claim.
- Retire publicly published internal-service ports in the production profile.
- Retire route-local API envelope/pagination variations.
- Retire in-memory V1 resource ownership where durable persistence is required.
- Retire manual-only migration/seed and unaudited administrative mutation.
- Retire any API-only platform feature claim once the Web UI surface ships.
- Do not retire persistent live data without explicit scoped confirmation.

## Completion Authority

This plan does not authorize a completion claim by itself. Completion requires
fresh evidence from Workstream 11 and an Aegis
`verification-before-completion` closeout against the approved reconciliation
spec.
