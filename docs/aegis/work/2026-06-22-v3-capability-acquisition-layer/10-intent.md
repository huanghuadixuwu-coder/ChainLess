# V3 Capability Acquisition Layer Implementation Intent

Date: 2026-06-22

## Requested Outcome

Execute `docs/aegis/plans/2026-06-22-v3-capability-acquisition-layer-execution-plan.md`
using subagent-driven development. Preserve the full V3 scope and start with
Workstream 1, because later acquisition lifecycle, runtime targets, API, UI, and
QA depend on persisted domain objects, migrations, and typed contracts.

## Scope

- Implement V3 Capability Acquisition Layer according to the approved V3 spec
  and execution plan.
- Use fresh subagents for bounded implementation/review slices.
- Keep all verification Docker-based; do not rely on host Python or host Node.
- Reuse existing V2 Memory, Skill, Worker, Capability Candidate, outbox, audit,
  confirmation, sandbox, artifact, eval, and browser QA foundations through
  explicit seams.

## Non-Goals

- No frontend restyling or visual redesign.
- No marketplace or team-shared capability publishing.
- No silent production self-modification, install, commit, push, deploy, or
  runtime patch application.
- No commits unless the user explicitly requests one.
- No host Python/Node runtime usage for verification.

## Baseline Read Set Hint

- `docs/aegis/specs/2026-06-20-v3-capability-acquisition-layer-design.md`
- `docs/aegis/plans/2026-06-22-v3-capability-acquisition-layer-execution-plan.md`
- `backend/app/models/capability.py`
- `backend/app/models/memory.py`
- `backend/app/models/skill.py`
- `backend/app/models/worker.py`
- `backend/app/core/capabilities/outbox.py`
- `backend/app/core/capabilities/service.py`
- `backend/app/api/contracts.py`
- `backend/app/api/pagination.py`

## Impact Statement Draft

V3 changes Chainless from a fixed-tool Agent platform into a private AI Worker
OS that can identify capability gaps, explore safe temporary solutions, propose
durable capabilities, verify activation snapshots, and activate approved
targets with audit, rollback, and user-visible control.

## Risk Hints

- Large schema surface can create owner drift if V3 state leaks into V2
  CapabilityCandidate metadata.
- Activation state machine and snapshot hash must be modeled explicitly before
  runtime targets are built.
- Tenant/user isolation and redaction must be present in schemas from the first
  slice, not added after API/UI work.
- Existing untracked V3 spec/plan files are the current execution authority.
