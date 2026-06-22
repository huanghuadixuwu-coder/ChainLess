# Chainless V3 Capability Acquisition Layer Execution Plan

Status: Ready for implementation after plan-eng-review revision patch
Type: V3 Implementation Plan
Created: 2026-06-22
Approved Spec: `docs/aegis/specs/2026-06-20-v3-capability-acquisition-layer-design.md`
Plan Review: `/plan-eng-review` completed on 2026-06-22. `codex.exe` outside voice failed with `Access is denied`; fallback read-only subagent completed, was closed, and all accepted findings below are incorporated.

## Goal

Implement the V3 Capability Acquisition Layer so Chainless can discover missing
capabilities during real Agent work, explore safe temporary solutions through
code-as-action, recommend durable capability targets, verify proposals, and
activate approved capabilities without silently mutating production runtime,
installing tools, leaking credentials, or bypassing audit.

This plan keeps the V3 scope intact. It does not shrink V3 into an Inbox-only
feature and does not continue the older pattern of hand-writing a builtin tool
for every new domain. The intended product behavior is:

- Unknown work first becomes explicit evidence: `CapabilityGap`,
  `ExplorationRun`, `CapabilityRecommendation`, `AcquisitionProposal`,
  `ActivationTarget`, `AcquisitionVerification`, and `AcquisitionJournal`.
- Low-risk public-data and file-processing gaps may be explored automatically.
  High-risk exploration requires user approval before it runs.
- Activation is always a second approval path. Verified proposals can activate
  only when the snapshot hash still matches the approved proposal, target,
  permissions, credentials, and verification evidence.
- Activated targets can become MCP tools, API tools, Workspace Connectors,
  Browser Automation capabilities, Workers, Skills, Memories, or development
  patch proposals, with Composite Target support for one primary target and
  optional secondary targets.
- Development patch proposals are never runtime-activated. They are evidence
  bundles for a human-approved development flow.

## Architecture

```text
Agent runtime / tool failure / code-as-action success
  |
  v
Capability Acquisition Facade
  |
  +--> core/planning_issues
  |       RuntimePlanningIssue for bad planning, missing context, or planner misses
  |
  +--> CapabilityGap
          |
          | risk policy
          v
      ExplorationRun
          |
          v
      CapabilityRecommendation
          |
          v
      AcquisitionProposal
          |
          | verification_requested -> verifying -> verified(snapshot_hash)
          v
      AcquisitionVerification
          |
          | activation_requested -> activation_approved(hash)
          v
      ActivationTarget
          |
          +--> MCPServerConfiguration -> isolated MCP stdio runtime or remote MCP
          +--> APIToolConfiguration -> generic API tool runtime
          +--> WorkspaceConnector -> approved path mapping and sandbox mount bundle
          +--> BrowserAutomation -> isolated browser runtime, traces, profiles
          +--> Worker / Skill / Memory -> V2 capability layer
          `--> DevelopmentPatchProposal -> review artifact only
          |
          v
      AcquisitionJournal / ACQUISITION.md read-only user log
```

Owner boundaries:

- Acquisition domain source of truth:
  `backend/app/models/acquisition.py`, `backend/app/api/v1/acquisition.py`,
  and split owners under `backend/app/core/acquisition/`.
- Acquisition internal owners:
  `lifecycle.py` owns Gap, Exploration, Recommendation, and Proposal
  transitions; `verification.py` owns verification runs and verified snapshot
  creation; `activation.py` owns activation approval and activation start;
  `rollback.py` owns activation saga compensation and rollback; `read_model.py`
  owns list/read projections; `bridge.py` owns accepted V2 handoff;
  `outbox.py` owns durable acquisition analysis enqueue/retry; `facade.py`
  remains the only integration seam used by stream/agent callers.
- Acquisition public API path:
  `/api/v1/acquisition/*`.
- Existing V2 capability Inbox remains owned by
  `backend/app/models/capability.py`, `backend/app/core/capabilities/`, and
  `/api/v1/capability-candidates`. V3 may bridge into V2 after verified
  acquisition outcomes, but V3 must not overload V2 candidate rows.
- CredentialConnection source of truth:
  `backend/app/core/credentials/` and V3 acquisition models. This owner is
  scoped to V3 acquired capability credentials only. Existing `LLMProvider`
  and `ChannelConfiguration` credential owners remain authoritative for LLM
  providers and channel integrations.
- Reusable outbound network policy:
  `backend/app/core/security/egress_policy.py`.
- RuntimePlanningIssue source of truth:
  `backend/app/core/planning_issues/`. Acquisition may cross-link planning
  issues and render them in the journal, but must not own planner-miss state.
- Isolated MCP stdio runtime:
  `backend/app/core/tools/mcp_runtime/` plus a dedicated compose service and
  image/Dockerfile or pinned image ref. Backend and worker containers must not
  launch arbitrary stdio MCP commands directly.
- Generic API tool runtime:
  `backend/app/core/tools/api_runtime/`.
- Per-user acquired tool manifest:
  `backend/app/core/tools/manifest.py`. Activation, rollback, revocation, and
  permission changes must bump the user-scoped manifest version used by Agent
  planning and tool registry exposure.
- Workspace Connector path and mount owner:
  `backend/app/core/workspace_connectors/`, with mount bundle propagation
  through `sandbox-proxy/main.py` for sandbox/code-as-action execution.
- Browser Automation runtime owner:
  `backend/app/core/browser_automation/` plus a dedicated compose service and
  image/Dockerfile or pinned image ref. It must not share the MCP stdio runtime
  or sandbox-proxy Docker socket authority.
- Agent integration seam:
  `backend/app/core/acquisition/facade.py`. `conversation_stream_service.py`
  may call the facade but must not import acquisition repositories, policy
  internals, credential internals, or runtime target internals.
- UI owner:
  existing chat, right panel, and Settings surfaces are extended through small
  components and stores. Current visual style, layout, scroll behavior, and
  conversation actions must be preserved.

## Tech Stack

- Backend: FastAPI, SQLAlchemy async, Alembic, PostgreSQL 16, pgvector,
  Redis/ARQ, existing audit and confirmation services.
- Runtime targets: existing sandbox and sandbox proxy, isolated MCP stdio
  runtime service, generic API runtime, Workspace Connector mount resolver,
  isolated Playwright/Chromium browser runtime.
- Frontend: Next.js, React, Zustand, existing Tailwind/zinc visual system.
- Verification: local Docker Desktop only. Do not use host Python or host Node
  as the application runtime.
- Browser QA: gstack `/browse` and `/qa` compatible Windows browser path, plus
  repo browser QA scripts when present.

## Baseline / Authority Refs

- `docs/aegis/specs/2026-06-20-v3-capability-acquisition-layer-design.md`
- `docs/aegis/specs/2026-06-16-v2-capability-operating-layer-design.md`
- `docs/aegis/plans/2026-06-17-v2-capability-operating-layer-execution-plan.md`
- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `backend/app/core/tools/mcp/client.py`
- `backend/app/core/tools/mcp/manager.py`
- `backend/app/core/tools/builtin/file_ops.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/secrets.py`
- `backend/app/models/llm_provider.py`
- `backend/app/models/channel_configuration.py`
- `frontend/src/stores/capability-store.ts`
- `frontend/src/components/chat/`
- `frontend/src/components/settings/`
- `AGENTS.md`

## Compatibility Boundary

- Do not redesign or restyle the frontend. Preserve current spacing, color,
  typography, panel structure, sidebar behavior, scroll behavior, Settings
  shell, and conversation rename/delete behavior.
- Do not use host Python or host Node for app execution or tests. Use Docker
  services and Docker test profile commands.
- Do not commit unless the user explicitly asks for a commit.
- `ACQUISITION_ENABLED=false` or disabled runtime capability flags must degrade
  safely: existing chat, V2 Capability Inbox, Workers, file tools, and normal
  Agent execution keep working; acquisition routes/UI expose a clear disabled
  state instead of failing the base product.
- Existing V1, W12, and V2 behavior must keep working: conversations, uploads,
  artifacts, file task closure, sandbox execution, Memory, Skill, Worker,
  Capability Inbox, scheduler, eval, audit, and confirmation resume.
- V3 acquisition objects are user-private by default. Shared or tenant-level
  scope must be explicit and tested.
- V3 must not pollute the V2 Capability Inbox. Acquisition state belongs in
  acquisition tables and the user-private acquisition journal. Only accepted
  V2-compatible outcomes may create Memory, Skill, or Worker candidates or
  records through existing V2 owners.
- Activation state order is mandatory:
  `drafted -> verification_requested -> verifying -> verified(snapshot_hash)
  -> activation_requested -> activation_approved(hash) -> activating ->
  activated`. Activation approval before verification is forbidden.
- Composite Target is runtime behavior, not only schema: primary failure blocks
  activation; secondary failure records `partial_activation`; rollback is
  idempotent; each target has independent permission, audit, verification, and
  rollback state; compensation covers registry, permission, session, journal,
  and audit state.
- Backend and worker containers must never execute arbitrary stdio MCP commands
  directly. `transport=stdio` requires `runtime_kind=isolated_stdio` and must
  go through `core/tools/mcp_runtime`.
- MCP stdio runtime and Browser Automation runtime are separate services/images
  with separate Dockerfiles or pinned image refs, healthchecks, no Docker socket,
  no backend/host filesystem access, resource limits, and cleanup tests.
- Activated API, remote MCP HTTP/SSE, Browser, and Worker-bound runtime targets
  must reject arbitrary network access. Hosts, redirects, private network
  access, DNS rebinding, byte caps, and credential references are policy-bound.
- Workspace Connector must use approved connector ids and generated mount
  bundles. Raw host paths must not be passed as a file tool execution path.
- Development patch proposal must not stage, commit, push, deploy, edit files,
  or mutate the working tree at runtime.
- Activation requires verified status, user approval, audit evidence, and an
  unchanged `activation_snapshot_hash`.
- Credential rotation or revocation invalidates dependent activation snapshots
  and blocks dependent target execution until reverified/reapproved.
- All acquisition list routes require pagination, default limits, maximum
  limits, and tenant/user isolation.
- `ACQUISITION.md` is bounded evidence, not authority: section rendering uses
  default limits, totals, and links to paginated API records.
- Standing Permission is bounded, revocable, expiring, and invalidated by any
  boundary change.
- Safe exploration is bounded: only public/read-only/run-workspace actions may
  auto-run. Login, payment, private network, external write, dependency install,
  credential access, and any non-idempotent side effect require exploration
  approval before execution.

## Plan Engineering Review Revision Contract

The 2026-06-22 `/plan-eng-review` found blocking and non-blocking issues. These
decisions are mandatory for implementation and supersede earlier ambiguous plan
phrasing:

- Keep full V3 scope; do not shrink to an Inbox MVP or defer runtime targets.
- Add the activation state machine listed in the Compatibility Boundary and
  tests forbidding approval before verification, stale approval reuse after
  re-verification, and activation without an approved verified hash.
- Add activation saga and rollback workflow tests for partial activation,
  per-target compensation order, idempotency keys, registry hide, permission
  revoke, session termination, journal update, and audit update.
- Add `ACQUISITION_ENABLED` and runtime capability flags with disabled-mode
  tests proving base chat, V2 Inbox, Workers, file tools, and normal Agent
  execution still work.
- Move RuntimePlanningIssue to `backend/app/core/planning_issues/`; acquisition
  only cross-links and renders planning issues.
- Add Gap dedupe protocol: normalized dedupe key, database unique/upsert
  behavior, row-lock/concurrent safety, and occurrence count increments.
- Add a per-user acquired tool manifest/version owner; activation, rollback,
  revocation, and permission changes bump the manifest so Agent planning and
  resumed runs cannot see stale tools.
- Split `core/acquisition/service.py` into smaller owners listed in the
  Architecture section.
- Lock canonical owners. Do not leave implementation-time owner discovery
  phrases in implementation tasks.
- Layer policy ownership: `acquisition/policy.py` makes final
  permission/confirmation decisions; `security/egress_policy.py` owns network
  checks; target-specific policies only adapt and narrow.
- Separate MCP stdio runtime and Browser runtime into distinct services/images.
- Extend Workspace Connector through `sandbox-proxy/main.py` so connector
  mounts reach sandbox/code-as-action.
- Reuse or extend the existing durable outbox pattern for acquisition analysis
  with bounded batch size, lease, retry, timeout metrics, and idempotency.
- Move frontend acquisition API calls to a dedicated module; do not grow the
  global `frontend/src/lib/api.ts` with the full V3 route surface.
- Add full route contracts for every `/api/v1/acquisition/*` route in the
  approved spec, including pagination/default/max limits for list routes.
- Add credential leak tests for Journal, SSE, audit, artifacts, browser traces,
  and logs.
- Add safe exploration bounds, Gap negative cases, API runtime matrix, Browser
  product-boundary/redaction, UI content-quality, bounded journal, bounded
  outbox, runtime concurrency, and observability tests.

## Verification

Targeted backend acquisition suite:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py tests/test_acquisition_lifecycle.py tests/test_acquisition_policy.py tests/test_acquisition_snapshot.py tests/test_acquisition_journal.py tests/test_acquisition_disabled_mode.py tests/test_acquisition_observability.py tests/test_planning_issues.py tests/test_tool_manifest.py"
```

Runtime target suite:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_mcp_runtime_isolation.py tests/test_mcp_transports.py tests/test_api_tool_runtime.py tests/test_v2_activation_targets.py tests/test_workspace_connectors.py tests/test_browser_automation_runtime.py tests/test_development_patch_proposal.py tests/test_tool_manifest.py"
```

Agent integration suite:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_agent_integration.py tests/test_planning_issues.py tests/test_worker_runtime.py tests/test_capability_candidates.py tests/test_file_tools.py tests/test_tool_manifest.py"
```

Full backend suite:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
```

Frontend verification:

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Local runtime smoke:

```powershell
docker-compose up -d --build
docker-compose ps
```

Browser QA:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost:3000 -Browser chrome -Headless -Suite capability-acquisition -TimeoutMs 240000
```

If `scripts\windows-browser-qa.ps1` is missing during execution, use gstack
`/browse` against `http://localhost:3000` and record screenshots for chat,
right panel, sidebar actions, Settings acquisition, scroll behavior, and
activation confirmation.

## Plan Basis

Facts:

- V2 already has Memory, Skill, Worker, Capability Candidate, Worker matching,
  audit, confirmation, sandbox, artifacts, scheduler, and eval foundations.
- Existing MCP support can launch stdio commands from the backend process path.
  V3 requires isolating that behavior behind `core/tools/mcp_runtime`.
- Existing file tools operate against `/workspace` and support runtime context.
  V3 requires explicit Workspace Connector ids and mount bundles for approved
  local path access.
- Existing secrets helpers can encrypt and decrypt secret values. V3 needs a
  scoped CredentialConnection owner for acquired capability credentials.
- Existing frontend already has chat, right panel, Settings, and capability
  store surfaces. V3 extends these surfaces without changing style.

Assumptions:

- Docker Desktop is available locally and the current Chainless compose stack
  can build and start.
- pgvector remains available in both normal and test databases.
- The browser runtime can be introduced as a compose-managed service with
  bounded profile and trace storage.

Implementation facts:

- Browser QA entrypoints exist at `scripts/windows-browser-qa.ps1`,
  `scripts/windows-browser-qa.cjs`, and `scripts/qa/`. V3 must add a dedicated
  acquisition suite there rather than relying on manual screenshots only.
- Eval tasks live in `backend/tests/eval/tasks/`, and the runner is
  `backend/scripts/run-eval.py`. V3 must add
  `backend/tests/eval/tasks/capability_acquisition.json` and deterministic
  runner cases.

## Files

Create:

- `backend/app/models/acquisition.py`
- `backend/alembic/versions/0012_add_capability_acquisition_layer.py`
- `backend/app/core/acquisition/__init__.py`
- `backend/app/core/acquisition/schemas.py`
- `backend/app/core/acquisition/repository.py`
- `backend/app/core/acquisition/lifecycle.py`
- `backend/app/core/acquisition/verification.py`
- `backend/app/core/acquisition/activation.py`
- `backend/app/core/acquisition/rollback.py`
- `backend/app/core/acquisition/read_model.py`
- `backend/app/core/acquisition/bridge.py`
- `backend/app/core/acquisition/outbox.py`
- `backend/app/core/acquisition/policy.py`
- `backend/app/core/acquisition/snapshot.py`
- `backend/app/core/acquisition/journal.py`
- `backend/app/core/acquisition/facade.py`
- `backend/app/core/planning_issues/__init__.py`
- `backend/app/core/planning_issues/repository.py`
- `backend/app/core/planning_issues/service.py`
- `backend/app/core/tools/manifest.py`
- `backend/app/core/credentials/__init__.py`
- `backend/app/core/credentials/service.py`
- `backend/app/core/security/egress_policy.py`
- `backend/app/core/tools/mcp_runtime/__init__.py`
- `backend/app/core/tools/mcp_runtime/client.py`
- `backend/app/core/tools/mcp_runtime/policy.py`
- `backend/app/core/tools/mcp_runtime/supervisor.py`
- `mcp-runtime/Dockerfile`
- `backend/app/core/tools/api_runtime/__init__.py`
- `backend/app/core/tools/api_runtime/client.py`
- `backend/app/core/tools/api_runtime/policy.py`
- `backend/app/core/workspace_connectors/__init__.py`
- `backend/app/core/workspace_connectors/service.py`
- `backend/app/core/workspace_connectors/mounts.py`
- `backend/app/core/browser_automation/__init__.py`
- `backend/app/core/browser_automation/client.py`
- `backend/app/core/browser_automation/policy.py`
- `backend/app/core/browser_automation/traces.py`
- `browser-runtime/Dockerfile`
- `backend/app/api/v1/acquisition.py`
- `frontend/src/lib/api/acquisition.ts`
- `frontend/src/stores/acquisition-store.ts`
- `frontend/src/components/chat/acquisition-hint-card.tsx`
- `frontend/src/components/chat/acquisition-panel.tsx`
- `frontend/src/components/settings/acquisition-section.tsx`
- `backend/tests/test_acquisition_models.py`
- `backend/tests/test_acquisition_api_contracts.py`
- `backend/tests/test_acquisition_lifecycle.py`
- `backend/tests/test_acquisition_policy.py`
- `backend/tests/test_acquisition_snapshot.py`
- `backend/tests/test_acquisition_journal.py`
- `backend/tests/test_acquisition_disabled_mode.py`
- `backend/tests/test_acquisition_observability.py`
- `backend/tests/test_planning_issues.py`
- `backend/tests/test_tool_manifest.py`
- `backend/tests/test_mcp_runtime_isolation.py`
- `backend/tests/test_api_tool_runtime.py`
- `backend/tests/test_workspace_connectors.py`
- `backend/tests/test_browser_automation_runtime.py`
- `backend/tests/test_development_patch_proposal.py`
- `backend/tests/test_v2_activation_targets.py`
- `backend/tests/test_acquisition_agent_integration.py`
- `backend/tests/eval/tasks/capability_acquisition.json`
- `scripts/qa/acquisition-suite.cjs`
- `docs/architecture/capability-acquisition-layer.md`

Modify:

- `backend/app/models/__init__.py`
- `backend/app/api/v1/router.py`
- `backend/app/core/tools/mcp/client.py`
- `backend/app/core/tools/mcp/manager.py`
- `backend/app/core/tools/builtin/file_ops.py`
- `backend/app/core/tools/registry.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/agent/prompt_builder.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/workers/runtime.py`
- `backend/app/core/workers/matcher.py`
- `backend/app/core/capabilities/service.py`
- `backend/app/core/audit/service.py`
- `backend/app/core/observability/runtime_metrics.py`
- `sandbox-proxy/main.py`
- `docker-compose.yml`
- `docker-compose.test.yml`
- `scripts/windows-browser-qa.cjs`
- `scripts/qa/suite-registry.cjs`
- `backend/scripts/run-eval.py`
- `frontend/src/lib/api.ts` only for compatibility re-export if required
- `frontend/src/components/chat/preview-panel.tsx`
- `frontend/src/components/settings/settings-shell.tsx`
- `docs/aegis/INDEX.md`

## Architecture Integrity Lens

- Invariant: Agent capability expansion must become explicit, approved,
  verified, reversible, and observable. Silent runtime mutation is forbidden.
- Canonical owner / contract: acquisition lifecycle belongs to
  `core/acquisition`; runtime target execution belongs to target-specific
  owners; conversation streaming calls only the facade.
- Responsibility overlap: V2 Capability Inbox, Workers, Skills, and Memories
  remain reuse and execution owners. V3 owns capability acquisition and may
  call V2 only through accepted target seams.
- Higher-level simplification: use a shared `PermissionBundle`,
  `CredentialConnection`, `ActivationSnapshot`, and `AcquisitionJournal`
  instead of target-specific ad hoc approval state.
- Retirement / falsifier: any old path that launches stdio MCP directly from
  backend or accepts raw host paths into file tools is either removed or guarded
  behind compatibility tests proving it cannot execute unapproved runtime work.
- Verdict: proceed with new acquisition owner and target-specific runtime
  owners. Do not add V3 state into V2 candidate metadata.

## Plan Pressure Test

- Owner / contract / retirement: owners are explicit; retired behavior is
  direct stdio MCP launch, raw host file access, unverified activation, and
  runtime development patch mutation.
- Architecture integrity / higher-level path: acquisition facade prevents
  `conversation_stream_service.py` from becoming a god object.
- Verification scope: backend contract tests, runtime isolation tests,
  frontend style/scroll browser QA, eval, and compose smoke are included.
- Task executability: each workstream has file paths, acceptance assertions,
  commands, and stop conditions.
- Pressure result: proceed.

## Plan-Time Complexity Check

- Target files:
  `conversation_stream_service.py`, `mcp/client.py`, `mcp/manager.py`,
  `file_ops.py`, `agent/engine.py`, `frontend/src/lib/api/acquisition.ts`,
  optional `frontend/src/lib/api.ts` re-export, `preview-panel.tsx`, and
  `settings-shell.tsx`.
- Existing size / shape signals:
  conversation streaming, agent runtime, and frontend API files already carry
  many behaviors and should not receive direct acquisition internals.
- Owner fit:
  add owner files for acquisition lifecycle, credentials, egress policy, MCP
  runtime, API runtime, Workspace Connector, and Browser Automation.
- Add-in-place risk:
  high for stream service, agent engine, and frontend shell components.
- Better file boundary:
  add facade, split acquisition owner, planning issue, manifest, runtime,
  store, API module, and component files; call them from existing seams.
- Recommendation:
  add owner files; edit existing large files only at import, router, event, and
  render seam points.

## Workstream 1: Schema, Models, Migration, and Typed Contracts

Stop condition: the database can persist every V3 domain object, API schemas
serialize required fields explicitly, and no acquisition state is hidden only
inside generic metadata.

### Task 1.1: Add acquisition SQLAlchemy models

Files:

- Create `backend/app/models/acquisition.py`
- Create `backend/tests/test_acquisition_models.py`

Why:

- V3 needs durable first-class records for capability gaps, exploration,
  recommendations, proposals, activation targets, verification, journal,
  runtime planning issues, credential connections, standing permissions, and
  target-specific configurations.

Impact / Compatibility:

- Adds tables only. Existing V2 capability, Memory, Skill, Worker, LLMProvider,
  and ChannelConfiguration tables are not migrated or renamed.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_models.py"
```

Steps:

- [ ] Write test: add tests named `test_acquisition_models_have_required_columns`, `test_acquisition_user_scope_is_required_for_private_records`, `test_activation_target_rejects_missing_primary_target_fields`, and `test_development_patch_proposal_cannot_be_runtime_active` in `backend/tests/test_acquisition_models.py`.
- [ ] Verify RED: run the verification command and confirm failures mention missing `app.models.acquisition` or missing columns.
- [ ] Minimal code: define SQLAlchemy classes `CapabilityGap`, `ExplorationRun`, `CapabilityRecommendation`, `AcquisitionProposal`, `ActivationTarget`, `AcquisitionVerification`, `AcquisitionJournalEntry`, `RuntimePlanningIssue`, `CredentialConnection`, `StandingPermission`, `MCPServerConfiguration`, `APIToolConfiguration`, `WorkspaceConnector`, `BrowserAutomationConfiguration`, and `DevelopmentPatchProposal` with explicit enum/check constraints from the spec.
- [ ] Verify GREEN: rerun the verification command and confirm the new model tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage only task files and run `git commit -m "Add V3 acquisition models"`.

### Task 1.2: Add Alembic migration and model exports

Files:

- Create `backend/alembic/versions/0012_add_capability_acquisition_layer.py`
- Modify `backend/app/models/__init__.py`
- Extend `backend/tests/test_acquisition_models.py`

Why:

- Runtime and test databases need the V3 schema, indexes, foreign keys, JSONB
  constraints, vector columns where needed, and model exports for metadata
  discovery.

Impact / Compatibility:

- Migration `0012` must use `down_revision = "0011"`.
- No existing data is deleted.
- Existing tenant/user foreign keys and JSONB patterns should match V2 model
  style.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && alembic upgrade head && pytest -q tests/test_acquisition_models.py"
```

Steps:

- [ ] Write test: add assertions that all acquisition tables appear in `Base.metadata.tables`, migration-created indexes include user/status lookup paths, Gap dedupe unique/upsert columns exist, and `models.__all__` exports all new model classes.
- [ ] Verify RED: run the verification command and confirm migration or export failures.
- [ ] Minimal code: create migration `0012_add_capability_acquisition_layer.py`, add tables, indexes, check constraints, JSONB defaults, foreign keys, Gap dedupe unique index, `occurrence_count`, activation state fields, and model exports.
- [ ] Verify GREEN: rerun the verification command and confirm Alembic upgrade plus model tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage migration/model export files and run `git commit -m "Add V3 acquisition migration"`.

### Task 1.3: Add Pydantic schemas and serialization contracts

Files:

- Create `backend/app/core/acquisition/schemas.py`
- Create `backend/tests/test_acquisition_api_contracts.py`

Why:

- The frontend, API tests, and activation snapshot need stable typed contracts
  with explicit evidence, target, permission, credential, and verification
  fields.

Impact / Compatibility:

- No API route is added yet. This task only introduces shared schemas used by
  later services and routes.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_api_contracts.py"
```

Steps:

- [ ] Write test: add tests named `test_capability_gap_contract_serializes_source_evidence`, `test_acquisition_proposal_contract_serializes_composite_target`, `test_activation_state_machine_contract_serializes_verified_hash_and_approval_hash`, `test_activation_snapshot_contract_has_required_hash_inputs`, and `test_credential_connection_contract_redacts_secret_values`.
- [ ] Verify RED: run the verification command and confirm missing schema failures.
- [ ] Minimal code: define request/response schemas for all acquisition objects, target config schemas, permission bundle schemas, approval requests, activation requests, and journal views.
- [ ] Verify GREEN: rerun the verification command and confirm serialization tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage schema/test files and run `git commit -m "Add V3 acquisition API contracts"`.

## Workstream 2: Acquisition Lifecycle, Verification, Activation, Rollback, Snapshot, and Journal

Stop condition: gaps can be created, deduped, explored, recommended, proposed,
verified, approved, activated, partially activated, rolled back, and journaled
through split owners with idempotent state transitions.

### Task 2.1: Add acquisition repository and lifecycle owner

Files:

- Create `backend/app/core/acquisition/repository.py`
- Create `backend/app/core/acquisition/lifecycle.py`
- Create `backend/app/core/acquisition/__init__.py`
- Create `backend/tests/test_acquisition_lifecycle.py`

Why:

- V3 needs explicit lifecycle ownership for Gap, Exploration, Recommendation,
  and Proposal state changes instead of scattered writes in agent runtime, tool
  runtime, and UI routes.

Impact / Compatibility:

- No route or agent integration yet. Existing code is not called until later
  workstreams connect the facade.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_lifecycle.py"
```

Steps:

- [ ] Write test: add `test_gap_lifecycle_is_idempotent`, `test_gap_dedupe_concurrent_failures_create_one_gap_and_increment_occurrence_count`, `test_missing_user_input_greeting_transient_retryable_failure_and_planner_missed_existing_tool_do_not_create_gap`, `test_safe_exploration_auto_runs_only_inside_public_read_only_run_workspace_bounds`, `test_login_payment_private_network_external_write_dependency_install_credentials_and_non_idempotent_side_effects_require_exploration_approval`, and `test_rejected_proposal_cannot_activate`.
- [ ] Verify RED: run the verification command and confirm missing service or transition failures.
- [ ] Minimal code: implement repository CRUD, normalized Gap dedupe key, database upsert/row-lock behavior, idempotency keys, lifecycle transition methods, audit event calls through `backend/app/core/audit/service.py`, safe exploration bounds, no-gap negative classification, and status validation.
- [ ] Verify GREEN: rerun the verification command and confirm lifecycle tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage acquisition lifecycle files and run `git commit -m "Add acquisition lifecycle owner"`.

### Task 2.2: Add verification, activation state machine, and snapshot drift prevention

Files:

- Create `backend/app/core/acquisition/verification.py`
- Create `backend/app/core/acquisition/activation.py`
- Create `backend/app/core/acquisition/snapshot.py`
- Create `backend/tests/test_acquisition_snapshot.py`

Why:

- Activation approval must happen after verification and bind the exact
  proposal, target, permission bundle, credential references, and verification
  evidence. Boundary drift after user approval must force a new approval.

Impact / Compatibility:

- Activation remains blocked until verification creates a snapshot hash and the
  user approves that exact verified hash.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_snapshot.py"
```

Steps:

- [ ] Write test: add `test_snapshot_hash_is_stable_for_canonical_json`, `test_snapshot_hash_changes_when_permission_or_credential_generation_changes`, `test_activation_approval_before_verification_is_forbidden`, `test_reverify_after_approval_requires_new_approval_hash`, `test_activate_without_approved_verified_hash_is_forbidden`, `test_activation_denies_stale_snapshot`, and `test_snapshot_uses_digest_refs_not_mutable_blob_text`.
- [ ] Verify RED: run the verification command and confirm missing snapshot functions.
- [ ] Minimal code: implement canonical JSON serialization, `sha256` snapshot hashing, schema versioning, snapshot storage, verification state transitions, activation approval binding to the verified hash, credential generation drift checks, and activation drift checks.
- [ ] Verify GREEN: rerun the verification command and confirm snapshot tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage verification/activation/snapshot files and run `git commit -m "Add acquisition verification state machine"`.

### Task 2.3: Add activation saga and rollback owner

Files:

- Create `backend/app/core/acquisition/rollback.py`
- Extend `backend/app/core/acquisition/activation.py`
- Create `backend/tests/test_acquisition_lifecycle.py`

Why:

- Primary target activation, secondary target partial failure, and user-visible
  rollback must not leave registry, permission, session, journal, or audit
  state split across owners.

Impact / Compatibility:

- Target-specific runtimes expose compensation hooks; acquisition rollback
  owns orchestration and idempotency.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_lifecycle.py tests/test_acquisition_policy.py tests/test_tool_manifest.py"
```

Steps:

- [ ] Write test: add `test_primary_activation_failure_blocks_activation`, `test_secondary_activation_failure_records_partial_activation_without_auto_rolling_back_primary`, `test_rollback_is_idempotent`, `test_rollback_hides_tool_revokes_permission_terminates_session_updates_journal_and_writes_audit`, and `test_rollback_failure_reports_user_visible_recovery_state`.
- [ ] Verify RED: run the verification command and confirm rollback/saga behavior is missing.
- [ ] Minimal code: implement activation saga phases, per-target compensation hooks, rollback idempotency keys, user-visible rollback state, registry/tool manifest invalidation, permission revocation, runtime session termination, journal update, and audit update.
- [ ] Verify GREEN: rerun the verification command and confirm rollback/saga tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage rollback files and run `git commit -m "Add acquisition activation rollback saga"`.

### Task 2.4: Add bounded user-private Acquisition Journal writer

Files:

- Create `backend/app/core/acquisition/journal.py`
- Create `backend/app/core/acquisition/read_model.py`
- Create `backend/tests/test_acquisition_journal.py`

Why:

- V3 discussion decided not to pollute V2 Capability Inbox with raw acquisition
  state. The user-private `ACQUISITION.md` journal gives durable, readable
  context while all mutations still go through API/service paths.

Impact / Compatibility:

- Journal file is read-only from the product perspective. It is rendered from
  durable records with bounded sections, totals, and links to paginated API
  records; it must not become an editable source of truth.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_journal.py"
```

Steps:

- [ ] Write test: add `test_journal_groups_open_gaps_proposals_activated_rejected_runtime_issues_and_patch_proposals`, `test_journal_is_user_private`, `test_journal_write_is_idempotent`, `test_journal_redacts_credentials_paths_and_trace_sensitive_values`, and `test_journal_uses_section_limits_totals_and_paginated_links_for_large_record_sets`.
- [ ] Verify RED: run the verification command and confirm missing journal owner.
- [ ] Minimal code: implement bounded journal rendering with sections `Open Gaps`, `Proposals Needing Approval`, `Activated Capabilities`, `Rejected or Dismissed`, `Runtime Planning Issues`, and `Development Patch Proposals`, default section limits, totals, paginated API links, and redaction.
- [ ] Verify GREEN: rerun the verification command and confirm journal tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage journal files and run `git commit -m "Add acquisition journal"`.

## Workstream 3: CredentialConnection, Egress Policy, and Permission Bundles

Stop condition: acquired credentials, network boundaries, standing permissions,
and runtime confirmations are explicit, revocable, auditable, and shared by all
activation targets.

### Task 3.1: Add V3 CredentialConnection owner

Files:

- Create `backend/app/core/credentials/__init__.py`
- Create `backend/app/core/credentials/service.py`
- Extend `backend/tests/test_acquisition_policy.py`
- Extend `backend/tests/test_acquisition_snapshot.py`

Why:

- MCP, API, Workspace, Browser, and future acquired targets need credential
  references without reusing LLMProvider or ChannelConfiguration ownership.

Impact / Compatibility:

- Existing LLM provider credentials and channel credentials remain in their
  current owners and are not migrated.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_policy.py"
```

Steps:

- [ ] Write test: add `test_credential_connection_encrypts_secret_material`, `test_credential_connection_response_redacts_secret_material`, `test_rotated_credential_generation_invalidates_activation_snapshot`, `test_revoked_credential_blocks_dependent_target_execution`, `test_revoked_credential_invalidates_dependent_activation_snapshot`, and `test_llm_provider_and_channel_credentials_are_not_reowned`.
- [ ] Verify RED: run the verification command and confirm missing credential service failures.
- [ ] Minimal code: implement create, rotate, revoke, resolve, dependent-target invalidation, activation-snapshot invalidation, and redact behavior using existing `backend/app/core/secrets.py`.
- [ ] Verify GREEN: rerun the verification command and confirm credential tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage credential files and run `git commit -m "Add V3 credential connection service"`.

### Task 3.2: Add reusable egress policy owner

Files:

- Create `backend/app/core/security/egress_policy.py`
- Extend `backend/tests/test_acquisition_policy.py`

Why:

- API tools, remote MCP, Browser Automation, and Worker-bound runtime calls must
  share the same SSRF, private network, redirect, DNS rebinding, byte limit, and
  host allowlist rules.

Impact / Compatibility:

- Existing internal service calls are not routed through this policy unless
  they are V3 acquired runtime calls.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_policy.py"
```

Steps:

- [ ] Write test: add `test_egress_policy_allows_declared_public_host`, `test_egress_policy_rejects_private_ip`, `test_egress_policy_rejects_dns_rebinding`, `test_egress_policy_rejects_forbidden_redirect`, `test_egress_policy_rejects_metadata_endpoint`, `test_egress_policy_rejects_oversized_response_contract`, and `test_arbitrary_network_is_forbidden_for_activated_targets`.
- [ ] Verify RED: run the verification command and confirm missing egress owner failures.
- [ ] Minimal code: implement host normalization, DNS resolution check hooks, redirect validation, private range rejection, content length bounds, and explicit allowlist evaluation.
- [ ] Verify GREEN: rerun the verification command and confirm egress tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage egress files and run `git commit -m "Add acquisition egress policy"`.

### Task 3.3: Add permission bundle and standing permission enforcement

Files:

- Create `backend/app/core/acquisition/policy.py`
- Extend `backend/tests/test_acquisition_policy.py`

Why:

- Approval semantics must be reusable and hard: bounded standing permission,
  runtime confirmation, expiration, revocation, and boundary-change invalidation.

Impact / Compatibility:

- Confirmation resume paths later must call this same policy owner. This task
  prepares the owner before runtime targets can execute.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_policy.py"
```

Steps:

- [ ] Write test: add `test_standing_permission_expires`, `test_standing_permission_revocation_blocks_runtime`, `test_permission_boundary_change_requires_reapproval`, `test_target_specific_policy_can_only_narrow_acquisition_decision`, `test_acquisition_policy_is_final_permission_gate`, and `test_runtime_confirmation_context_uses_same_policy_gate`.
- [ ] Verify RED: run the verification command and confirm missing policy behavior.
- [ ] Minimal code: implement permission bundle validation, standing permission lookup, expiration checks, revocation checks, confirmation-context validation, and final-decision layering where target policies adapt/narrow but cannot bypass `acquisition/policy.py` or `security/egress_policy.py`.
- [ ] Verify GREEN: rerun the verification command and confirm policy tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage policy files and run `git commit -m "Add acquisition permission policy"`.

## Workstream 4: Runtime and Durable Target Owners for MCP, API Tools, V2 Capabilities, and Development Patches

Stop condition: MCP, API, Worker, Skill, Memory, and development patch proposal
targets are persisted, verified, policy-gated, rollback-capable, and executable
or durable only through their proper owners.

### Task 4.1: Add isolated MCP runtime and durable MCP server configuration

Files:

- Create `backend/app/core/tools/mcp_runtime/__init__.py`
- Create `backend/app/core/tools/mcp_runtime/client.py`
- Create `backend/app/core/tools/mcp_runtime/policy.py`
- Create `backend/app/core/tools/mcp_runtime/supervisor.py`
- Create `mcp-runtime/Dockerfile`
- Modify `backend/app/core/tools/mcp/client.py`
- Modify `backend/app/core/tools/mcp/manager.py`
- Modify `docker-compose.yml`
- Modify `docker-compose.test.yml`
- Create `backend/tests/test_mcp_runtime_isolation.py`
- Extend `backend/tests/test_mcp_transports.py`

Why:

- V3 allows MCP activation, including stdio MCP, but stdio commands must not run
  in the backend or worker container. They must run through an isolated runtime
  with command provenance, digest checks, filesystem/network policy, resource
  limits, lifecycle cleanup, and restart-safe supervision.

Impact / Compatibility:

- Existing remote MCP HTTP/SSE behavior remains available through manager
  seams. Existing direct stdio launch is retired or guarded so unapproved stdio
  configs cannot execute.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_mcp_runtime_isolation.py tests/test_mcp_transports.py"
```

Steps:

- [ ] Write test: add `test_stdio_mcp_requires_isolated_runtime_kind`, `test_backend_mcp_client_does_not_launch_stdio_process`, `test_stdio_runtime_requires_command_provenance_and_package_digest`, `test_stdio_runtime_uses_dedicated_image_with_healthcheck`, `test_stdio_runtime_enforces_resource_limits`, `test_stdio_runtime_cannot_access_docker_socket_backend_fs_host_fs_unapproved_mounts_or_non_allowlisted_network`, `test_stdio_runtime_cleanup_after_success_failure_timeout_reconnect_backend_restart_and_rollback`, and `test_remote_mcp_transport_still_works`.
- [ ] Verify RED: run the verification command and confirm direct stdio launch behavior fails isolation expectations.
- [ ] Minimal code: add MCP runtime Docker image/service, healthcheck, policy/client/supervisor, compose service wiring, durable `MCPServerConfiguration` handling, command provenance/digest checks, no Docker socket/backend FS/host FS access, cleanup hooks, and manager/client changes that route stdio through the isolated runtime only.
- [ ] Verify GREEN: rerun the verification command and confirm MCP runtime tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage MCP runtime files and run `git commit -m "Add isolated MCP runtime target"`.

### Task 4.2: Add generic API tool runtime

Files:

- Create `backend/app/core/tools/api_runtime/__init__.py`
- Create `backend/app/core/tools/api_runtime/client.py`
- Create `backend/app/core/tools/api_runtime/policy.py`
- Modify `backend/app/core/tools/registry.py`
- Create `backend/tests/test_api_tool_runtime.py`

Why:

- Chainless should not need a new builtin tool for every API-shaped capability.
  Verified API tool activation should create a policy-bound generic runtime
  with declared hosts, methods, schemas, byte caps, credential refs, and
  idempotency constraints.

Impact / Compatibility:

- Existing builtin tools remain. Generic API tools enter the registry only
  after activation and policy verification.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_api_tool_runtime.py tests/test_acquisition_policy.py"
```

Steps:

- [ ] Write test: add `test_api_tool_requires_allowed_host`, `test_api_tool_rejects_private_network`, `test_api_tool_rejects_dns_rebinding`, `test_api_tool_rejects_unsafe_redirect`, `test_api_tool_rejects_disallowed_content_type`, `test_api_tool_enforces_rate_limit_timeout_retry_and_error_contract`, `test_api_tool_injects_credential_by_reference_only`, `test_api_tool_respects_request_and_response_byte_caps`, and `test_api_tool_requires_confirmation_for_non_idempotent_or_external_write`.
- [ ] Verify RED: run the verification command and confirm missing API runtime behavior.
- [ ] Minimal code: implement API runtime client/policy, registry exposure for active targets, request rendering from schema, response redaction, rate limiting, timeout/retry policy, error contract normalization, content-type checks, idempotency checks, and policy checks.
- [ ] Verify GREEN: rerun the verification command and confirm API runtime tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage API runtime files and run `git commit -m "Add generic API tool runtime"`.

### Task 4.3: Add development patch proposal target

Files:

- Extend `backend/app/core/acquisition/bridge.py`
- Extend `backend/app/core/acquisition/activation.py`
- Create `backend/tests/test_development_patch_proposal.py`

Why:

- Self-modification must be converted into a reviewable development artifact,
  not a runtime mutation path.

Impact / Compatibility:

- No runtime code path may apply patches, edit repo files, stage, commit, push,
  or deploy from this target.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_development_patch_proposal.py"
```

Steps:

- [ ] Write test: add `test_development_patch_proposal_records_base_commit_patch_digest_test_plan_and_rollback`, `test_development_patch_proposal_cannot_activate_as_runtime_tool`, `test_runtime_mutation_fields_are_forbidden`, `test_development_patch_handoff_fails_when_current_git_revision_differs_from_base_commit`, and `test_development_patch_handoff_fails_when_patch_no_longer_applies`.
- [ ] Verify RED: run the verification command and confirm missing patch proposal behavior.
- [ ] Minimal code: implement proposal validation, immutable artifact digest refs, rollback checklist fields, current revision validation, patch dry-apply validation, `handoff_ready` state, and runtime activation denial.
- [ ] Verify GREEN: rerun the verification command and confirm development patch tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage patch proposal files and run `git commit -m "Add development patch proposal target"`.

### Task 4.4: Add Worker, Skill, and Memory activation targets through V2 owners

Files:

- Extend `backend/app/core/acquisition/activation.py`
- Extend `backend/app/core/acquisition/verification.py`
- Extend `backend/app/core/acquisition/rollback.py`
- Extend `backend/app/core/acquisition/bridge.py`
- Extend `backend/app/core/capabilities/service.py`
- Extend `backend/app/core/workers/service.py`
- Extend `backend/app/core/memory/persistent.py`
- Create `backend/tests/test_v2_activation_targets.py`
- Extend `backend/tests/test_capability_candidates.py`
- Extend `backend/tests/test_worker_runtime.py`

Why:

- The spec defines Worker, Skill, and Memory as first-class activation targets.
  Without this task, V3 would acquire external tools but fail to activate the
  core Chainless capability loop: Memory remembers facts, Skill remembers
  methods, and Worker remembers executable work.

Impact / Compatibility:

- V3 acquisition remains the source of verification, approval, snapshot, audit,
  and rollback state. Existing V2 Memory, Skill, Worker, and Capability
  Candidate owners remain the persistence/runtime owners for accepted
  V2-compatible outcomes. Do not hide acquisition state in V2 candidate
  metadata.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_v2_activation_targets.py tests/test_capability_candidates.py tests/test_worker_runtime.py"
```

Steps:

- [ ] Write test: add `test_worker_target_requires_verified_worker_version_schema_allowed_tools_and_permission_snapshot`, `test_worker_target_activation_creates_or_updates_worker_version_through_worker_owner`, `test_worker_target_rollback_disables_or_rolls_back_worker_version`, `test_skill_target_requires_trigger_or_semantic_match_and_no_embedded_runtime_permission`, `test_skill_target_activation_creates_private_skill_through_skill_owner`, `test_skill_target_rollback_disables_or_deletes_skill`, `test_memory_target_requires_source_evidence_user_scope_and_secret_redaction`, `test_memory_target_activation_writes_private_memory_through_memory_owner`, `test_memory_target_rollback_archives_or_deletes_memory`, and `test_v2_target_activation_does_not_store_v3_state_in_capability_candidate_metadata`.
- [ ] Verify RED: run the verification command and confirm Worker/Skill/Memory activation targets are not implemented through acquisition verification/activation/rollback.
- [ ] Minimal code: implement V2 target adapters that validate WorkerVersion, Skill trigger/method policy, and Memory evidence/scope, then call existing V2 owners for activation and rollback while keeping acquisition snapshot/audit/permission state in V3 acquisition owners.
- [ ] Verify GREEN: rerun the verification command and confirm V2 activation target tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage V2 target files and run `git commit -m "Add V2 capability activation targets"`.

## Workstream 5: Workspace Connector, File Tools, and Code-as-Action Propagation

Stop condition: user-approved local/workspace paths become connector-backed
mount bundles visible to file tools and sandbox/code-as-action, while stale
workspace pollution and raw host path access are blocked.

### Task 5.1: Add Workspace Connector owner and mount resolver

Files:

- Create `backend/app/core/workspace_connectors/__init__.py`
- Create `backend/app/core/workspace_connectors/service.py`
- Create `backend/app/core/workspace_connectors/mounts.py`
- Modify `sandbox-proxy/main.py`
- Create `backend/tests/test_workspace_connectors.py`

Why:

- "Private AI Worker OS" requires approved local/workspace access without
  giving the Agent arbitrary host filesystem access.

Impact / Compatibility:

- Existing upload/artifact flows remain. Workspace Connector adds a separate
  approved path contract.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_workspace_connectors.py"
```

Steps:

- [ ] Write test: add `test_workspace_connector_requires_user_approval`, `test_mount_bundle_contains_connector_id_generation_and_container_paths`, `test_mount_bundle_propagates_to_sandbox_proxy_without_raw_host_path`, `test_raw_host_path_is_never_exposed_to_agent_context`, and `test_connector_revocation_blocks_future_mounts`.
- [ ] Verify RED: run the verification command and confirm missing connector owner.
- [ ] Minimal code: implement connector creation, approval, revocation, mount bundle generation, path normalization, sandbox-proxy mount contract, and audit events.
- [ ] Verify GREEN: rerun the verification command and confirm connector tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage connector files and run `git commit -m "Add Workspace Connector owner"`.

### Task 5.2: Route file tools through connector-aware context

Files:

- Modify `backend/app/core/tools/builtin/file_ops.py`
- Modify `backend/app/core/tools/registry.py`
- Modify `sandbox-proxy/main.py`
- Extend `backend/tests/test_file_tools.py`
- Extend `backend/tests/test_workspace_connectors.py`

Why:

- Uploaded files, artifacts, connector mounts, and sandbox workspace must have
  a clear contract. The Agent should not list stale test files after failing to
  read a user-selected file.

Impact / Compatibility:

- Existing `/workspace` behavior remains for internal sandbox workspace files.
  Host/local path access requires a connector id and mount bundle.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_tools.py tests/test_workspace_connectors.py"
docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile live-docker run --rm -e PYTHONPATH=/repo/backend backend-test-live sh -lc "cd /repo/backend && pytest -q tests/test_workspace_connectors.py -m live_docker"
```

Steps:

- [ ] Write test: add `test_file_read_accepts_connector_mounted_path`, `test_code_as_action_reads_connector_mounted_path_in_live_sandbox`, `test_file_list_omits_unrelated_stale_workspace_files_when_attachment_context_is_active`, `test_raw_workspace_base_override_is_rejected_for_host_access`, and `test_revoked_connector_file_read_fails_with_actionable_message`.
- [ ] Verify RED: run the verification command and confirm current file tool behavior fails connector expectations.
- [ ] Minimal code: add connector-aware path resolver, sandbox-proxy mount propagation, attachment-aware listing guard, revoked-connector checks, and clear user-facing failure text.
- [ ] Verify GREEN: rerun the verification command and confirm file tool and connector tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage file tool files and run `git commit -m "Make file tools connector-aware"`.

### Task 5.3: Connect code-as-action exploration evidence to acquisition outcomes

Files:

- Modify `backend/app/core/agent/engine.py`
- Extend `backend/app/core/acquisition/facade.py`
- Extend `backend/app/core/acquisition/bridge.py`
- Create `backend/tests/test_acquisition_agent_integration.py`

Why:

- Code-as-action is the exploratory layer. Successful temporary scripts should
  create evidence that can become Worker, Skill, Memory, API Tool, MCP Tool, or
  Workspace Connector recommendations.

Impact / Compatibility:

- Normal code execution still completes the user task. Acquisition suggestions
  are secondary and cannot block successful task completion unless activation
  approval is required.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_agent_integration.py"
```

Steps:

- [ ] Write test: add `test_code_as_action_success_creates_exploration_evidence`, `test_repeated_success_creates_worker_or_skill_recommendation`, `test_failed_exploration_creates_gap_with_failure_reason`, and `test_code_as_action_connector_failure_records_gap_without_listing_stale_workspace_files`.
- [ ] Verify RED: run the verification command and confirm missing acquisition evidence events.
- [ ] Minimal code: emit structured exploration evidence through acquisition facade after code execution success or useful failure, including script digest, inputs, outputs, tool calls, and risk classification.
- [ ] Verify GREEN: rerun the verification command and confirm integration tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage agent/facade files and run `git commit -m "Link code-as-action evidence to acquisition"`.

## Workstream 6: Browser Automation Runtime

Stop condition: Browser Automation is a real activation target with isolated
runtime execution, profile isolation, traces, network policy, resource caps,
confirmation gates, and frontend-visible evidence.

### Task 6.1: Add browser runtime service and client owner

Files:

- Create `backend/app/core/browser_automation/__init__.py`
- Create `backend/app/core/browser_automation/client.py`
- Create `backend/app/core/browser_automation/policy.py`
- Create `backend/app/core/browser_automation/traces.py`
- Create `browser-runtime/Dockerfile`
- Modify `docker-compose.yml`
- Modify `docker-compose.test.yml`
- Create `backend/tests/test_browser_automation_runtime.py`

Why:

- Some capability gaps need real browser automation for public web flows, DOM
  inspection, screenshots, and user-approved external interactions.

Impact / Compatibility:

- This runtime is separate from gstack browser QA. Product browser automation
  must run in the compose-managed runtime, not in the developer QA browser.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_browser_automation_runtime.py"
```

Steps:

- [ ] Write test: add `test_browser_runtime_requires_allowed_hosts`, `test_browser_runtime_uses_dedicated_image_with_healthcheck`, `test_browser_runtime_uses_isolated_profile`, `test_browser_runtime_records_redacted_trace_artifact`, `test_browser_runtime_enforces_session_timeout`, `test_browser_runtime_denies_external_write_without_confirmation`, `test_browser_runtime_cannot_access_docker_socket_host_fs_or_non_allowlisted_network`, `test_browser_runtime_forbids_captcha_paywall_login_bypass_and_unauthorized_automation`, `test_browser_runtime_redacts_cookies_screenshots_and_trace_sensitive_values`, and `test_browser_runtime_enforces_per_user_system_concurrency_max_actions_and_cleanup_releases_resources`.
- [ ] Verify RED: run the verification command and confirm missing browser runtime behavior.
- [ ] Minimal code: add browser runtime Docker image/service, client, policy checks, trace artifact handling, compose service health checks, profile retention settings, trace/cookie/screenshot redaction, forbidden automation boundaries, per-user/system concurrency, max actions per run, cleanup accounting, and resource caps.
- [ ] Verify GREEN: rerun the verification command and confirm browser runtime tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage browser runtime files and run `git commit -m "Add browser automation runtime target"`.

### Task 6.2: Register browser automation as an activation target

Files:

- Extend `backend/app/core/acquisition/activation.py`
- Extend `backend/app/core/tools/registry.py`
- Extend `backend/app/core/tools/manifest.py`
- Extend `backend/tests/test_browser_automation_runtime.py`

Why:

- Verified Browser Automation proposals need to become callable capabilities
  only after activation approval and permission checks.

Impact / Compatibility:

- Browser target calls pass through the same acquisition policy gate as API and
  MCP targets.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_browser_automation_runtime.py tests/test_acquisition_policy.py"
```

Steps:

- [ ] Write test: add `test_activated_browser_target_registers_tool`, `test_unverified_browser_target_is_not_callable`, `test_stale_snapshot_blocks_browser_activation`, `test_browser_target_bumps_tool_manifest_version_on_activation_and_rollback`, and `test_browser_target_uses_runtime_confirmation_policy`.
- [ ] Verify RED: run the verification command and confirm browser activation is not implemented.
- [ ] Minimal code: connect browser target activation to registry exposure, tool manifest versioning, policy checks, snapshot validation, rollback hooks, and confirmation context.
- [ ] Verify GREEN: rerun the verification command and confirm browser activation tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage browser activation files and run `git commit -m "Register browser automation activation target"`.

## Workstream 7: Agent Runtime Integration, Planning Issues, Tool Manifest, Outbox, and Observability

Stop condition: Agent execution can create acquisition evidence, degrade safely
when acquisition is disabled, separate true capability gaps from planner misses,
use activated targets through policy and fresh tool manifests, process durable
acquisition analysis jobs, emit operational metrics, and keep
`conversation_stream_service.py` thin.

### Task 7.1: Add acquisition facade and thin stream-service integration

Files:

- Create `backend/app/core/acquisition/facade.py`
- Create `backend/app/core/acquisition/outbox.py`
- Modify `backend/app/services/conversation_stream_service.py`
- Create `backend/tests/test_acquisition_agent_integration.py`
- Create `backend/tests/test_acquisition_disabled_mode.py`

Why:

- The stream service should not know acquisition internals. It should pass
  runtime events to a facade and stream lightweight UI notices.

Impact / Compatibility:

- Existing SSE events remain. New acquisition events are additive and
  namespaced. `ACQUISITION_ENABLED=false` makes the facade no-op for acquisition
  writes while preserving base chat behavior.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_agent_integration.py tests/test_acquisition_disabled_mode.py"
```

Steps:

- [ ] Write test: add `test_stream_service_calls_acquisition_facade_only`, `test_acquisition_notice_streams_without_blocking_chat_completion`, `test_acquisition_sse_event_names_match_spec_contract`, `test_stream_disconnect_does_not_drop_durable_analysis`, `test_acquisition_disabled_keeps_chat_v2_inbox_workers_file_tools_and_normal_agent_execution_working`, and `test_acquisition_disabled_routes_and_ui_return_clear_disabled_state`.
- [ ] Verify RED: run the verification command and confirm missing facade or direct import issues.
- [ ] Minimal code: implement facade methods for gap creation, exploration events, proposal events, spec-named SSE notices (`acquisition_gap`, `acquisition_exploration`, `acquisition_recommendation`, `acquisition_approval_required`, `acquisition_verification`, `acquisition_activation`, `acquisition_runtime_planning_issue`, `acquisition_permission`, `acquisition_browser_trace`), durable outbox enqueue, disabled-mode no-op behavior, runtime capability flag checks, and UI notices; adjust stream service to call only facade methods.
- [ ] Verify GREEN: rerun the verification command and confirm stream integration tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage facade/stream files and run `git commit -m "Add acquisition facade integration"`.

### Task 7.2: Add RuntimePlanningIssue owner

Files:

- Create `backend/app/core/planning_issues/__init__.py`
- Create `backend/app/core/planning_issues/repository.py`
- Create `backend/app/core/planning_issues/service.py`
- Extend `backend/app/core/acquisition/journal.py`
- Extend `backend/app/core/agent/engine.py`
- Create `backend/tests/test_planning_issues.py`

Why:

- Not every failure is a missing external capability. Planner misses, bad
  prompt context, wrong tool choice, and incomplete reasoning should not become
  Capability Gaps.

Impact / Compatibility:

- RuntimePlanningIssue is owned outside acquisition, is journaled through a
  cross-link, and never triggers activation recommendations.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_planning_issues.py tests/test_acquisition_journal.py"
```

Steps:

- [ ] Write test: add `test_planner_miss_creates_runtime_planning_issue_not_gap`, `test_missing_credential_creates_gap`, `test_missing_prompt_context_creates_runtime_planning_issue`, and `test_runtime_planning_issue_appears_in_journal`.
- [ ] Verify RED: run the verification command and confirm issue classification is missing.
- [ ] Minimal code: add planning issue repository/service methods, classification rules, journal cross-link rendering, and agent runtime calls.
- [ ] Verify GREEN: rerun the verification command and confirm runtime planning issue tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage planning issue files and run `git commit -m "Separate runtime planning issues from capability gaps"`.

### Task 7.3: Route activated acquisition targets through tool policy

Files:

- Modify `backend/app/core/tools/registry.py`
- Modify `backend/app/core/tools/manifest.py`
- Modify `backend/app/core/agent/prompt_builder.py`
- Modify `backend/app/core/workers/runtime.py`
- Extend `backend/tests/test_acquisition_policy.py`
- Create `backend/tests/test_tool_manifest.py`
- Extend `backend/tests/test_worker_runtime.py`

Why:

- Activated API/MCP/Browser/Workspace/Worker-bound targets must all pass the
  same policy gate during normal execution and confirmation resume.

Impact / Compatibility:

- Existing Worker policy remains. V3 adds acquisition target context and
  standing permission checks.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_policy.py tests/test_tool_manifest.py tests/test_worker_runtime.py"
```

Steps:

- [ ] Write test: add `test_normal_tool_execution_uses_acquisition_policy_gate`, `test_confirmation_resume_uses_same_acquisition_policy_gate`, `test_worker_bound_target_passes_worker_run_id`, `test_activation_bumps_user_tool_manifest_version_and_next_run_sees_tool`, `test_revocation_or_rollback_bumps_manifest_and_resumed_run_cannot_see_stale_tool`, and `test_policy_denial_records_trace_reason`.
- [ ] Verify RED: run the verification command and confirm bypass paths exist.
- [ ] Minimal code: pass acquisition context into tool execution and confirmation resume, enforce policy in one owner, add user-scoped tool manifest/version lookups to prompt builder and registry, and record denial reasons in audit/trace.
- [ ] Verify GREEN: rerun the verification command and confirm policy integration tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage policy integration files and run `git commit -m "Gate activated targets through acquisition policy"`.

### Task 7.4: Add bounded acquisition outbox and observability

Files:

- Create `backend/app/core/acquisition/outbox.py`
- Modify `backend/app/core/observability/runtime_metrics.py`
- Create `backend/tests/test_acquisition_observability.py`
- Extend `backend/tests/test_acquisition_agent_integration.py`

Why:

- Stream-tail analysis can timeout or disconnect. Acquisition analysis must be
  durable, bounded, retryable, observable, and secret-safe.

Impact / Compatibility:

- Reuse the V2 capability outbox pattern where possible; do not create an
  unbounded scanner or synchronous stream-blocking analyzer.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_agent_integration.py tests/test_acquisition_observability.py"
```

Steps:

- [ ] Write test: add `test_acquisition_analysis_outbox_enqueue_is_idempotent`, `test_acquisition_outbox_claim_uses_skip_locked_lease_and_batch_limit`, `test_acquisition_outbox_retries_timeout_and_records_metrics`, `test_acquisition_metric_names_match_spec_contract`, `test_policy_block_rollback_failure_session_cleanup_and_credential_revocation_emit_metrics`, and `test_metrics_labels_do_not_include_secret_material_or_raw_paths`.
- [ ] Verify RED: run the verification command and confirm bounded acquisition outbox and metrics are missing.
- [ ] Minimal code: implement acquisition analysis enqueue/claim/complete/fail helpers, batch limit, lease/stale reclaim, retry counters, timeout counters, spec-named acquisition metrics, policy/rollback/session cleanup metrics, and safe metric labels.
- [ ] Verify GREEN: rerun the verification command and confirm outbox and observability tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage outbox/observability files and run `git commit -m "Add acquisition outbox observability"`.

## Workstream 8: API Surface and Frontend Acquisition UX

Stop condition: users can see acquisition hints, review private acquisition
state, approve exploration, approve activation, revoke permissions, inspect
evidence, manage credentials/connectors/browser targets, and navigate Settings
without style or scroll regressions.

### Task 8.1: Add `/api/v1/acquisition/*` routes

Files:

- Create `backend/app/api/v1/acquisition.py`
- Modify `backend/app/api/v1/router.py`
- Extend `backend/tests/test_acquisition_api_contracts.py`

Why:

- V3 needs a stable product API separate from V2 `/api/v1/capability-candidates`.

Impact / Compatibility:

- Existing capability candidate and worker routes are unchanged.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_api_contracts.py"
```

Steps:

- [ ] Write test: add route contract tests for every spec route: gaps list/detail/dismiss/snooze, explorations list/detail/approve-exploration, recommendations list/detail/draft-proposal, proposals list/detail/verify/approve-activation/reject-activation/activate/rollback/handoff-development-patch, runtime-planning-issues list/detail/dismiss, credential-connections list/detail/create/validate/rotate/revoke, browser-sessions list/detail/terminate, browser-traces detail, permissions list/revoke/renew, and journal.
- [ ] Write test: add pagination contract tests proving every list route enforces default limit, maximum limit, offset or cursor behavior, tenant/user isolation, stable ordering, and redacted serialization.
- [ ] Verify RED: run the verification command and confirm routes return 404 or schema mismatches.
- [ ] Minimal code: implement FastAPI router methods that call acquisition, planning issue, credential, connector, browser runtime, permission, rollback, and journal services through stable schemas with pagination/default/max limits.
- [ ] Verify GREEN: rerun the verification command and confirm API contract tests pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage API files and run `git commit -m "Add acquisition API routes"`.

### Task 8.2: Add frontend acquisition API client and store

Files:

- Create `frontend/src/lib/api/acquisition.ts`
- Modify `frontend/src/lib/api.ts` only for a compatibility re-export if required
- Create `frontend/src/stores/acquisition-store.ts`

Why:

- Frontend needs a dedicated acquisition state owner and must not overload the
  V2 capability store.

Impact / Compatibility:

- Existing capability store remains the V2 Inbox owner.

Verification:

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Steps:

- [ ] Write test: add or extend frontend type/build checks so acquisition API functions and store actions typecheck from `frontend/src/lib/api/acquisition.ts` for list, approve, verify, activate, rollback, revoke, renew, journal, credential, connector, planning issue, permission, and browser target flows.
- [ ] Verify RED: run the verification command and confirm missing types/functions fail if tests/build reference them.
- [ ] Minimal code: add acquisition TypeScript types and API functions in the dedicated module, keep `frontend/src/lib/api.ts` stable except optional re-export, add Zustand store actions, loading/error states, and no style changes.
- [ ] Verify GREEN: rerun the verification command and confirm frontend lint/build passes.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage frontend API/store files and run `git commit -m "Add acquisition frontend store"`.

### Task 8.3: Add chat, right panel, and Settings acquisition surfaces

Files:

- Create `frontend/src/components/chat/acquisition-hint-card.tsx`
- Create `frontend/src/components/chat/acquisition-panel.tsx`
- Create `frontend/src/components/settings/acquisition-section.tsx`
- Create `scripts/qa/acquisition-suite.cjs`
- Modify `scripts/windows-browser-qa.cjs`
- Modify `scripts/qa/suite-registry.cjs`
- Modify `frontend/src/components/chat/preview-panel.tsx`
- Modify `frontend/src/components/settings/settings-shell.tsx`

Why:

- Users need lightweight chat notices and a durable place to review and act on
  acquisition objects. Product behavior must stay clear without changing the
  established visual style.

Impact / Compatibility:

- No restyling. Add components by reusing existing card, button, panel,
  typography, and scroll patterns.

Verification:

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost:3000 -Browser chrome -Headless -Suite capability-acquisition -TimeoutMs 240000
```

Steps:

- [ ] Write test: add browser assertions for chat acquisition hint, right panel acquisition list, Settings acquisition section, problem/cause/risk/next-step/recovery text, separate Approve Exploration and Approve Activation actions, rollback visible for activated targets, disabled acquisition state, approve/revoke controls, sidebar conversation delete/rename still visible, chat scroll still works, and Settings conversation click still routes back to chat.
- [ ] Verify RED: run the verification commands and confirm the acquisition surfaces or browser assertions are missing.
- [ ] Minimal code: add components using existing visual classes and integrate them at current panel/Settings seams without changing global styles or layout primitives; add the acquisition browser QA suite and register it as `capability-acquisition`.
- [ ] Verify GREEN: rerun frontend lint/build and browser QA; confirm screenshots show no style regression in chat, right panel, sidebar, and Settings.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage frontend UI files and run `git commit -m "Add acquisition UI surfaces"`.

## Workstream 9: Eval, Documentation, Final QA, and Completion Evidence

Stop condition: V3 behavior passes targeted tests, full backend tests,
frontend build, compose smoke, browser QA, eval, docs, and completion evidence
with no known spec gaps.

### Task 9.1: Add acquisition eval suite

Files:

- Create `backend/tests/eval/tasks/capability_acquisition.json`
- Modify `backend/scripts/run-eval.py`
- Create `backend/tests/test_acquisition_agent_integration.py` cases if eval
  runner coverage needs fixtures

Why:

- V3 must be verified through product-level examples, not only unit tests.

Impact / Compatibility:

- Existing eval suites remain.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_acquisition_agent_integration.py"
docker-compose exec -T backend python scripts/run-eval.py --suite capability_acquisition --json --min-pass-rate 1.0
```

Steps:

- [ ] Write test: add eval cases for train query capability gap, public weather API exploration, safe exploration blocked by high-risk boundary, local file Workspace Connector recommendation, browser automation recommendation with confirmation before external write, activation verification before approval, partial activation rollback recovery, development patch proposal only, disabled acquisition fallback, and planner miss classification.
- [ ] Verify RED: run the verification commands and confirm missing eval suite or failing cases.
- [ ] Minimal code: add `backend/tests/eval/tasks/capability_acquisition.json` and extend `backend/scripts/run-eval.py` with deterministic cases named `capability_gap_train_query`, `public_weather_api_exploration`, `safe_exploration_high_risk_block`, `workspace_connector_recommendation`, `browser_automation_recommendation`, `activation_state_machine`, `partial_activation_rollback`, `development_patch_proposal`, `acquisition_disabled_fallback`, and `runtime_planning_issue_classification`.
- [ ] Verify GREEN: rerun the verification commands and confirm eval pass rate is `1.0`.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage eval files and run `git commit -m "Add acquisition eval suite"`.

### Task 9.2: Run full backend, frontend, compose, and browser QA

Files:

- No source files unless failures require fixes in earlier workstream owners
- Record evidence in `docs/aegis/work/2026-06-22-v3-capability-acquisition-layer/90-evidence.md`

Why:

- Completion requires proof across backend, frontend, local Docker runtime, and
  browser product surfaces.

Impact / Compatibility:

- Failures must be fixed in the owning workstream files, not bypassed by test
  weakening.

Verification:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile live-docker run --rm -e PYTHONPATH=/repo/backend backend-test-live sh -lc "cd /repo/backend && pytest -q tests/test_workspace_connectors.py tests/test_mcp_runtime_isolation.py -m live_docker"
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
docker-compose up -d --build
docker-compose ps
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost:3000 -Browser chrome -Headless -Suite capability-acquisition -TimeoutMs 240000
docker-compose exec -T backend python scripts/run-eval.py --suite capability_acquisition --json --min-pass-rate 1.0
```

Steps:

- [ ] Write test: confirm all targeted tests and browser assertions from W1-W8 are present before running full suites.
- [ ] Verify RED: if a full-suite failure appears, capture the failing test name and owner file before editing.
- [ ] Minimal code: repair failures only in the owner files defined by W1-W8; do not add broad fallbacks or weaken assertions.
- [ ] Verify GREEN: rerun full backend tests, live Docker connector/runtime tests, frontend lint/build, compose smoke, eval, browser QA, and metrics smoke until all pass.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage only completed implementation/evidence files and run `git commit -m "Verify V3 capability acquisition layer"`.

### Task 9.3: Add architecture docs, ADR signals, and final index entries

Files:

- Create `docs/architecture/capability-acquisition-layer.md`
- Create `docs/aegis/work/2026-06-22-v3-capability-acquisition-layer/10-intent.md`
- Create `docs/aegis/work/2026-06-22-v3-capability-acquisition-layer/20-checkpoint.md`
- Create `docs/aegis/work/2026-06-22-v3-capability-acquisition-layer/90-evidence.md`
- Modify `docs/aegis/INDEX.md`

Why:

- Future sessions need durable context for owner boundaries, verification
  evidence, and architecture decisions.

Impact / Compatibility:

- Docs must describe the implemented behavior, not aspirational behavior.

Verification:

```powershell
Select-String -LiteralPath docs\aegis\INDEX.md -Pattern 'v3-capability-acquisition-layer'
Select-String -LiteralPath docs\architecture\capability-acquisition-layer.md -Pattern 'MCP stdio|CredentialConnection|Workspace Connector|Browser Automation|activation_snapshot_hash|activation state machine|rollback saga|tool manifest|RuntimePlanningIssue|observability'
```

Steps:

- [ ] Write test: add documentation checks by running the two `Select-String` commands and confirming they fail before docs/index are present.
- [ ] Verify RED: capture missing index/doc references.
- [ ] Minimal code: write implementation-accurate architecture notes, work evidence, checkpoint, index rows, and review evidence for plan-eng-review outside-voice decisions.
- [ ] Verify GREEN: rerun the `Select-String` commands and confirm required references exist.
- [ ] Commit checkpoint: do not commit unless the user authorizes it; if authorized, stage docs files and run `git commit -m "Document V3 capability acquisition layer"`.

## Risks

- Runtime isolation risk: MCP stdio and browser automation widen the attack
  surface. Mitigation is isolated services, policy checks, resource caps,
  trace evidence, and tests proving backend/worker cannot execute those paths
  directly.
- Runtime image drift risk: isolated runtimes can silently lose isolation if
  implemented with shared backend images. Mitigation is separate MCP and Browser
  images/services, healthchecks, pinned refs or Dockerfiles, and escape tests.
- Credential leakage risk: acquired credentials touch more targets than V2.
  Mitigation is a scoped CredentialConnection owner, encrypted storage,
  redacted API responses, reference-only runtime injection, full-surface leak
  tests, and rotation/revocation snapshot invalidation.
- Activation split-brain risk: primary activation, secondary failure, rollback,
  registry exposure, and permission state can diverge. Mitigation is an
  activation saga, partial activation state, idempotent compensation, and
  journal/audit/tool-manifest tests.
- Tool cache risk: Agent planning can see stale tools after activation,
  rollback, or revocation. Mitigation is a user-scoped tool manifest version
  owner and prompt/registry tests for activation and resumed runs.
- Frontend regression risk: acquisition surfaces could disturb chat/right
  panel/Settings style. Mitigation is seam-only components, no global style
  changes, lint/build, browser screenshots/DOM/scroll assertions, and content
  assertions for problem/cause/risk/next-step/recovery.
- Product confusion risk: V2 candidates and V3 acquisition objects could blur.
  Mitigation is separate API paths, separate stores, separate tables, and an
  explicit bridge only after accepted acquisition outcomes.
- Unbounded growth risk: journals, list routes, and analysis jobs can degrade
  with usage. Mitigation is pagination/default/max limits, bounded journal
  rendering, bounded outbox claims, leases, retries, and metrics.
- Scope risk: V3 is broad. Mitigation is subagent-driven implementation by
  workstream, owner-file boundaries, and verification-before-completion gates.

## Not In Scope

- Frontend restyling, visual redesign, or global style/layout changes.
- Marketplace, team-shared capability publishing, or third-party capability
  catalog.
- Silent production self-modification, runtime patch application, package
  installation, commit, push, deploy, or working-tree mutation.
- A shared universal runner for MCP stdio and Browser Automation.
- Host Python or host Node as the app runtime or verification runtime.

## Retirement

- Retire direct backend stdio MCP command launch for activated or acquired MCP
  tools. Keep remote MCP HTTP/SSE behavior only through policy-bound manager
  paths.
- Retire raw host path access for user local files. Workspace Connector owns
  approved path mapping and mount bundle generation.
- Retire any runtime path that treats development patch proposals as executable
  targets.
- Retire acquisition state hidden in V2 capability candidate metadata. V2
  candidates remain for Memory/Skill/Worker reuse proposals only.
- Retire stream-service direct knowledge of acquisition repositories, target
  policies, credentials, or runtime internals.
- Retire stale tool visibility after rollback/revocation by making the
  user-scoped tool manifest version the source of truth for Agent planning.
- Retire unbounded acquisition journal rendering and unbounded background
  analysis scans.

## Execution Discipline

- Recommended mode: Subagent-Driven implementation.
- Use one fresh subagent per independent workstream or tightly bounded task.
- Close/release each subagent after its assigned workstream evidence is
  reviewed.
- Main agent owns final integration, verification, and user-facing status.
- Every workstream must reach its stop condition before moving forward.
- If a new issue is discovered, record it in the active checkpoint and either
  fix it in the owning workstream or create a named follow-up only after user
  approval.
- No commits are allowed unless the user explicitly requests a commit.

## Final Acceptance Checklist

- [ ] All V3 domain objects persist and serialize through explicit schemas.
- [ ] `/api/v1/acquisition/*` routes exist and are contract-tested.
- [ ] Every acquisition list route enforces pagination, default limit, maximum
  limit, stable ordering, tenant/user isolation, and redacted serialization.
- [ ] CapabilityGap, ExplorationRun, Recommendation, Proposal, Target,
  Verification, Journal, RuntimePlanningIssue, and CredentialConnection flows
  are durable and user-private.
- [ ] `ACQUISITION_ENABLED=false` preserves base chat, V2 Inbox, Workers, file
  tools, and normal Agent execution while showing clear disabled acquisition
  API/UI state.
- [ ] Gap creation uses normalized dedupe keys, database upsert/unique behavior,
  and concurrent occurrence count increments.
- [ ] Low-risk exploration can run automatically; high-risk exploration
  requires approval.
- [ ] Activation follows `drafted -> verification_requested -> verifying ->
  verified(snapshot_hash) -> activation_requested -> activation_approved(hash)
  -> activating -> activated`; approval before verification is impossible.
- [ ] Activation requires user approval, audit, unchanged activation snapshot
  hash, and valid credential generations.
- [ ] Composite Target activation has primary/secondary semantics,
  `partial_activation`, idempotent rollback, registry hide, permission revoke,
  runtime session cleanup, journal update, and audit update.
- [ ] MCP stdio runs only through isolated `core/tools/mcp_runtime`.
- [ ] MCP stdio and Browser Automation use separate images/services with
  healthchecks and cannot access Docker socket, backend filesystem, host
  filesystem, unapproved mounts, or non-allowlisted networks.
- [ ] Generic API tool runtime enforces host, redirect, private network,
  credential, byte-cap, content-type, retry/timeout, rate-limit, idempotency,
  and confirmation policy.
- [ ] Workspace Connector owns approved local/workspace path mapping.
- [ ] Workspace Connector mount bundles reach sandbox-proxy and code-as-action
  without raw host paths.
- [ ] Browser Automation target runs through isolated runtime with traces,
  profiles, network policy, resource caps, and confirmation gates.
- [ ] Browser Automation forbids captcha, paywall, login bypass, and
  unauthorized automation; trace, screenshot, and cookie redaction are tested.
- [ ] Worker, Skill, and Memory activation targets verify, activate, and
  rollback through existing V2 owners while V3 owns snapshot, approval, audit,
  permission, and rollback evidence.
- [ ] Development patch proposal is evidence-only and cannot mutate runtime or
  repo state.
- [ ] Development patch proposal fails handoff when current git revision differs
  from base commit or the patch no longer applies.
- [ ] Agent runtime creates acquisition evidence from code-as-action success,
  useful failure, and missing capability signals.
- [ ] RuntimePlanningIssue is owned by `core/planning_issues` and separates
  planner misses from true capability gaps.
- [ ] Activated targets update the per-user tool manifest; rollback/revocation
  hide stale tools from next and resumed Agent runs.
- [ ] Acquisition analysis uses durable bounded outbox claims, leases, retries,
  timeout metrics, and idempotency.
- [ ] Credential material never appears in Journal, SSE, audit, artifacts,
  browser traces, logs, or metrics labels.
- [ ] V2 Memory/Skill/Worker integration remains intact and only receives
  accepted V2-compatible outcomes.
- [ ] Frontend acquisition UI preserves existing visual style, scroll, sidebar
  actions, Settings navigation, and right panel behavior.
- [ ] Frontend acquisition UI shows problem, cause, risk, next step, recovery,
  separate exploration/activation approvals, and rollback visibility.
- [ ] Full backend tests, frontend lint/build, local Docker smoke, eval, and
  browser QA pass.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not-run | Optional; V3 product direction was already settled through prior brainstorming/spec work. |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | unavailable | Not run in this pass; previous outside voice path had `codex.exe` access-denied, and this Windows shell has broken WSL bash. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 3 issues found and patched: exact acquisition SSE event-name contract, exact acquisition metric-name contract, and missing Worker/Skill/Memory activation target task. 0 critical gaps remain. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not-run | Not required before implementation because this pass did not approve restyling; plan explicitly preserves existing frontend style and adds browser style/scroll regression checks. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not-run | Optional; implementation commands remain Docker-based and no host Python/Node runtime is required. |

- **UNRESOLVED:** 0.
- **VERDICT:** ENG CLEARED. The V3 execution plan is ready to enter Subagent-Driven implementation, with full V3 scope preserved and no known plan-level blockers.
- **NOT IN SCOPE CONFIRMED:** frontend restyling, marketplace/team-shared publishing, silent production self-modification, universal shared MCP/Browser runner, and host Python/Node verification.
- **WHAT ALREADY EXISTS CONFIRMED:** V2 Capability Candidate/outbox, Memory, Skill, Worker, audit, confirmation, sandbox proxy, file tools, eval runner, and Windows browser QA are reused through explicit seams.
