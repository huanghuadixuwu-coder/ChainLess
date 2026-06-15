# Chainless Spec Gap Closure Checklist

**Status**: Historical execution evidence; superseded for remaining work  
**Type**: Historical Implementation Plan / Runtime Evidence  
**Created**: 2026-06-03  
**Reconciled**: 2026-06-05  
**Parent Spec**: [Chainless Agent Platform Design Spec](../specs/2026-06-02-chainless-agent-platform-design.md)  
**Parent Plan**: [Chainless Agent Platform Implementation Plan](./2026-06-02-chainless-implementation.md)
**Approved Reconciliation**: [2026-06-04-chainless-v1-complete-spec-reconciliation.md](../specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md)  
**Only Active Remaining-Work Tracker**: [2026-06-05-chainless-v1-complete-spec-execution-plan.md](./2026-06-05-chainless-v1-complete-spec-execution-plan.md)

> Authority notice: preserve this document as evidence of the historical
> Workstream 1-10 pass. Its unchecked boxes, old workstream numbers, and
> direct-port deployment decisions are not active remaining-work authority.
> All remaining V1 work is owned only by the 2026-06-05 execution plan.

## Goal

Close the remaining gaps between the current `E:\Chainless` codebase and the promised scope in the design spec / implementation plan, without changing the established frontend visual style, scroll behavior, or interaction feel.

## Architecture

Current verified baseline:

- Transitional public frontend on `:3000`
- Transitional public FastAPI backend on `:8000`
- PostgreSQL + pgvector
- Redis
- ARQ worker
- `sandbox-proxy` + sandbox execution
- Login, conversation CRUD/reload, chat SSE, tool/MCP, Code-as-Action,
  confirmation, memory, eval, scheduler, Feishu-format webhook delivery,
  health, metrics, rate limiting, backup, and Windows browser QA

Target gap-closure outcome:

- API surface matches the spec where required for v1
- Frontend product surfaces match the spec's declared UX scope
- Agent UI exposes tool / terminal / confirmation states end-to-end
- MCP / proactive / eval / Feishu / production hardening are not merely scaffolded, but runnable and verified
- Compose-managed Nginx is the supported production entrypoint; direct service
  ports are transitional until the new production gateway workstream closes

## Tech Stack

- Backend: FastAPI, SQLAlchemy async, Redis, ARQ, pgvector
- Frontend: Next.js, React, Zustand, current project UI primitives
- Runtime: Docker Compose, sandbox-proxy, Docker sandbox
- QA path: local Windows browser automation against remote Docker deployment

## Baseline / Authority Refs

- [docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md](E:/Chainless/docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md)
- [docs/aegis/plans/2026-06-02-chainless-implementation.md](E:/Chainless/docs/aegis/plans/2026-06-02-chainless-implementation.md)
- [PROBLEM_TODO_LIST.md](E:/Chainless/PROBLEM_TODO_LIST.md)
- [docs/aegis/BASELINE-GOVERNANCE.md](E:/Chainless/docs/aegis/BASELINE-GOVERNANCE.md)

## Compatibility Boundary

- Preserve the current frontend visual language and layout feel unless the spec explicitly requires a missing surface.
- Do not change scroll behavior, spacing language, or UI tone as a side effect of logic work.
- Prefer filling missing logic inside existing owners before inventing new product surfaces.
- Keep the already-fixed public routing, login, sandbox health, weather, and memory fallback behavior intact.

## Verification

Completion of this checklist is only proven by:

- real browser verification against the remote Docker deployment
- endpoint verification against the live backend
- targeted regression checks for previously fixed issues
- evidence that each spec-declared surface is either working, explicitly deferred with approval, or intentionally removed from scope

---

## Plan Basis

### Facts

- The current frontend app still lacks the approved settings/administration
  surface and real artifact/diff flow.
- The right-side Preview, Terminal, and Files baseline is verified; Diff remains
  placeholder-only.
- ARQ worker, scheduler, eval, Feishu-format webhook delivery, health, metrics,
  rate limiting, backup, and the Workstream 10 browser gate are verified.
- `docker-compose.yml` still has no compose-managed Nginx production entrypoint.
- Dynamic `spawn_sub_agent`, passive skill metadata/trigger matching, canonical
  SSE parity, full API contract parity, and three-tenant isolation remain open.
- Current Next.js `16.2.7`, React `19.2.4`, and PostgreSQL `16` are accepted;
  the historical version declarations do not authorize a downgrade.

### Assumptions

- The v1 target still includes the spec's declared product surfaces unless the user later narrows scope.
- The current remote Docker environment remains the source of truth for runtime verification.
- Some surfaces already have code scaffolding and primarily need QA-backed closure rather than net-new architecture.

### Unknowns

- Real external Feishu receipt remains credential-dependent; the internal
  Feishu-format delivery path is verified.
- MinIO and Skill Precipitation remain V2. Passive skill metadata and trigger
  matching are V1 and owned by Workstream 5.
- Compose-managed Nginx is approved and owned by Workstream 10.

---

## Architecture Integrity Lens

- Invariant: one production-grade agent platform, not a partial demo with disconnected surfaces.
- Canonical owners:
  - API contracts: `backend/app/api/v1/*`
  - Agent execution and confirmations: `backend/app/core/agent/*`
  - Memory behavior: `backend/app/core/memory/*`
  - Proactive scheduling: `backend/app/core/proactive/*`
  - Frontend interaction contract: `frontend/src/app/*`, `frontend/src/stores/*`, `frontend/src/components/*`
- Responsibility overlap risk:
  - chat UX completion could sprawl across `chat/page.tsx`, store logic, and ad hoc new components
  - production readiness could fragment across scripts, compose, and undocumented runtime assumptions
- Higher-level simplification:
  - close gaps by workstream, not by file
  - keep spec parity separate from extra polish
- Verdict: proceed with one durable gap-closure plan, then execute by workstream

## Plan Pressure Test

- Owner / contract / retirement:
  current risk is not one broken file, but partial contract coverage across frontend, backend, and deployment surfaces.
- Architecture integrity / higher-level path:
  the missing work clusters cleanly into API parity, frontend UX parity, agent UI parity, tool/memory verification, proactive/channel/eval, and production hardening.
- Verification scope:
  broad; requires live browser + remote runtime, not unit checks alone.
- Task executability:
  good, if executed in the order below.
- Pressure result: proceed

## Plan-Time Complexity Check

- Target files:
  `backend/app/api/v1/*`, `backend/app/core/*`, `frontend/src/app/*`, `frontend/src/components/*`, `docker-compose.yml`, deployment scripts
- Existing size / shape signals:
  chat surface and conversation flows are already concentrated in a small set of files, which is good; product-surface parity is the bigger issue.
- Owner fit:
  existing owner boundaries are mostly usable; avoid scattering missing UI states into unrelated files.
- Add-in-place risk:
  medium on chat UI and system routes; low elsewhere.
- Better file boundary:
  add only owner-aligned files for missing spec surfaces such as right panel subcomponents or missing API route modules.
- Recommendation: edit-in-place for current owners, add owner files only where the spec clearly demands a distinct surface

---

## Strict Execution Checklist

Execution order is mandatory. Do not skip a workstream because a later one seems easier.

### Workstream 1: Freeze the authoritative v1 gap map

- [x] Produce a spec-to-runtime matrix with three states per item: `implemented-and-verified`, `implemented-but-unverified`, `missing`.
- [x] Reconcile each V1 surface as `ship`, closed baseline, accepted drift, or explicit V2.
- [x] Make the 2026-06-05 execution plan the only active tracker for remaining work.

Files:
- [docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md](E:/Chainless/docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md)
- [docs/aegis/plans/2026-06-02-chainless-implementation.md](E:/Chainless/docs/aegis/plans/2026-06-02-chainless-implementation.md)
- [PROBLEM_TODO_LIST.md](E:/Chainless/PROBLEM_TODO_LIST.md)

Verification:
- every spec section from API, memory, tools, proactive/channel, frontend, and production polish appears in the matrix

Stop condition:
- no remaining work item is floating outside the current-truth matrix and the
  owning workstream in the 2026-06-05 execution plan

### Workstream 2: Close backend API parity gaps

- [ ] Add missing spec-required endpoints or document approved deviations:
  - `POST /api/v1/auth/refresh`
  - `DELETE /api/v1/conversations/:id`
  - `GET /api/v1/system/metrics`
  - skills endpoints if still in v1 scope
  - generic channel list/config/test contract if Feishu-only endpoints are insufficient
- [ ] Align endpoint naming and path semantics with the spec or record explicit deviations.
- [ ] Ensure every list endpoint follows the same pagination envelope.
- [ ] Ensure every error path follows the unified JSON error envelope.

Primary files:
- [backend/app/api/v1/auth.py](E:/Chainless/backend/app/api/v1/auth.py)
- [backend/app/api/v1/conversations.py](E:/Chainless/backend/app/api/v1/conversations.py)
- [backend/app/api/v1/channels.py](E:/Chainless/backend/app/api/v1/channels.py)
- [backend/app/api/v1/router.py](E:/Chainless/backend/app/api/v1/router.py)
- [backend/app/main.py](E:/Chainless/backend/app/main.py)
- new route modules only if a missing owner is real

Verification:
- curl each added endpoint against remote `:8000`
- verify 401/404/500 style responses still match envelope

Stop condition:
- no spec-required v1 endpoint remains silently absent

### Workstream 3: Finish conversation lifecycle and chat-state parity

- [ ] Verify and complete true conversation CRUD:
  - create
  - list
  - open/select
  - rename
  - delete/archive
- [ ] Ensure the frontend state model and sidebar UX reflect those operations.
- [ ] Add regression coverage for first-message send on a newly created conversation.
- [ ] Prove SSE completion/error handling in the actual browser flow, not just backend logs.

Primary files:
- [frontend/src/stores/chat-store.ts](E:/Chainless/frontend/src/stores/chat-store.ts)
- [frontend/src/components/layout/sidebar.tsx](E:/Chainless/frontend/src/components/layout/sidebar.tsx)
- [frontend/src/app/chat/page.tsx](E:/Chainless/frontend/src/app/chat/page.tsx)
- [backend/app/api/v1/conversations.py](E:/Chainless/backend/app/api/v1/conversations.py)

Verification:
- browser test:
  - login
  - create chat
  - rename chat
  - delete chat
  - create another chat
  - send first message
  - reload and re-open history

Stop condition:
- the user can fully manage conversations from the UI without hidden state drift

### Workstream 4: Finish spec-required agent UI surfaces without style drift

- [x] Replace the current right-panel toggle stub with a real right-side panel that matches the existing style system.
- [ ] Add preview / terminal / files / diff behavior only inside the established visual language.
- [x] Add inline tool-call cards in the chat stream.
- [x] Add terminal output blocks in the chat stream.
- [ ] Add context banner behavior if still required by the spec.
- [ ] Keep current scroll behavior and interaction feel stable while doing so.

Primary files:
- [frontend/src/app/chat/page.tsx](E:/Chainless/frontend/src/app/chat/page.tsx)
- [frontend/src/components/chat/chat-panel.tsx](E:/Chainless/frontend/src/components/chat/chat-panel.tsx)
- [frontend/src/components/chat/message-bubble.tsx](E:/Chainless/frontend/src/components/chat/message-bubble.tsx)
- [frontend/src/components/chat/input-area.tsx](E:/Chainless/frontend/src/components/chat/input-area.tsx)
- new owner-aligned components under `frontend/src/components/chat/` or `frontend/src/components/shared/`

Verification:
- browser QA with screenshots for:
  - tool call shown inline
  - code block render
  - terminal output render
  - right panel open/close
  - preview / terminal / files / diff tabs

Stop condition:
- the frontend matches the spec's declared chat experience without a style regression

### Workstream 5: Close code-as-action and destructive confirmation end-to-end

- [x] Trigger a real `code_as_action` path from the UI and verify generated code executes in sandbox.
- [x] Trigger a real destructive tool confirmation flow from the UI.
- [x] Ensure deny / timeout / approve paths all behave correctly in chat and backend state.
- [x] Verify conversation history records the confirmation outcome cleanly.

Primary files:
- [backend/app/core/agent/engine.py](E:/Chainless/backend/app/core/agent/engine.py)
- [backend/app/core/agent/code_executor.py](E:/Chainless/backend/app/core/agent/code_executor.py)
- [backend/app/api/v1/conversations.py](E:/Chainless/backend/app/api/v1/conversations.py)
- frontend chat components responsible for tool and confirmation rendering

Verification:
- browser scenario for `code_as_action`
- browser scenario for a destructive tool that requires confirmation
- backend log and persisted message history checks

Stop condition:
- the spec's "agent can write code / ask for confirmation / continue" promise is real from the user's point of view

### Workstream 6: Close tool ecosystem parity

- [x] Prove builtin tools cover the intended general-agent core requests beyond weather.
- [x] Run MCP registration, discovery, tool invocation, and failure recovery against at least one real MCP server.
- [x] Confirm risk classification is visible and respected in UI flows.
- [x] Record which tool classes are truly in-scope for v1 and which are not.

Primary files:
- [backend/app/api/v1/tools.py](E:/Chainless/backend/app/api/v1/tools.py)
- [backend/app/core/tools/classifier.py](E:/Chainless/backend/app/core/tools/classifier.py)
- [backend/app/core/tools/mcp/client.py](E:/Chainless/backend/app/core/tools/mcp/client.py)
- [backend/app/core/tools/mcp/manager.py](E:/Chainless/backend/app/core/tools/mcp/manager.py)
- [backend/app/core/tools/builtin/web.py](E:/Chainless/backend/app/core/tools/builtin/web.py)

Verification:
- remote backend container Agent-loop verification for `file_read`, `file_write`, `file_list`, `web_search`, `web_fetch`, `weather_get`, `code_as_action`, and destructive `shell_exec` confirmation routing
- browser-driven weather task with visible `weather_get` card and result: `.gstack/qa-reports/local/workstream6-browser-2026-06-04T02-34-24-773Z/`
- browser-driven file/search task with visible `file_write`, `file_read`, `file_list`, and `web_search` cards: `.gstack/qa-reports/local/workstream6-browser-file-web-2026-06-04T02-36-38-220Z/`
- browser-driven fetch task with visible `web_fetch` card: `.gstack/qa-reports/local/workstream6-browser-web-fetch-2026-06-04T02-41-13-925Z/`
- one real MCP server registration + invocation + failure case: completed with `backend/scripts/mcp_echo_server.py`
- one browser proof that a `risky` tool event is visible in the existing tool activity row: completed at `.gstack/qa-reports/local/workstream6-2026-06-04T01-50-19-991Z/`

Stop condition:
- tool claims in marketing/spec map to evidence, not assumptions

Current checkpoint:
- Workstream 6 is closed for the current v1 tool-ecosystem scope.
- In-scope v1 builtin tool classes are: workspace file read/write/list, web search, web fetch, weather lookup, sandboxed code execution, and destructive shell execution with confirmation.
- `file_ops` now targets the explicit Docker `/workspace` volume and rejects traversal outside that workspace.
- `web_search` now returns structured JSON results with `title`, `url`, `snippet`, and `source`.
- `shell_exec` is intentionally not auto-executed; it is classified as destructive and enters the confirmation path.

### Workstream 7: Close memory-system parity

- [x] Verify tag-based recall separately from semantic recall.
- [x] Verify layered instruction merge behavior with current runtime data.
- [x] Verify memory write, update, search, merge, and chat influence in one end-to-end flow.
- [x] Decide whether any remaining memory encoding/content issues are code problems or seed-data cleanup.

Primary files:
- [backend/app/core/memory/layered.py](E:/Chainless/backend/app/core/memory/layered.py)
- [backend/app/core/memory/persistent.py](E:/Chainless/backend/app/core/memory/persistent.py)
- [backend/app/core/memory/tasks.py](E:/Chainless/backend/app/core/memory/tasks.py)
- [backend/app/api/v1/memories.py](E:/Chainless/backend/app/api/v1/memories.py)

Verification:
- direct API checks covered create, update, list with tag filter, semantic search, merge, and cleanup
- remote API tag-only scenario proved explicit `#tag` memory ranks first while semantic results fill the remaining budget
- browser chat proved injected memory and layered instructions affect assistant output, including `[memory:WS7 Browser Memory]` and `[context:local]` citations:
  `.gstack/qa-reports/local/workstream7-browser-memory-2026-06-04T05-05-33-747Z/`

Stop condition:
- memory is not "works in one lucky path"; all declared retrieval modes are verified

Current checkpoint:
- Workstream 7 is closed for the current v1 memory scope.
- No remaining encoding/content issue was found in the Workstream 7 verification data; the mojibake visible in some historical spec excerpts is document-display debt, not a runtime memory defect.

### Workstream 8: Make eval, scheduler, and Feishu real runtime features

- [x] Run `backend/tests/eval/tasks/basic.json` through the actual evaluation harness and make it pass at an agreed threshold.
- [x] Ensure an ARQ worker service exists in deployment and is documented.
- [x] Verify cron scheduling works in the real remote runtime.
- [x] Verify Feishu test delivery and one scheduled delivery.
- [x] Record failure and retry behavior.

Primary files:
- [backend/scripts/run-eval.py](E:/Chainless/backend/scripts/run-eval.py)
- [backend/tests/eval/tasks/basic.json](E:/Chainless/backend/tests/eval/tasks/basic.json)
- [backend/app/core/proactive/scheduler.py](E:/Chainless/backend/app/core/proactive/scheduler.py)
- [backend/app/api/v1/proactive.py](E:/Chainless/backend/app/api/v1/proactive.py)
- [backend/app/core/channel/feishu.py](E:/Chainless/backend/app/core/channel/feishu.py)
- [docker-compose.yml](E:/Chainless/docker-compose.yml)

Verification:
- remote worker process running:
  `chainless-worker` is up under docker-compose and logs `Starting worker for 2 functions: execute_proactive_task, cron:check_scheduled_tasks`
- eval command output captured:
  `python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0` passed `10 / 10`, `Error: 0 / 10`
- real scheduled run observed:
  a `* * * * *` proactive task executed at `2026-06-04T06:06:04Z` and was deleted after verification
- Feishu receives both test and scheduled message:
  because no real Feishu webhook env var exists on the remote host, delivery was verified against a live HTTP webhook receiver that captured the exact Feishu interactive-card payload for both `/channels/feishu/test` and scheduled proactive delivery
- failure and retry behavior recorded:
  `FeishuChannel.send_with_result()` retries up to 3 attempts and scheduler run records are available through `/api/v1/proactive-tasks/runs`
- deletion behavior verified:
  a deleted proactive test task initially exposed an in-memory cache bug; scheduler refresh now replaces the cache from Redis, and post-fix logs at `06:09` and `06:10` showed no further execution while Redis tasks remained `{}`

Stop condition:
- proactive delivery is not scaffold-only anymore

Current checkpoint:
- Workstream 8 is closed for the current remote runtime scope.
- External Feishu group receipt still requires user-supplied real Feishu webhook credentials; the application runtime path itself is implemented and verified with captured webhook payloads.

### Workstream 9: Close production hardening gaps

- [x] Add or verify:
  - system metrics endpoint
  - rate limiting behavior
  - backup script execution path
  - restore procedure documentation
  - operational health coverage beyond sandbox
  - production compose / proxy story if still required by spec
- [x] Confirm `docker-compose up` remains sufficient for the supported deployment mode.
- [x] Decide whether the Nginx layer is required now or explicitly deferred.

Primary files:
- [backend/app/main.py](E:/Chainless/backend/app/main.py)
- [backend/scripts/backup.sh](E:/Chainless/backend/scripts/backup.sh)
- [docker-compose.yml](E:/Chainless/docker-compose.yml)
- any missing system route modules or deployment files

Verification:
- remote health checks:
  `GET /api/v1/system/health` returned `status: ok`, `db: connected`, `redis: connected`, `worker: ok`, and sandbox `status: ok`
- metrics checks:
  `/api/v1/system/metrics` includes `chainless_db_up 1`, `chainless_redis_up 1`, `chainless_worker_up 1`, `chainless_sandbox_up 1`, and rate-limit gauges
- rate-limit probe:
  after clearing Redis `ratelimit:*`, 70 requests to `/api/v1/system/metrics` produced `429` responses
- backup script artifact check:
  `docker-compose exec -T backend ./scripts/backup.sh` produced `/backups/chainless-20260604-064743.sql`; artifact is non-empty and begins with a PostgreSQL database dump header
- restore script/runtime check:
  `pg_dump` and `psql` are installed in the backend container; `./scripts/restore.sh` validates required input and returns usage with exit code `2` when called without a file
- compose sufficiency:
  remote `docker-compose up -d` converged with db, redis, sandbox-proxy, backend, worker, frontend, and sandbox all up; backend is `Up (healthy)`
- production/proxy story at the time of this historical pass:
  direct-port compose was verified as the current runtime. The approved
  reconciliation supersedes the old boundary: compose-managed Nginx must ship
  in the new Workstream 10.

Stop condition:
- production-readiness claims are backed by repeatable operational evidence

Current checkpoint:
- Workstream 9 is closed for backend/runtime operational readiness.
- Compose-managed Nginx, private internal networking, sandbox negative security
  tests, audit, auto-migration, idempotent seed, and isolated restore proof are
  not historical Workstream 9 tail items; they are owned by the new Workstream
  10 and Workstream 11.

### Workstream 10: Close frontend polish and QA gates

- [x] Add loading, empty, and error states required by the spec.
- [x] Add keyboard shortcuts only if they are still in scope and can be added without style drift.
- [x] Expand the local Windows browser QA path into repeatable regression scripts for:
  - auth
  - conversation CRUD
  - chat SSE
  - tool cards / right panel
  - code_as_action
  - destructive confirmation
- [x] Keep `PROBLEM_TODO_LIST.md` aligned with current truth after each closure.

Primary files:
- [frontend/src/components/chat/*](E:/Chainless/frontend/src/components/chat)
- [frontend/src/components/layout/sidebar.tsx](E:/Chainless/frontend/src/components/layout/sidebar.tsx)
- [scripts/windows-browser-qa.ps1](E:/Chainless/scripts/windows-browser-qa.ps1)
- [scripts/windows-browser-qa.cjs](E:/Chainless/scripts/windows-browser-qa.cjs)
- [PROBLEM_TODO_LIST.md](E:/Chainless/PROBLEM_TODO_LIST.md)

Verification:
- frontend production build:
  remote `docker build -t chainless_frontend:latest ./frontend` completed `next build` and TypeScript successfully.
- remote deployment:
  `chainless-frontend` was restarted and `docker-compose ps` showed db, redis, backend, frontend, sandbox-proxy, sandbox, and worker all up.
- repeatable local browser run with saved evidence:
  `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://118.196.142.31:3000 -Browser chrome -Headless -Suite workstream10 -TimeoutMs 60000`
  passed with `ok: true`.
- Workstream 10 browser steps covered:
  auth login, conversation create, rename, archive, chat SSE, `web_fetch` tool card, right-panel Files tab, `code_as_action` with visible `42`, destructive confirmation deny, and cleanup of test conversations.
- evidence artifacts:
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/report.json`
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/01-auth-login.png`
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/02-chat-sse.png`
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/03-tool-panel.png`
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/04-code-as-action.png`
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/05-destructive-confirmation.png`

Stop condition:
- we have a stable regression gate for the remaining feature work

Current checkpoint:
- Workstream 10 is closed for frontend polish and browser QA gate scope.
- No frontend style rewrite was introduced; changes stayed inside existing zinc/dark visual classes and owner-aligned state/test logic.

---

## Risks

- Reintroducing frontend style regressions while filling chat UI gaps
- Mistaking "route exists" for "feature is production-ready"
- Shipping proactive/memory features without their runtime worker path
- Letting spec-declared surfaces silently drift into permanent partial implementations

## Retirement

- Remove any temporary stopgap UI introduced during QA once the final owner-aligned version exists.
- Retire endpoint or file-path deviations only after the spec-parity matrix is updated.
- Do not carry forward dead toggle-only surfaces once the real replacement is shipped.

## Historical Execution Order

1. Workstream 1
2. Workstream 2
3. Workstream 3
4. Workstream 4
5. Workstream 5
6. Workstream 6
7. Workstream 7
8. Workstream 8
9. Workstream 9
10. Workstream 10
11. Workstream 11

## Historical Workstream 11 Closure

- Workstream 11 ran the final spec-complete release gate in local Docker
  Desktop, not on the retired remote server.
- Evidence includes fresh `docker-compose up -d --build`, full backend tests
  (`339 passed, 4 skipped`), frontend lint/build, `spec_complete_probe.py`,
  Windows Chrome `spec-complete` browser QA, both eval suites, backup, isolated
  restore drill, Fibonacci `55`, HackerNews top-10 Code-as-Action under `5s`,
  and residue cleanup.
- The authoritative one-to-one original gate mapping is
  [original-gate-ledger.md](../work/2026-06-05-v1-spec-completion/original-gate-ledger.md).
- Live GLM API and real Feishu group receipt are external-credential proof
  boundaries in the current local Docker environment, not claimed as executed
  without credentials.

## Historical Exit Rule

Do not claim "spec met" when only the happy-path chat demo works.
The objective is achieved only when each remaining spec surface is either:

- implemented and verified in the live environment
- explicitly deferred with user approval
- or intentionally removed from scope with the baseline updated accordingly

## Authority Closure

- Historical Workstreams 8, 9, and 10 are closed for their recorded current
  runtime scopes and evidence.
- Historical Workstream 11 closes the final spec-complete local-Docker evidence
  bundle for the current V1 scope, with live GLM and real Feishu receipt kept as
  explicit external-credential proof boundaries.
- The current-truth registry is
  [2026-06-03-spec-runtime-gap-matrix.md](./2026-06-03-spec-runtime-gap-matrix.md).
- The only active remaining-work tracker is
  [2026-06-05-chainless-v1-complete-spec-execution-plan.md](./2026-06-05-chainless-v1-complete-spec-execution-plan.md).
