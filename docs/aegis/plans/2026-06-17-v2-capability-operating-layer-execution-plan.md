# Chainless V2 Capability Operating Layer Execution Plan

Status: Ready for implementation after plan-eng-review revisions
Type: V2 Implementation Plan
Created: 2026-06-17
Approved Spec: `docs/aegis/specs/2026-06-16-v2-capability-operating-layer-design.md`
Plan Review: `/plan-eng-review` completed on 2026-06-17; decisions incorporated.

## Goal

Implement the V2 Capability Operating Layer: a personal, auditable capability
system where successful or evidence-rich chat runs can generate inactive
Memory, Skill, and Worker candidates; candidates live in a personal Inbox until
the user accepts, edits, dismisses, merges, archives, or mutes them; accepted
capabilities influence future Agent planning; and Workers become Agent-callable
executable capabilities guarded by policy, hooks, trace, and fallback rules.

This plan is implementation-only. It does not change the approved product
scope. It does not authorize commits, frontend restyling, team capability
publishing, or full administrator Managed Settings.

## Architecture

```text
Chat Run
  |
  | after completion or useful failure evidence
  v
Capability Rule Filter
  |
  | if signal matches
  v
Capability Analyzer
  |
  v
Capability Candidate Service
  |
  +--> Chat lightweight hint / SSE event
  |
  `--> Personal Capability Inbox
          |
          | user accepts
          v
     Memory / Skill / Worker
          |
          v
Agent Capability Retrieval
          |
          v
Soft Merge Planner
          |
          v
Policy Guard + Hook Runtime
          |
          v
Tool calls / WorkerRun / normal Agent execution
          |
          v
Trace, feedback, fallback, new candidates
```

Owner boundaries:

- Capability candidate source of truth:
  `backend/app/core/capabilities/`, `backend/app/models/capability.py`,
  `backend/app/api/v1/capabilities.py`. Public REST path is locked to
  `/api/v1/capability-candidates`.
- Candidate analysis outbox source of truth:
  `backend/app/core/capabilities/outbox.py` and explicit analysis job fields
  in `backend/app/models/capability.py`. Stream-tail analysis is an
  optimization, not the only durable path.
- Worker source of truth:
  `backend/app/core/workers/`, `backend/app/models/worker.py`,
  `backend/app/api/v1/workers.py`
- Personal Memory and Skill scope:
  existing Memory and Skill owners remain, but V2 must enforce per-user
  capability visibility through `user_id`/scope-aware queries and migrations.
- Agent planning integration:
  `backend/app/core/capabilities/retrieval.py`,
  `backend/app/core/agent/prompt_builder.py`,
  `backend/app/services/conversation_stream_service.py`
- Worker matching and invocation:
  `backend/app/core/workers/matcher.py`,
  `backend/app/core/workers/runtime.py`
- Minimal policy facade:
  `backend/app/core/capabilities/policy.py` is introduced before executable
  Worker runtime can run. W6 expands the policy and hook surface, but W4 must
  not create an unguarded Worker execution window.
- Hard guard and hooks:
  `backend/app/core/capabilities/policy.py`,
  `backend/app/core/capabilities/hooks.py`
- UI state and surfaces:
  `frontend/src/stores/capability-store.ts`,
  `frontend/src/components/chat/capability-inbox-panel.tsx`,
  `frontend/src/components/settings/capabilities-section.tsx`,
  existing `preview-panel.tsx` and `settings-shell.tsx` at their tab/section
  seams only.
- Browser QA:
  `scripts/qa/capability-layer-suite.cjs`

## Tech Stack

- Backend: FastAPI, SQLAlchemy async, Alembic, PostgreSQL/pgvector, Redis/ARQ
- Agent runtime: existing ReAct loop, tool router, sandbox, SSE stream
- Frontend: Next.js, React, Zustand, current Tailwind/zinc visual system
- Verification: local Docker Desktop, Docker test profile, Windows browser QA
- No host Python or host Node as application runtime

## Baseline / Authority Refs

- `docs/aegis/specs/2026-06-16-v2-capability-operating-layer-design.md`
- `docs/aegis/specs/2026-06-16-auditable-self-evolution-worker-layer-brief.md`
- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `docs/aegis/plans/2026-06-15-w12-file-task-closure-execution-plan.md`
- `AGENTS.md`

## Compatibility Boundary

- Do not redesign or restyle the frontend. Reuse the current dark zinc visual
  language, right panel structure, Settings shell, scroll behavior, sidebar, and
  chat interaction feel.
- Existing V1 and W12 chat, upload, artifact, tool, memory, skill metadata,
  proactive, audit, health, and eval behavior must keep working.
- Capability Candidates must not influence Agent planning before user
  acceptance.
- User-private candidates and accepted capabilities must not affect other users.
- Memory and Skill retrieval must be user-private unless a record is explicitly
  tenant-shared by scope. Tenant-only filters are not sufficient for V2
  accepted capabilities.
- Worker is not a schedule. Proactive tasks can trigger Workers, but must not
  own Worker behavior.
- WorkerVersion activation requires verified status plus user confirmation and
  audit evidence. Draft WorkerVersions cannot become active directly.
- Worker matching must include semantic similarity in phase 1. Keyword/example
  scoring may supplement tests but cannot replace an embedding-backed semantic
  score.
- Tool calls during normal execution and confirmation resume must pass the same
  Worker policy gate when a Worker context is active.
- Worker failure fallback must be visible and must not be reported as Worker
  success.
- Do not add team publishing, marketplace, arbitrary user hooks, or full admin
  Managed Settings in this phase.
- Do not commit unless the user explicitly asks for a commit.

## Plan Review Revision Contract

`/plan-eng-review` and the outside-voice fallback found production-critical
gaps. These decisions are mandatory for implementation:

- Keep full V2 scope; do not reduce to Inbox MVP or split out Worker runtime.
- Add Memory/Skill personal scope migration and cross-user leak tests.
- Lock Candidate public API to `/api/v1/capability-candidates`.
- Make Candidate source, merge, snooze, mute, and Worker/source reference
  fields explicit schema fields, not opaque metadata-only audit state.
- Add durable candidate analysis outbox/ARQ behavior. A stream-tail timeout or
  client disconnect must not silently lose an eligible candidate analysis.
- Add minimal policy facade before executable Worker runtime can run.
- Add Worker recursion and nesting guard with traceable block reasons.
- Require WorkerVersion verification, user confirmation, and audit before
  activation.
- Implement semantic Worker matching with pgvector/embedding-backed scoring and
  fake-embedding tests.
- Unify Worker policy across normal tool execution and confirmation resume.
- Keep `conversation_stream_service.py` as a thin capability facade caller.
- Add browser screenshot/DOM/scroll assertions that prove no frontend style or
  conversation/sidebar behavior regression.

## Verification

Targeted backend suites:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_policy_hooks.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py"
```

Full backend:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
```

Frontend:

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Local runtime:

```powershell
docker-compose up -d --build
curl.exe -fsS http://127.0.0.1/api/v1/health
docker-compose ps
```

Eval:

```powershell
docker-compose exec -T backend python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0
docker-compose exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
docker-compose exec -T backend python scripts/run-eval.py --suite capability_layer --json --min-pass-rate 1.0
```

Browser QA:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost `
  -Browser chrome -Headless `
  -Suite capability-layer `
  -TimeoutMs 180000
```

Expected final state:

- Backend targeted and full tests pass.
- Frontend lint/build pass.
- Eval `basic`, `spec_complete`, and `capability_layer` pass.
- Browser QA `capability-layer` returns `ok: true` and cleanup evidence.
- Browser QA includes style-sensitive evidence for right-panel Inbox, chat
  scroll, sidebar conversation rename/delete/select, and Settings navigation.
- Capability analysis outbox proves timeout does not lose eligible analysis.
- Worker activation proves verified version plus user confirmation/audit.
- Worker policy proves normal tool calls and confirmation resume use the same
  guard.
- No QA-created conversations, candidates, Workers, memories, skills, or
  providers remain after cleanup.
- `PROBLEM_TODO_LIST.md` contains no unresolved V2 item discovered during this
  implementation pass.

## Plan Basis

### Facts

- `backend/app/api/v1/conversations.py` currently owns chat route behavior and
  is 595 lines.
- `backend/app/services/conversation_stream_service.py` owns SSE orchestration,
  confirmations, file workspace setup, and persistence and is 639 lines.
- `backend/app/core/agent/engine.py` owns ReAct execution and is 372 lines.
- `frontend/src/stores/chat-store.ts` is 823 lines and should not absorb V2
  capability management state.
- `frontend/src/stores/platform-store.ts` is 854 lines and already owns many
  settings surfaces.
- `frontend/src/components/chat/preview-panel.tsx` already has tabs for
  Preview, Terminal, Files, and Diff.
- `frontend/src/app/settings/page.tsx` delegates settings content to
  `SettingsShell`.
- Current Skill model is passive metadata with trigger terms.
- Current Memory model already supports tenant, optional user, tags, metadata,
  and embeddings.
- Current Skill model needs V2 personal scope. Existing tenant-wide Skill
  behavior must remain compatible only for explicitly shared or legacy records.
- Current Memory query owners must be audited so accepted private Memories do
  not leak through tenant-only search/list/merge paths.
- W12 added run-scoped artifact/workspace behavior and must remain the file
  source-of-truth boundary.

### Assumptions

- V2 phase 1 should use user-private capabilities, even for admin users.
- Accepted Skill candidates can map to the existing passive Skill model with
  `user_id`/scope and candidate/source metadata; no active Skill execution
  engine is introduced.
- Accepted Memory candidates use the existing Memory model with `user_id` set
  to the current user and source metadata. Memory retrieval must include only
  current-user private records plus explicitly tenant-shared records.
- Candidate generation can run after a chat stream finishes. A lightweight SSE
  event is emitted only when analysis completes within the stream lifecycle;
  otherwise a durable analysis job finishes later and Inbox refresh shows the
  candidate.
- Worker execution reuses the existing Agent engine through a new Worker runtime
  service rather than duplicating ReAct logic.
- Worker matching thresholds begin deterministic/configurable and include an
  embedding-backed semantic score in phase 1. Keyword/example scoring is only a
  supplement for deterministic tests and explainability.

### Unknowns Assigned To Workstreams

- Whether existing settings store should be split. Owner: Workstream 7. Plan
  choice: add `capability-store.ts`, do not grow `platform-store.ts`.
- Whether WorkerRun trace should store full event JSON or references. Owner:
  Workstream 4. Plan choice: bounded JSON summary plus artifact/tool/audit refs.
- How candidate analysis is scheduled. Owner: Workstream 2. Plan choice:
  stream-tail best effort plus durable outbox/ARQ-compatible processing with
  idempotent run-level dedupe and metrics.

## Architecture Integrity Lens

- Invariant: inactive candidates never affect Agent behavior; accepted
  capabilities affect only their owner user.
- Canonical owner / contract:
  - Candidate ownership lives in `core/capabilities` and
    `models/capability.py`.
  - Candidate analysis durability lives in the capability outbox owner.
  - Worker ownership lives in `core/workers` and `models/worker.py`.
  - Memory and Skill remain their existing source-of-truth owners, with V2
    personal scope enforced at model/query boundaries.
  - Agent engine remains the execution loop; Worker runtime composes it.
  - Policy modules enforce minimal hard guard behavior before executable Worker
    runtime in W4; hooks expand lifecycle behavior in W6.
- Responsibility overlap:
  - Do not put candidate lifecycle into `conversations.py`.
  - Do not put Worker definitions into proactive tasks.
  - Do not put capability Settings state into `chat-store.ts`.
  - Do not put executable Skill behavior into the passive Skill model.
  - Do not put candidate analysis retry state into volatile SSE-only flow.
  - Do not put Worker policy only in the first tool-call path while leaving
    confirmation resume as a bypass.
- Higher-level simplification:
  add a Capability Operating Layer above existing Memory, Skill, Worker, tools,
  artifacts, and proactive runtime instead of scattering learning in each owner.
- Retirement / falsifier:
  if an unaccepted candidate changes planning, if a private capability crosses
  user boundaries, if an unverified WorkerVersion becomes active, if a schedule
  owns Worker behavior, or if confirmation resume bypasses Worker policy, the
  implementation fails.
- Verdict: proceed with new owner modules and thin integration seams.

## Plan Pressure Test

- Owner / contract / retirement:
  new persistence, public APIs, SSE events, Worker execution, and UI surfaces
  require a durable plan. Existing owners remain but must not absorb the whole
  feature.
- Architecture integrity / higher-level path:
  the approved design already settled the new owner boundary. This plan keeps
  that boundary and avoids large refactors.
- Verification scope:
  backend contract tests, integration tests, frontend lint/build, eval, Windows
  browser QA, and cleanup are all required.
- Task executability:
  workstreams are ordered by dependency: schema/API, candidate pipeline,
  acceptance, Worker runtime, Agent integration, guards/hooks, UI, QA, final
  evidence.
- Pressure result: proceed.

## Plan-Time Complexity Check

- Target files:
  `conversations.py`, `conversation_stream_service.py`, `engine.py`,
  `chat-store.ts`, `platform-store.ts`, `preview-panel.tsx`,
  `settings-shell.tsx`, `settings/page.tsx`
- Existing size / shape signals:
  both frontend stores exceed 800 lines; stream service already mixes SSE,
  confirmation, workspace, and persistence concerns.
- Owner fit:
  new capability and Worker logic needs dedicated backend owners and a separate
  frontend capability store.
- Add-in-place risk:
  adding V2 state directly into chat/platform stores or stream service would
  make later debugging and rollback difficult.
- Better file boundary:
  create `backend/app/core/capabilities/`, `backend/app/core/workers/`,
  `frontend/src/stores/capability-store.ts`, and focused UI components.
- Stream-service boundary:
  `conversation_stream_service.py` may call capability facade functions only:
  enqueue/analyze run, retrieve context, emit capability events, and pass
  Worker context into the Agent. It must not own candidate persistence,
  matching, policy, or hook logic.
- Recommendation: add owner files; edit existing high-pressure files only at
  API registration, SSE event, prompt integration, and UI tab/section seams.

## Files

Create:

- `backend/app/models/capability.py`
- `backend/app/models/worker.py`
- `backend/alembic/versions/<revision>_add_capability_layer.py`
- `backend/app/core/capabilities/__init__.py`
- `backend/app/core/capabilities/schemas.py`
- `backend/app/core/capabilities/service.py`
- `backend/app/core/capabilities/rules.py`
- `backend/app/core/capabilities/analyzer.py`
- `backend/app/core/capabilities/outbox.py`
- `backend/app/core/capabilities/retrieval.py`
- `backend/app/core/capabilities/policy.py`
- `backend/app/core/capabilities/hooks.py`
- `backend/app/core/workers/__init__.py`
- `backend/app/core/workers/matcher.py`
- `backend/app/core/workers/runtime.py`
- `backend/app/core/workers/service.py`
- `backend/app/api/v1/capabilities.py`
- `backend/app/api/v1/workers.py`
- `backend/tests/test_capability_candidates.py`
- `backend/tests/test_capability_acceptance.py`
- `backend/tests/test_capability_planning.py`
- `backend/tests/test_worker_runtime.py`
- `backend/tests/test_capability_policy_hooks.py`
- `backend/tests/eval/tasks/capability_layer.json`
- `frontend/src/stores/capability-store.ts`
- `frontend/src/components/chat/capability-inbox-panel.tsx`
- `frontend/src/components/chat/capability-hint-card.tsx`
- `frontend/src/components/chat/worker-run-card.tsx`
- `frontend/src/components/settings/capabilities-section.tsx`
- `frontend/src/components/settings/workers-section.tsx`
- `scripts/qa/capability-layer-suite.cjs`

Modify:

- `backend/app/models/__init__.py`
- `backend/app/api/v1/router.py`
- `backend/app/api/v1/conversations.py`
- `backend/app/api/v1/memories.py`
- `backend/app/api/v1/skills.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/prompt_builder.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/agent/tool_router.py`
- `backend/app/models/skill.py`
- `backend/app/models/memory.py`
- `backend/app/core/proactive/scheduler.py`
- `backend/scripts/run-eval.py`
- `frontend/src/lib/api.ts`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/components/chat/preview-panel.tsx`
- `frontend/src/components/settings/settings-shell.tsx`
- `scripts/windows-browser-qa.cjs`
- `scripts/windows-browser-qa.ps1`
- `PROBLEM_TODO_LIST.md`
- `docs/aegis/plans/2026-06-17-v2-capability-operating-layer-execution-plan.md`

Do not modify:

- Frontend global style/theme files unless a compile error proves a typed export
  is required.
- Existing sidebar visual design.
- Existing chat layout classes except small tab/button insertion seams.

## Execution Rules

1. Use local Docker Desktop only.
2. Use Windows only for browser QA/control plane.
3. Do not rely on host Python or host Node for app runtime.
4. Do not commit unless the user explicitly asks for a commit.
5. Do not change frontend style or visual language.
6. One workstream closes only when every listed verification command passes.
7. Any issue found during a workstream must be recorded in
   `PROBLEM_TODO_LIST.md`, fixed, and reverified before that workstream closes.
8. QA-created data must be cleaned by ID or unique test prefix.
9. Worker and candidate test data must never be created in another user's scope
   unless the test is explicitly verifying isolation.
10. If a new owner or contract not covered by this plan becomes necessary,
    pause and return to design review.

---

## Workstream 1: Persistence, Models, and API Contract Skeleton

### Goal

Introduce durable personal Capability Candidate and Worker owners without
making them affect Agent behavior.

### Files

- Create: `backend/app/models/capability.py`
- Create: `backend/app/models/worker.py`
- Create: `backend/alembic/versions/<revision>_add_capability_layer.py`
- Create: `backend/app/api/v1/capabilities.py`
- Create: `backend/app/api/v1/workers.py`
- Create: `backend/app/core/capabilities/schemas.py`
- Create: `backend/app/core/capabilities/service.py`
- Create: `backend/app/core/capabilities/outbox.py`
- Create: `backend/app/core/workers/service.py`
- Create: `backend/tests/test_capability_candidates.py`
- Create: `backend/tests/test_worker_runtime.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/skill.py`
- Modify: `backend/app/api/v1/router.py`

### Contract

Candidate statuses:

```text
new, seen, accepted, edited_accepted, dismissed, snoozed, muted_pattern, merged, archived
```

Candidate types:

```text
memory, skill, worker
```

Worker statuses:

```text
draft, active, disabled, soft_deleted
```

WorkerVersion statuses:

```text
draft, verified, active, archived, failed_verification
```

WorkerRun statuses:

```text
succeeded, failed, failed_fallback_succeeded, failed_fallback_failed,
blocked_by_policy, cancelled, needs_user_confirmation
```

Candidate analysis job statuses:

```text
pending, running, succeeded, failed, skipped_duplicate
```

Public route contract:

```text
GET    /api/v1/capability-candidates
GET    /api/v1/capability-candidates/{candidate_id}
POST   /api/v1/capability-candidates/{candidate_id}/accept
POST   /api/v1/capability-candidates/{candidate_id}/dismiss
POST   /api/v1/capability-candidates/{candidate_id}/snooze
POST   /api/v1/capability-candidates/{candidate_id}/archive
POST   /api/v1/capability-candidates/{candidate_id}/mute-pattern
POST   /api/v1/capability-candidates/{candidate_id}/merge
```

### Tasks

1. Write RED tests in `backend/tests/test_capability_candidates.py` for create,
   list, get, status transition, personal user isolation, tenant isolation,
   exact `/api/v1/capability-candidates` route contract, required-field
   serialization, dedupe key merge lookup, and inactive candidates not returned
   by capability retrieval.
2. Write RED tests in `backend/tests/test_worker_runtime.py` for Worker draft,
   version draft, blocked draft activation, verify-before-activate,
   activation confirmation/audit, disable, enable, soft delete, version
   rollback, and user/tenant isolation.
3. Write RED tests for Skill personal scope migration:
   - existing tenant-wide Skill rows remain available as explicit shared/legacy
     records
   - accepted Skill rows require `user_id`
   - scoped uniqueness permits the same Skill name for two users while
     preventing duplicates in one user's scope
4. Write RED tests for candidate analysis outbox records:
   - one eligible run creates one pending analysis job
   - repeated enqueue for the same run is idempotent
   - failed analysis records bounded error metadata without creating active
     capability behavior
5. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py"
   ```

   Expected: failures are missing models/routes/services only.

6. Implement models and migration:
   - `CapabilityCandidate`
   - `CapabilityAnalysisJob`
   - `Worker`
   - `WorkerVersion`
   - `WorkerRun`
   - `WorkerMatchFeedback`
   - Skill `user_id` and `scope`
   Use UUID primary keys, `tenant_id`, `user_id`, timestamps, explicit
   Candidate source/merge/snooze/mute/worker reference columns, JSONB only for
   bounded extensibility, indexes for `(tenant_id, user_id, status)`,
   `(tenant_id, user_id, dedupe_key)`, `(tenant_id, user_id, source_run_id)`,
   `(tenant_id, user_id, enabled, soft_deleted_at)`, and Skill scoped
   uniqueness.
7. Implement thin CRUD/service layer with no Agent behavior:
   - candidate create/list/get/transition/merge/mute/archive
   - candidate analysis job enqueue/claim/complete/fail with run-level
     idempotency
   - Worker create/list/get/update/verify-version/request-activation/
     activate-after-confirmation/disable/enable/soft-delete/rollback
   - all write paths require current `tenant_id` and `user_id`
8. Add routers to `backend/app/api/v1/router.py`.
9. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py"
   ```

   Expected: all tests pass.

10. Run contract regression:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py"
   ```

   Expected: all tests pass.

11. Update `PROBLEM_TODO_LIST.md` only if W1 finds new issues.
12. Checkpoint diff. Do not commit.

### Stop Condition

The database and REST skeleton exist, are tenant/user isolated, have exact
Candidate API paths, explicit audit/source fields, durable analysis jobs,
verified Worker activation gates, scoped Skills, and cannot affect Agent
planning.

---

## Workstream 2: Rule-First Candidate Generation Pipeline

### Goal

Generate inactive Memory/Skill/Worker candidates after useful chat runs through
a deterministic rule filter plus LLM analyzer, while controlling noise and cost.

### Files

- Create: `backend/app/core/capabilities/rules.py`
- Create: `backend/app/core/capabilities/analyzer.py`
- Create: `backend/app/core/capabilities/outbox.py`
- Modify: `backend/app/core/capabilities/service.py`
- Modify: `backend/app/services/conversation_stream_service.py`
- Modify: `backend/app/api/v1/conversations.py`
- Modify: `backend/tests/test_capability_candidates.py`

### Design Choices

- Rule filter runs synchronously after a chat run has enough evidence.
- An eligible run is written to the durable candidate analysis outbox before
  stream-tail analysis is attempted.
- LLM analyzer is called best-effort at stream tail with a bounded timeout. If
  it finishes in time, the job is completed immediately.
- If analyzer does not finish during stream, an ARQ-compatible background
  function must claim the pending outbox job and persist candidates later.
- Analyzer timeout, duplicate enqueue, and failure counters must be observable
  through bounded metrics/log evidence.
- Candidate SSE event name: `capability_candidate`.
- Candidate SSE event never means active capability.

### Tasks

1. Write RED tests for `rules.should_analyze_run(...)` covering:
   - "remember/next time/always" text signal
   - tool-chain signal
   - artifact signal
   - user correction signal
   - fallback signal
   - pure greeting non-trigger
2. Write RED tests for analyzer parsing with a fake gateway returning valid
   JSON for one Memory, one Skill, and one Worker candidate.
3. Write RED stream test proving a completed chat run with "next time" text
   persists an inactive candidate and emits `capability_candidate` when analyzer
   returns before timeout.
4. Write RED outbox tests proving:
   - analyzer timeout does not block `done`
   - timeout leaves a pending analysis job
   - background processing later persists the candidate
   - duplicate processing of one run is idempotent
   - analyzer failure records bounded error metadata and increments metrics
5. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py"
   ```

6. Implement `rules.py` with deterministic signal extraction and a
   `RunAnalysisSignal` dataclass.
7. Implement `analyzer.py` with:
   - strict JSON parsing
   - allowed candidate types only
   - confidence clamped to `0.0..1.0`
   - `source_evidence` length/size bounds
   - fallback to no candidate on invalid analyzer output
8. Implement `outbox.py` with:
   - `enqueue_run_analysis(...)`
   - `claim_pending_analysis(...)`
   - `complete_analysis(...)`
   - `fail_analysis(...)`
   - run-level idempotency and bounded retry metadata
9. Extend candidate service with dedupe/merge behavior:
   - same `(tenant_id, user_id, candidate_type, dedupe_key)` and active Inbox
     state updates existing candidate evidence instead of creating spam
   - dismissed/muted pattern prevents chat hint repeat
10. Integrate stream-tail generation in `conversation_stream_service.py` after
    assistant message persistence through a capability facade only:
    - enqueue durable analysis job
    - attempt bounded stream-tail analysis
    - emit `capability_candidate` only if a candidate is ready before stream end
    - never place candidate persistence or analyzer parsing logic directly in
      the stream service
11. Add ARQ-compatible background processor entrypoint for pending analysis
    jobs. It may be invoked by tests directly in phase 1, but the code path
    must be queue-safe and idempotent.
12. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py"
   ```

13. Update `PROBLEM_TODO_LIST.md` for discovered issues and checkpoint diff.
    Do not commit.

### Stop Condition

Useful runs create durable, idempotent analysis jobs; completed analysis creates
inactive, deduped personal candidates and optionally emits a lightweight SSE
hint. Pure chat noise does not create candidates, and analyzer timeout does not
silently lose eligible work.

---

## Workstream 3: Candidate Acceptance Into Memory, Skill, and Worker

### Goal

Make candidate acceptance create real private Memory, Skill, or Worker drafts
without bypassing review, ownership, or scope boundaries.

### Files

- Modify: `backend/app/api/v1/capabilities.py`
- Modify: `backend/app/core/capabilities/service.py`
- Modify: `backend/app/core/workers/service.py`
- Modify: `backend/app/api/v1/memories.py`
- Modify: `backend/app/api/v1/skills.py`
- Modify: `backend/tests/test_capability_acceptance.py`
- Modify: `backend/tests/test_memory_source_contract.py`
- Modify: `backend/tests/test_skill_trigger_matching.py`

### Tasks

1. Write RED tests:
   - accepting Memory candidate creates Memory with `user_id` and source
     metadata
   - accepting Skill candidate creates passive Skill with source metadata and
     trigger terms, `user_id`, and private scope
   - accepting Worker candidate creates Worker draft and WorkerVersion draft,
     not active Worker
   - accepting Worker improvement creates new WorkerVersion draft, not overwrite
   - accepting someone else's candidate returns 404 or authorization error
   - accepting archived/dismissed candidate is rejected with unified error
   - Memory list/search/merge for accepted private Memory does not return data
     to another user in the same tenant
   - Skill trigger matching for accepted private Skill does not return data to
     another user in the same tenant
   - legacy tenant-wide Skills remain available only as explicit shared/legacy
     scope records
2. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_acceptance.py"
   ```

3. Implement `accept_candidate(...)` routing:
   - `memory` -> existing memory service with current `user_id`, source
     metadata, and private retrieval semantics
   - `skill` -> existing passive skill model with `user_id`, private scope,
     candidate metadata, and trigger terms
   - `worker` -> Worker draft + WorkerVersion draft
4. Ensure accepted candidate status changes to `accepted` or
   `edited_accepted` and stores target resource IDs.
5. Update Memory and Skill API/query owners so private accepted capabilities are
   returned only for the current user plus explicitly shared scope. Tenant-only
   filtering fails the workstream.
6. Add optional edited proposal body support with strict schema and size bounds.
7. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_acceptance.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py"
   ```

8. Run API contract regression:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_api_contracts.py"
   ```

9. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
   commit.

### Stop Condition

Candidates can become active private Memory/Skill or inactive Worker drafts
only through explicit acceptance, and accepted private Memory/Skill cannot leak
across users in the same tenant.

---

## Workstream 4: Worker Runtime, Matching, Versions, Fallback, and Feedback

### Goal

Make accepted Workers Agent-callable executable capabilities with match scoring,
versions, runs, failure fallback, match feedback, soft delete, and rollback.

### Files

- Create: `backend/app/core/workers/matcher.py`
- Create: `backend/app/core/workers/runtime.py`
- Create or extend: `backend/app/core/capabilities/policy.py`
- Modify: `backend/app/core/workers/service.py`
- Modify: `backend/app/api/v1/workers.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `backend/app/core/agent/tool_router.py`
- Modify: `backend/tests/test_worker_runtime.py`

### Runtime Contract

Worker runtime reuses existing Agent execution. It must not duplicate ReAct.
Worker runtime prepares a Worker-specific system/context wrapper, validates
policy, calls `run_agent(...)`, records WorkerRun, and returns events to the
caller.

W4 may introduce only the minimal policy facade required to prevent unguarded
execution. W6 expands hooks and richer guard behavior, but W4 must already
enforce activation, input schema, allowed tools, risk decision, recursion, and
confirmation-resume policy.

### Tasks

1. Write RED tests:
   - high semantic match but missing required input does not auto-invoke
   - high match, input fit, low risk returns match decision `auto_notice`
   - medium match returns `skip_and_suggest_after`
   - high risk match returns `needs_confirmation`
   - disabled/soft-deleted Worker is never matched
   - draft or unverified WorkerVersion cannot activate or run
   - activation requires verified version, user confirmation, and audit record
   - same Worker cannot recursively invoke itself
   - nested Worker invocation beyond the configured max depth is blocked with a
     traceable reason
   - semantic match works for same-meaning/different-wording tasks using fake
     embeddings; keyword-only overlap is not sufficient
   - normal tool execution and confirmation resume both reject a Worker
     disallowed tool
   - WorkerRun records `matched_request`, `match_score`, status, tool trace,
     fallback fields, and timestamps
   - Worker failure safe fallback produces `failed_fallback_succeeded`
   - failure lowers match feedback and creates improvement candidate
   - success raises confidence but does not create candidate without feedback
   - rollback reactivates prior version
2. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_worker_runtime.py"
   ```

3. Implement `matcher.py`:
   - embedding-backed semantic score using existing Memory/pgvector patterns
   - deterministic fake-embedding hook for tests
   - keyword/example scoring only as a supplemental signal
   - input schema fit
   - precondition fit
   - success/failure/feedback score modifiers
   - risk penalty
4. Implement `runtime.py`:
   - `execute_worker_run(...)`
   - bounded trace capture
   - calls existing `run_agent(...)`
   - passes `worker_run_id`, active WorkerVersion, recursion depth, and
     allowed tool context into the Agent/tool path
   - blocks same-Worker reentry and configured max-depth overflow
   - maps status values
   - writes WorkerRun records
   - handles safe fallback to normal Agent execution
5. Implement minimal `policy.py` facade used by W4:
   - `allow`, `confirm`, `block` decisions
   - input schema validation
   - Worker allowed-tool enforcement
   - risk confirmation decision
   - confirmation-resume validation using persisted Worker context
6. Implement Worker API endpoints for versions, verification, activation
   request, activation after confirmation, rollback, runs, feedback, enable,
   disable, and soft delete.
7. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_worker_runtime.py tests/test_agent_runtime_limits.py"
   ```

8. Run full backend subset that exercises tool authorization:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_proactive_authorization.py tests/test_tool_cancellation.py tests/test_artifacts.py"
   ```

9. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
   commit.

### Stop Condition

Workers are real executable capabilities with semantic match scoring, verified
activation, policy-guarded tool execution including confirmation resume,
recursion protection, versioned contracts, run records, fallback transparency,
feedback, disable, soft delete, and rollback.

---

## Workstream 5: Agent Soft Merge and Capability Retrieval

### Goal

Let Agent planning combine accepted Memory, Skill, and Worker while ensuring
inactive candidates never influence behavior.

### Files

- Create: `backend/app/core/capabilities/retrieval.py`
- Modify: `backend/app/core/agent/prompt_builder.py`
- Modify: `backend/app/services/conversation_stream_service.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `backend/tests/test_capability_acceptance.py`
- Modify: `backend/tests/test_memory_source_contract.py`
- Modify: `backend/tests/test_skill_trigger_matching.py`
- Create: `backend/tests/test_capability_planning.py`

### Soft Merge Contract

Planning context contains separate sections:

```text
Current user request
Relevant private memories
Relevant private skills
Matched worker candidates
Hard guard summary
```

It must not blend these into one untraceable prompt paragraph.

### Tasks

1. Write RED tests:
   - accepted Memory appears in merged planning context with source
   - accepted Skill appears as method guidance
   - active Worker appears as matchable executable capability
   - inactive candidate does not appear
   - user A capability does not appear for user B
   - user A private Memory does not appear for user B
   - user A private Skill does not appear for user B
   - explicit tenant-shared legacy Skill remains visible according to scope
   - current user instruction can override Memory preference in generated plan
     text while hard guard summary remains non-overridable
2. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_planning.py"
   ```

3. Implement `retrieval.py` with:
   - `get_capability_context(db, tenant_id, user_id, task_text)`
   - Memory retrieval using existing memory service with user-private plus
     explicitly shared scope only
   - Skill trigger match using existing skill logic with user-private plus
     explicitly shared scope only
   - Worker matching using semantic `matcher.py`
   - bounded context budgets and explicit source records
4. Extend `prompt_builder.py` to add capability sections without removing
   existing memory/layered instruction behavior.
5. Extend stream service to call only the capability retrieval facade and pass
   user/tenant into it. Do not put retrieval, matching, or policy internals in
   `conversation_stream_service.py`.
6. Extend agent events with Worker notice events when a low-risk Worker is
   selected.
7. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py"
   ```

8. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
   commit.

### Stop Condition

Agent context supports Claude Code-style soft merge for accepted private
capabilities, Memory/Skill/Worker retrieval is user-scoped, semantic Worker
matches are source-traced, and unaccepted candidates remain behaviorally inert.

---

## Workstream 6: Minimal Hard Guards and Internal Hooks

### Goal

Enforce runtime safety with policy guards and lifecycle hooks so model reasoning
cannot bypass permissions, risk gates, schema, allowed tools, or audit.

### Files

- Create: `backend/app/core/capabilities/policy.py`
- Create: `backend/app/core/capabilities/hooks.py`
- Modify: `backend/app/core/workers/runtime.py`
- Modify: `backend/app/core/workers/matcher.py`
- Modify: `backend/app/services/conversation_stream_service.py`
- Modify: `backend/app/core/agent/tool_router.py`
- Modify: `backend/app/api/v1/conversations.py`
- Create: `backend/tests/test_capability_policy_hooks.py`

### Guard Contract

Hard guards:

- tenant isolation
- user-private capability isolation
- Worker input schema validation
- Worker precondition validation
- Worker allowed tool enforcement
- tool risk-level enforcement
- external delivery confirmation
- destructive action confirmation
- Worker delete/disable confirmation
- fallback transparency
- WorkerRun trace/audit recording
- Worker recursion/nesting guard
- confirmation-resume policy parity

Hook points:

```text
before_worker_match
before_worker_run
after_worker_run
before_tool_call
after_tool_call
on_worker_failure
on_capability_candidate_created
```

### Tasks

1. Write RED tests:
   - Worker with disallowed tool is blocked before tool execution
   - missing input schema blocks WorkerRun
   - external delivery Worker requires confirmation
   - destructive Worker requires confirmation
   - confirmation resume for a Worker-run destructive or disallowed tool passes
     the same policy gate as the original tool call
   - Worker context persists `worker_run_id`, allowed tools, risk decision, and
     confirmation context without secrets
   - same-Worker recursion and max-depth overflow are blocked
   - hook records before/after run calls
   - hook cannot override denied policy decision
   - failure hook creates improvement candidate
   - fallback notice event is emitted
2. Verify RED:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_policy_hooks.py"
   ```

3. Expand the W4 `policy.py` facade with pure decision functions returning
   typed decisions: `allow`, `confirm`, `block`.
4. Implement `hooks.py` as internal async dispatcher with named hook events and
   bounded payloads. Do not allow user-authored code.
5. Wire policy guard into Worker matching, Worker runtime, normal tool call
   path, and confirmation resume path.
6. Ensure blocked or confirmation-required WorkerRun records are persisted with
   safe messages and no secrets.
7. Verify GREEN:

   ```powershell
   docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py"
   ```

8. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
   commit.

### Stop Condition

All Worker and capability execution paths pass through explicit guard and hook
points, and denied decisions cannot be overridden by prompts or hooks.

---

## Workstream 7: Frontend Capability Inbox and Worker Management UI

### Goal

Expose lightweight chat-side learning feedback and full Settings management
without changing Chainless visual style.

### Files

- Create: `frontend/src/stores/capability-store.ts`
- Create: `frontend/src/components/chat/capability-inbox-panel.tsx`
- Create: `frontend/src/components/chat/capability-hint-card.tsx`
- Create: `frontend/src/components/chat/worker-run-card.tsx`
- Create: `frontend/src/components/settings/capabilities-section.tsx`
- Create: `frontend/src/components/settings/workers-section.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/stores/chat-store.ts`
- Modify: `frontend/src/components/chat/preview-panel.tsx`
- Modify: `frontend/src/components/settings/settings-shell.tsx`

### UI Boundary

- Right panel adds an Inbox tab next to existing tabs.
- Settings adds personal capability sections.
- Reuse existing card/button/input classes and spacing.
- Do not alter global styles, sidebar, chat scroll, or layout feel.
- Browser QA must capture before/after-sensitive evidence for right panel,
  chat scroll, sidebar conversation actions, and Settings navigation. Passing
  lint/build is not enough to claim no style regression.

### Tasks

1. Add API client types and functions for:
   - candidate list/get/accept/dismiss/archive/snooze/mute/merge
   - worker list/get/enable/disable/delete/rollback/runs
   - worker run feedback
2. Add `capability-store.ts` with bounded state:
   - `candidatesByStatus`
   - `workers`
   - `workerRuns`
   - loading/error states
   - actions mapped to API client
3. Extend `chat-store.ts` only at SSE parsing seams:
   - store `capability_candidate` events
   - store `worker_notice` and `worker_fallback` events
   - do not move capability management into chat store
4. Add `CapabilityInboxPanel` using existing right-panel visual language.
5. Modify `PreviewPanel` tab list to include `Inbox`; preserve current sizing,
   border, colors, overflow, and tab behavior.
6. Add `CapabilityHintCard` and `WorkerRunCard` using existing card/button
   classes only.
7. Add Settings sections for Inbox and Workers using the existing
   `SettingsShell` section pattern.
8. Add stable selectors or test IDs only where needed for QA assertions. Do not
   change visual classes to satisfy tests.
9. Run frontend verification:

   ```powershell
   docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
   ```

   Expected: lint and build pass.

10. Run style-sensitive browser smoke after Workstream 8 registers QA:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
     -Url http://localhost `
     -Browser chrome -Headless `
     -Suite capability-layer `
     -TimeoutMs 180000
   ```

    Expected: report includes screenshots or DOM evidence for right panel Inbox,
    chat scroll movement, sidebar delete/rename/selection behavior, and
    Settings capability sections.

11. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
    commit.

### Stop Condition

Users can see and act on candidates in chat and Settings, manage Workers, and
the frontend passes lint/build with browser evidence that style, scroll,
sidebar conversation actions, and Settings navigation did not regress.

---

## Workstream 8: Eval, Browser QA, and Cleanup

### Goal

Prove the full Capability Operating Layer in deterministic backend eval and
real browser QA with cleanup.

### Files

- Create: `backend/tests/eval/tasks/capability_layer.json`
- Modify: `backend/scripts/run-eval.py`
- Create: `scripts/qa/capability-layer-suite.cjs`
- Modify: `scripts/windows-browser-qa.cjs`
- Modify: `scripts/windows-browser-qa.ps1`
- Modify: `PROBLEM_TODO_LIST.md`

### Browser QA Coverage

The suite must cover:

- login
- create conversation
- chat task that triggers Memory candidate
- chat task that triggers Skill candidate
- chat task that triggers Worker candidate
- right panel Inbox tab shows candidates
- accept Memory and verify later recall behavior
- accept Skill and verify later method behavior
- accept Worker candidate into draft, verify the WorkerVersion, confirm
  activation, and verify Agent auto-match with visible Worker notice
- verify Worker activation requires verified version plus user confirmation and
  audit evidence
- Worker failure fallback shows transparent notice and creates improvement
  candidate
- Worker semantic match works on same-meaning/different-wording request
- Worker disallowed tool is denied both before confirmation and after
  confirmation resume
- natural-language "delete X Worker" creates a confirmation flow and does not
  soft delete until confirmed
- disable Worker and verify no auto-match
- soft delete Worker with confirmation
- Settings capability page lists candidates and Workers
- screenshots or DOM evidence prove right-panel styling, chat scroll, sidebar
  conversation rename/delete/select, and Settings navigation still work
- cleanup all created conversations, candidates, workers, memories, skills, and
  providers

### Tasks

1. Add deterministic eval tasks:
   - candidate rule trigger
   - Memory acceptance/retrieval
   - Skill acceptance/method use
   - Worker match/invocation
   - Worker failure fallback
   - Worker semantic match through fake embeddings
   - Worker verify-before-activate
   - Worker recursion guard
   - confirmation-resume policy denial
   - candidate analysis outbox timeout and eventual persistence
   - Memory/Skill personal scope isolation
   - private user isolation
   - inactive candidate inertness
   - policy guard denial
2. Extend eval runner only where necessary to support capability assertions.
3. Add browser suite with unique prefix
   `qa-v2-capability-<timestamp>` and `finally` cleanup.
4. Add browser style-regression assertions:
   - capture right-panel Inbox screenshot/DOM class evidence
   - prove chat scroll wheel/scrollbar movement still works
   - prove sidebar conversation rename/delete/select still works
   - prove Settings conversation click returns to `/chat`
   - prove Settings capability sections use existing shell/button/card patterns
5. Register `capability-layer` suite in JS and PowerShell launcher.
6. Run eval:

   ```powershell
   docker-compose exec -T backend python scripts/run-eval.py --suite capability_layer --json --min-pass-rate 1.0
   ```

7. Run browser QA:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
     -Url http://localhost `
     -Browser chrome -Headless `
     -Suite capability-layer `
     -TimeoutMs 180000
   ```

8. If cleanup fails, fix cleanup before closing W8.
9. Update `PROBLEM_TODO_LIST.md` for findings and checkpoint diff. Do not
   commit.

### Stop Condition

Deterministic eval and browser QA prove the V2 loop end to end, style-sensitive
UI behavior did not regress, and all QA data is cleaned.

---

## Workstream 9: Final Verification, Documentation, and ADR Signals

### Goal

Close V2 Capability Operating Layer with full verification evidence, no open
problem-list items, and preserved ADR/baseline signals.

### Files

- Modify: `PROBLEM_TODO_LIST.md`
- Modify: this plan with evidence results
- Create ADR only if the user explicitly approves ADR backfill after
  implementation

### Final Verification Commands

```powershell
docker compose -p chainless up -d --build
curl.exe -fsS http://127.0.0.1/api/v1/health
docker compose -p chainless ps
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_policy_hooks.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py"
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
docker run --rm -e NEXT_PUBLIC_API_URL='' -v '<worktree>\frontend\src:/app/src' chainless-frontend-test:latest sh -lc "npm run lint && npm run build"
docker compose -p chainless exec -T backend python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0
docker compose -p chainless exec -T backend python scripts/run-eval.py --suite spec_complete --json --min-pass-rate 1.0
docker compose -p chainless exec -T backend python scripts/run-eval.py --suite capability_layer --json --min-pass-rate 1.0
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost `
  -Browser chrome -Headless `
  -Suite capability-layer `
  -TimeoutMs 180000
docker run --rm --network chainless_data --add-host "db:<chainless-db-ip>" --add-host "redis:<chainless-redis-ip>" -e DATABASE_URL='<local-db-url>' -e REDIS_URL='redis://redis:6379/0' -e SECRET_KEY='<local-secret>' -e SECRET_ENCRYPTION_KEY='<local-secret-encryption-key>' -e PYTHONPATH='/repo/backend' -v '<worktree>:/repo' -w /repo/backend chainless-backend:latest python scripts/cleanup_qa_prefix.py --prefix <browser-qa-prefix>
```

Expected:

- All commands exit successfully.
- Browser report has `ok: true`.
- Browser report includes screenshots/DOM evidence for no style, scroll,
  sidebar, or Settings navigation regression.
- No unresolved V2 items remain in `PROBLEM_TODO_LIST.md`.
- QA cleanup proves no V2 test records remain.
- No frontend style redesign appears in diff.
- No commits are created unless explicitly requested.

### ADR Signals To Preserve

After implementation proves the boundary, ask the user whether to create ADRs
for:

- Capability Candidate vs active Memory/Skill/Worker ownership.
- Worker as Agent-callable executable capability.
- Claude Code-style soft merge plus hard guard conflict model.
- Personal-only capability scope and future team publishing path.

### Stop Condition

V2 phase 1 is implemented and verified only when every final verification
command passes, browser QA cleans up, and the problem ledger has no unresolved
V2 item.

### W9 Evidence Addendum

W9 final verification on 2026-06-19:

- Full backend regression returned `427 passed, 4 skipped, 1 warning`.
- Frontend lint/build passed through the mounted `chainless-frontend-test`
  worktree-safe path.
- Local Docker runtime rebuilt with `docker compose -p chainless up -d
  --build`; health returned `{"status":"ok"}`.
- Alembic current/head both returned `0011 (head)`.
- Eval passed at 100%: `basic 10/10`, `spec_complete 4/4`,
  `capability_layer 13/13`.
- Windows Chrome `capability-layer` browser QA returned `"ok": true` at
  `.gstack/qa-reports/local/capability-layer-2026-06-19T05-02-06-546Z`.
- QA prefix cleanup removed all tracked records for
  `qa-v2-capability-1781845326782`: before `analysis_jobs=3`,
  `candidates=5`, `conversations=1`, `workers=4`; after all tracked
  categories `0`.
- `PROBLEM_TODO_LIST.md` V2 W1-W9 items are closed; no unresolved V2 `[ ]`
  remains for this phase.

## Risks

- Candidate generation can create noise. Mitigation: rule-first filter, dedupe,
  muted patterns, no pure-success suggestions, durable outbox idempotency, and
  bounded analyzer metrics.
- Worker auto-invocation can erode trust. Mitigation: visible Worker notices,
  verified activation, hard guards, confirmation gates, recursion guard, and
  fallback transparency.
- Worker runtime can duplicate Agent engine logic. Mitigation: Worker runtime
  wraps existing `run_agent(...)` instead of copying ReAct.
- Personal capability isolation can leak if tenant-only filters are reused.
  Mitigation: every candidate, Worker, Memory, Skill, and match query filters
  by both `tenant_id` and `user_id` unless scope is explicitly shared.
- Worker confirmation resume can bypass policy if it uses a separate tool path.
  Mitigation: normal tool execution and confirmation resume both call the same
  Worker policy gate with persisted Worker context.
- Worker matching can become keyword-only if semantic scoring is deferred.
  Mitigation: phase 1 requires embedding-backed semantic score and
  fake-embedding tests.
- Frontend stores are already large. Mitigation: add `capability-store.ts` and
  keep chat/platform store edits at event/section seams.
- Browser QA can leave persistent capability data or miss style regressions.
  Mitigation: unique prefixes, cleanup registry, final cleanup assertions, and
  screenshot/DOM/scroll evidence.
- Fallback success can hide Worker failure. Mitigation: explicit
  `failed_fallback_succeeded` status and user-visible fallback notice.

## Rollback Surface

- Disable candidate generation integration in `conversation_stream_service.py`
  while keeping APIs/models/outbox records intact. Pending outbox jobs can be
  paused, not deleted, unless explicitly approved.
- Hide the Inbox tab if frontend QA finds a blocking visual regression, while
  retaining Settings management for debugging.
- Disable Worker auto-match by setting match thresholds above 1.0 or checking a
  feature flag, while retaining manual Worker test runs.
- Disable Worker activation if verification/confirmation/audit evidence is not
  passing; do not allow direct draft activation as rollback.
- Keep inactive candidates inert; no rollback should delete user data unless
  explicitly approved.
- Soft-deleted Workers preserve run history, making restore possible during
  debugging.

## Retirement

- Retire the narrower "Worker equals manual/scheduled reusable job" framing as
  the primary V2 product definition. The Worker brief remains as historical
  sub-direction evidence.
- Retire chat-only memory of brainstorming decisions by preserving this plan and
  the V2 design spec under `docs/aegis/`.
- Do not retire existing Memory, Skill, proactive, or artifact APIs.
- Do not retire direct proactive tasks in phase 1; Worker-triggered schedules
  are additive until a later migration plan exists.

## Completion Authority

This plan does not authorize a completion claim by itself. Completion requires
fresh evidence from Workstream 9 and an Aegis verification closeout against the
approved V2 design spec.

## Execution Choice

Recommended execution mode: Subagent-Driven.

Reason: V2 has separable backend persistence, candidate pipeline, Worker
runtime, policy/hooks, frontend UI, and QA slices. Use one fresh subagent per
workstream where possible, review between slices, and release subagents after
their workstream.

Inline execution is acceptable if subagent capacity is unavailable, but the same
stop condition applies: no tail items, no frontend style drift, no host runtime,
and no commit without explicit user approval.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | not requested for this revision |
| Codex Review | outside voice fallback | Independent 2nd opinion | 1 | incorporated | `codex.exe` denied by Windows; read-only subagent found Memory/Skill scope, Worker activation, policy, outbox, semantic matching, API, schema, NLP delete, and style QA gaps |
| Eng Review | `/plan-eng-review` | Architecture & tests | 1 | clear after revision | full V2 scope kept; 10 review decisions incorporated into owner boundaries, workstreams, tests, risks, rollback, and verification |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run | UI scope is additive; style-regression QA is now mandatory before implementation closeout |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | not requested for this revision |

- **UNRESOLVED:** none in the plan review decisions.
- **VERDICT:** Eng review revisions incorporated; ready to execute only under the updated stop conditions in this plan.
