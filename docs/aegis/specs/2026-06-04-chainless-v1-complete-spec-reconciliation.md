# Chainless V1 Complete Spec Reconciliation

**Status**: Approved  
**Type**: Spec Reconciliation / Spec Delta  
**Created**: 2026-06-04  
**Approved**: 2026-06-05  
**Execution Amendment**: The user-approved engineering-reviewed execution plan
dated 2026-06-05 refines implementation and security details while preserving
this reconciliation's product scope.  
**Parent Spec**: `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`  
**Parent Plan**: `docs/aegis/plans/2026-06-02-chainless-implementation.md`  
**Runtime Evidence Tracker**: `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`  
**Gap Matrix**: `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`  
**Operational Notes**: `docs/remote-windows-runtime-notes.md`

## Goal

Create one reconciled authority boundary for the active implementation pass so
Chainless V1 can be completed against the original design spec and
implementation plan without leaving hidden "tail items".

This document does not implement code. It defines what the active detailed
execution plan must cover, what is already complete, what must ship, what is
an original V1 non-goal, and what requires external credentials for final proof.

## Reconciliation Rule

The user's current requirement is: the next version must fully complete the
spec in one pass.

Therefore:

- Anything required by the 2026-06-02 design spec or implementation plan is
  `must ship`, unless it is explicitly listed as a V1 non-goal in the original
  spec.
- Anything previously marked `explicit defer` only remains deferred if the
  original spec itself made it V2 or the user explicitly approves deferral.
- A feature is not complete because a route exists. It is complete only when
  the local Docker runtime and browser/API/eval evidence prove it.
- Every original P1-P6 verification gate and explicit `Verify:` step remains
  required unless this reconciliation explicitly classifies it as V2/non-goal.
  A similar substitute scenario does not retire an exact original gate.
- Frontend logic may change, but the established dark zinc visual language,
  scroll behavior, and interaction feel must not be rewritten.
- Test data created during QA must be removed before closure.

## Current Verified Baseline

The following baseline is already proven and should be preserved:

- Remote Docker runtime runs PostgreSQL, Redis, backend, frontend,
  sandbox-proxy, sandbox holder, and ARQ worker.
- Public frontend and backend are reachable.
- Login, authenticated `/chat`, conversation create, rename, archive, reload
  selection, first-message send, and SSE chat are verified.
- Agent ReAct loop, builtin tools, MCP echo server, risk classification,
  destructive confirmation, and `code_as_action` sandbox execution are verified.
- Weather, web fetch/search, workspace file tools, and shell confirmation paths
  are verified.
- Memory CRUD, semantic recall, tag recall, and layered instruction injection
  are verified.
- Eval harness runs against the remote runtime with `10 / 10` pass evidence.
- ARQ worker, cron scheduling, Feishu-format channel delivery through a live
  webhook receiver, run records, retries, and deleted-task behavior are
  verified.
- Health, metrics, rate limiting, backup script, restore script validation, and
  production operations docs are verified.
- Windows-local browser QA gate exists and Workstream 10 passed with
  `ok: true`.

## Reconciled Authority Drift

The following drift was identified before the active execution plan was
approved. Workstream 1 reconciles the current-truth matrix and historical
authority notices; the active execution plan owns all remaining work:

- `2026-06-03-spec-runtime-gap-matrix.md` still contains stale states for some
  Workstream 8-10 items that are now verified in the execution checklist and
  problem list.
- The design spec contains a topology diagram with MinIO, while Section 1 and
  Appendix E explicitly defer MinIO to V2. Reconciled V1 outcome: no MinIO.
- The design spec and implementation plan mention Nginx / TLS / rate limiting,
  while Workstream 9 documented direct exposed ports as current runtime.
  Reconciled V1 outcome: add a compose-managed Nginx reverse proxy as the
  supported production entrypoint.
- The design spec marks Skill Precipitation as V2, but the API endpoint list
  includes `/skills`. Reconciled V1 outcome: skill precipitation remains V2;
  passive skill library / trigger metadata is only required if needed to satisfy
  the current "skill trigger match" context-builder promise.
- The original left panel was simplified by design review to "history +
  settings only", but the directory structure still lists full dashboard routes.
  Reconciled V1 outcome: left panel stays visually simple, but settings must
  expose the required configuration surfaces.

## Reconciled V1 Must-Ship Scope

### 1. Deployment and Operations

Must ship:

- `docker-compose up -d` starts the full supported stack from a clean checkout.
- All canonical container names are present and healthy where health checks
  apply.
- Backend health reports DB, Redis, worker, and sandbox live state.
- Metrics expose DB, Redis, worker, sandbox, rate limit, and useful runtime
  counters.
- Backup creates a real SQL dump and restore script validates input.
- Seed data creates a usable default tenant/admin/provider flow.
- A compose-managed Nginx gateway service routes frontend and `/api/v1/*`,
  supports documented TLS certificate mounting, and is the supported V1
  production entrypoint.

Acceptance evidence:

- Fresh remote `docker-compose up -d`.
- `docker-compose ps` shows the expected canonical services.
- Public browser opens through the supported V1 entry URL.
- Health and metrics pass.
- Backup and restore validation pass.
- No anonymous exited compose replacement containers remain after rebuild.
- Final evidence maps and executes every original P1-P6 verification gate and
  explicit `Verify:` step that is not an approved V2/non-goal.

### 2. API Contract Parity

Must ship:

- All V1 REST routes in the reconciled API surface exist or are explicitly
  removed from V1 by this document.
- All non-streaming errors return `{error: {code, message, detail}}`.
- All list endpoints return `{items, total, limit, offset, next}`.
- Auth refresh is available and verified.
- Conversation CRUD is available and verified.
- Agents, tools/MCP, memories, proactive tasks, Feishu channel config,
  LLM providers, and system routes are available and verified.
- Skills precipitation remains V2. If a skill library route exists in V1, it
  must be passive read/create metadata only and must not claim precipitation.

Acceptance evidence:

- Remote API contract probe covers success and representative 401, 404, 422,
  and backend failure paths.
- Pagination probe covers every list route family.
- OpenAPI schema does not advertise routes that are not implemented.

### 3. SSE Protocol Parity

Must ship:

- Backend emits stable typed SSE events compatible with the design contract:
  `text`, `tool_call`, `tool_result`, `sandbox`, `sandbox_output`, `done`,
  `error`.
- Existing internal event names may remain only as compatibility aliases if the
  frontend and tests consume the canonical contract.
- SSE error events use the unified error envelope.
- Frontend consumes tool, sandbox, confirmation, text, done, and error events
  without relying on ad hoc text parsing.

Acceptance evidence:

- API-level SSE probe records event names and JSON shapes.
- Browser chat verifies text streaming, tool card, sandbox/code output,
  confirmation, done state, and error state.

### 4. Agent Engine and Code-as-Action

Must ship:

- ReAct loop remains the canonical agent execution owner.
- Complexity router can choose direct tool, ReAct, or Code-as-Action.
- Code-as-Action executes real generated Python in sandbox and streams output.
- Dynamic `spawn_sub_agent(prompt, context="")` is implemented inside the
  Code-as-Action extension because it is required by AD14 and Section 4.3.
- Sub-agent constraints match the original spec:
  - max depth 1
  - max parallelism 5
  - timeout 15 seconds per sub-agent
  - shared budget accounting
  - results written to a run-scoped path under
    `/workspace/runs/{run_id}/sub_results/`; this is the approved
    engineering-review security refinement of the original shared
    `/workspace/_sub_results/` suggestion
  - same sandbox/security boundary
- Sub-agents are temporary runtime workers, not persistent UI "subagents" in
  the Codex app sidebar.

Acceptance evidence:

- Browser triggers a task that genuinely uses `code_as_action`.
- Browser or API triggers a task that genuinely calls `spawn_sub_agent` at least
  twice in parallel and aggregates results.
- Backend logs and sandbox artifacts prove execution, not merely model text.
- Failure, timeout, and partial result behavior are verified.

### 5. Tool Ecosystem and Safety

Must ship:

- Builtin tools: `file_read`, `file_write`, `file_list`, `web_fetch`,
  `web_search`, `weather_get`, `shell_exec`, `code_as_action`.
- MCP registration, discovery, invocation, idle lifecycle, reconnect/failure,
  and risk default behavior.
- Tool risk levels: `safe`, `risky`, `destructive`.
- Destructive tools require inline confirmation in interactive chat.
- Proactive tasks use pre-authorized tool lists and block non-authorized tools.
- Tool cards show tool name, args, status, risk, result/error, and timing when
  available.

Acceptance evidence:

- Remote Agent-loop verification for each builtin tool.
- Browser verification for weather, web, file, MCP, code, and destructive
  confirmation.
- Proactive pre-authorization violation test proves a blocked tool is logged and
  not executed.

### 6. Memory and Context

Must ship:

- Layered instruction merge from enterprise, user, project, rules, and local.
- Short-term conversation context from Redis or durable equivalent.
- Persistent memory CRUD by type and tag.
- pgvector semantic recall with embedding fallback.
- Tag recall takes priority and semantic recall fills remaining budget.
- Session injection emits citations using `[memory:name]` and
  `[context:layer]` where factual claims depend on memory/context.
- Skill precipitation remains V2, but the context builder's "skill trigger
  match" line must not be a dead promise. Either implement passive trigger
  matching for V1 skills metadata or revise the context-builder spec to remove
  this V1 claim.

Acceptance evidence:

- Remote API verifies create, update, list, tag search, semantic search, merge,
  and deletion cleanup.
- Browser chat proves memory and layered instruction influence responses.
- Eval includes memory citation checks.

### 7. Proactive Service and Feishu

Must ship:

- Proactive task CRUD.
- ARQ worker service in compose.
- Cron scheduling in the real runtime.
- Recent run records with status, attempts, delivery result, and errors.
- Feishu channel config and test delivery.
- Scheduled delivery to Feishu-compatible webhook.
- Retry behavior.
- Deleted or disabled tasks stop running after source-of-truth refresh.

External credential boundary:

- A real Feishu group receipt can only be proven if the user supplies a real
  Feishu webhook URL and secret.
- Without those credentials, the system can prove the runtime path against a
  live webhook receiver, but the final claim must say "Feishu-compatible
  delivery verified" rather than "real Feishu group receipt verified".

Acceptance evidence:

- Remote scheduled task fires at least once.
- Receiver captures the exact Feishu card payload.
- If real credentials are supplied, real Feishu group receives both test and
  scheduled messages.
- Cleanup removes test tasks and subsequent worker logs prove no rerun.

### 8. Eval and Hallucination Guard

Must ship:

- Eval runner supports JSON output, minimum pass threshold, and explicit failure
  reporting.
- Eval suite covers at least:
  - basic chat
  - weather
  - web fetch/search
  - file tools
  - MCP
  - code_as_action
  - spawn_sub_agent
  - destructive confirmation
  - memory recall and citations
  - proactive task safety
- Hallucination judge or deterministic citation checks enforce tool/memory/
  context reference rules where feasible.
- Eval gate is runnable from the remote backend container.

Acceptance evidence:

- `python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0` passes.
- Additional spec-complete eval suite passes at the threshold chosen by the
  next execution plan.

### 9. Frontend Product Surface

Must ship without changing established style:

- `/login`
- `/chat`
- Settings access from the left panel.
- Settings sections or dashboard routes for:
  - LLM providers
  - agents
  - tools and MCP servers
  - memories
  - Feishu channel
  - proactive tasks
  - system health / metrics / eval status
- Conversation history create, open, rename, archive/delete, and reload reopen.
- Three-panel IDE-style layout:
  - left: conversation history and settings entry
  - center: chat stream
  - right: preview, terminal, files, diff
- Right panel diff must show a real diff-producing flow, not only an empty
  placeholder.
- Tool cards, terminal blocks, confirmation cards, loading/empty/error states.
- Context banner showing the active injected instruction/memory summary without
  changing the established chat layout or visual language.
- Rich input area:
  - multiline composer
  - `Ctrl+Enter` send
  - `Ctrl+N` new conversation
  - `Ctrl+K` command palette or command entry
  - `+file` attachment path if supported by the backend
  - `@tool` mention or tool picker if supported by the backend

Acceptance evidence:

- Windows browser QA covers all product routes and settings sections.
- Screenshots prove the original visual language is preserved.
- Tests verify scroll behavior still works.
- Test-created conversations, memories, tools, channels, and proactive tasks are
  cleaned up.

### 10. Multi-Tenant Runtime

Must ship:

- Three tenants can log in and use chat concurrently without data leakage.
- Tenant isolation applies to conversations, memories, tools/MCP config,
  providers, channels, proactive tasks, and eval-visible state.
- Rate limiting and metrics do not leak sensitive tenant data.

Acceptance evidence:

- Remote/browser or API concurrency probe creates three tenants and runs
  parallel chat/tool/memory flows.
- Cross-tenant read attempts return 404 or authorization errors with the unified
  envelope.
- Cleanup removes only test tenants or uses a fresh isolated test database.

## Original V1 Non-Goals That Remain Non-Goals

These are not required for V1 completion unless the user explicitly promotes
them:

- Model training or fine-tuning.
- OpenAPI Bridge.
- Skill Precipitation.
- MinIO object storage.
- LDAP/SAML SSO.
- Billing.
- Mobile app.
- Additional channels beyond Feishu.

## Reconciled Decisions

| Topic | Decision | Reason |
|---|---|---|
| Frontend style | Preserve current style | User explicitly forbids unauthorized frontend style changes. |
| Nginx / proxy | Compose-managed Nginx must ship | User approved the original spec-aligned integrated production entrypoint on 2026-06-05. |
| MinIO | Remove from V1 | Original non-goal and Appendix E defer MinIO to V2. |
| Skills | Precipitation stays V2; passive metadata is allowed | Original non-goal conflicts with endpoint list; V1 should not claim precipitation. |
| Dynamic sub-agent | Must ship for spec-complete V1 | AD14 and Section 4.3 require it. |
| Dashboard/admin UI | Must ship through settings/dashboard surfaces | Configurable LLM, agent, tools, memory, channel, and proactive features must be user-operable, not API-only. |
| Diff panel | Must ship real behavior | Design review required terminal + diff viewer; placeholder is insufficient. |
| Feishu verification | Runtime must ship; real group receipt depends on user credentials | Cannot prove external Feishu receipt without webhook credentials. |
| Runtime source of truth | Local Docker Desktop | Local Windows is the browser QA/control plane; the old remote server is retired. |

## Anti-Entropy Boundary

Retire or correct stale authority during the next plan:

- Update the gap matrix so verified Workstream 8-10 rows no longer remain stale.
- Remove or revise any code/docs that advertise V1 Skill Precipitation.
- Remove MinIO from V1 topology docs or mark it clearly as V2.
- Retire "direct ports are the complete V1 production topology" as a
  final-production claim. Direct ports may remain a development/debug mode.

No live data deletion is authorized by this reconciliation. Any cleanup of real
tenant data requires explicit scoped confirmation.

## Product Risk Lens

- Value: finishing the full spec turns Chainless from a chat demo with strong
  runtime pieces into an operable self-hosted Agent platform.
- Non-goals: do not expand into V2 OpenAPI Bridge, Skill Precipitation, MinIO,
  SSO, billing, mobile, or extra channels.
- Trade-offs: adding admin/settings UI and protocol parity is less flashy than
  new agent tricks, but it removes the largest production-readiness gap.
- Decision: Compose-managed Nginx/TLS entrypoint is required for V1.

## Architecture Integrity Lens

- Invariant: one production-grade Agent platform, not disconnected API demos.
- Canonical owners:
  - API contracts: `backend/app/api/v1/*`
  - agent execution: `backend/app/core/agent/*`
  - tool execution: `backend/app/core/tools/*`
  - sandbox runtime: `backend/app/core/sandbox/*` and `sandbox-proxy/*`
  - memory: `backend/app/core/memory/*`
  - proactive/channel: `backend/app/core/proactive/*`,
    `backend/app/core/channel/*`
  - frontend interaction: `frontend/src/app/*`,
    `frontend/src/components/*`, `frontend/src/stores/*`
  - QA gates: `scripts/windows-browser-qa.*`, eval scripts, remote Docker
    commands documented in operations notes
- Responsibility overlap risk: settings/dashboard work could scatter state
  across chat store and ad hoc components. The active plan defines separate
  stores and owner modules for admin surfaces.
- Higher-level simplification: keep chat execution state separate from platform
  configuration state.
- Verdict: proceed to detailed implementation planning only after this
  reconciliation is accepted.

## Baseline Role Alignment

- Product / Requirement Baseline:
  original design spec plus current user demand for one-pass full completion.
- Architecture / Runtime Boundary Baseline:
  local Docker runtime, existing verified services, and Windows browser QA
  path.
- Result:
  both `Implementation Drift` and `Design Defect` exist.
- Scope:
  requirements and architecture.
- Next action:
  execute the approved detailed plan against the reconciled current-truth
  matrix.

## Active Execution Plan Shape

The next plan is saved as:

```text
docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md
```

It includes workstreams that fully close:

1. Authority and matrix sync.
2. API envelope, pagination, OpenAPI, and route parity.
3. SSE canonical protocol parity.
4. Dynamic `spawn_sub_agent`.
5. Admin/settings frontend surfaces.
6. Right-panel diff and artifact flows.
7. Rich input and keyboard shortcuts.
8. Proactive pre-authorization and Feishu credential-ready validation.
9. Multi-tenant concurrency/isolation.
10. Nginx/proxy final boundary.
11. Final full QA, eval, cleanup, and evidence bundle.

Each workstream must have:

- exact files
- explicit no-style-drift boundary
- remote Docker verification
- Windows browser verification where user-facing
- API/eval verification where contract-facing
- test data cleanup
- problem list and matrix update
- stop condition that leaves no tail item

## User Review Gate

Approved by the user on 2026-06-05. The approved boundary includes
Compose-managed Nginx, dynamic `spawn_sub_agent`, dashboard/settings UI, and
real diff behavior as must-ship requirements.
