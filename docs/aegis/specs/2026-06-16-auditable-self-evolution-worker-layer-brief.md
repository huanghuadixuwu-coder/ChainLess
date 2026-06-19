# Auditable Self-Evolution Worker Layer Spec Brief

Status: Draft for user review
Type: Spec Brief / Product Architecture
Created: 2026-06-16
Parent refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- User-approved product direction on 2026-06-16:
  `Chainless = private-deployable proactive AI Worker platform`

## TaskIntentDraft

Outcome: add a product and architecture layer that turns successful one-off
agent conversations into auditable, reusable, schedulable, and versioned private
AI Workers.

Goal: a user can complete a useful task in chat, inspect what happened, save the
task as a Worker, adjust its inputs/tools/delivery, run it again manually, and
optionally schedule it. The system may suggest Worker or Skill creation, but
production behavior changes require explicit user approval and verification.

Success evidence:
- A successful chat run can be promoted to a draft Worker without losing the
  prompt, selected attachments, tool permissions, output artifacts, delivery
  target, and run trace.
- A Worker can be run manually and produce a new run record with inputs, tool
  events, artifacts, status, error details, and delivery result.
- A Worker can be scheduled through the existing proactive runtime without
  turning the schedule itself into the Worker source of truth.
- A Worker can be versioned, disabled, rolled back, and compared against a prior
  version.
- A Worker proposal or upgrade cannot become active silently. It must be
  reviewed, accepted, and pass the required verification gate.

Stop condition: the design is accepted when Worker, Memory, Skill, Agent,
Artifact, and Proactive Task ownership boundaries are explicit enough for a
follow-up implementation plan.

Non-goals:
- Do not implement autonomous self-modifying production behavior.
- Do not make Skill Precipitation fully automatic without user review.
- Do not replace existing Memory, Skill, Agent, Artifact, or Proactive Task
  systems.
- Do not redesign the frontend visual style, sidebar, chat layout, or settings
  aesthetic.
- Do not introduce a marketplace or public template ecosystem in this slice.
- Do not claim vertical product-market fit from this feature alone.

## BaselineReadSetHint

Authority refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `PROBLEM_TODO_LIST.md`
- `AGENTS.md`

Current implementation refs:
- `backend/app/models/memory.py`
- `backend/app/models/skill.py`
- `backend/app/models/agent.py`
- `backend/app/api/v1/proactive.py`
- `backend/app/core/proactive/scheduler.py`
- `backend/app/api/v1/conversations.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/artifacts/service.py`
- `frontend/src/components/settings/skills-section.tsx`
- `frontend/src/components/settings/proactive-section.tsx`
- `frontend/src/components/chat/preview-panel.tsx`
- `frontend/src/components/chat/file-artifact-list.tsx`
- `frontend/src/stores/platform-store.ts`
- `frontend/src/stores/chat-store.ts`

## Product Model

Chainless should keep four distinct product concepts:

- Memory: remembers knowledge, preferences, facts, project context, and
  references.
- Skill: remembers a method, habit, heuristic, instruction, trigger, or
  playbook. It may inform future runs, but it is not itself a scheduled job.
- Worker: remembers one executable job. It has inputs, an execution prompt,
  tool permissions, expected outputs, delivery settings, versions, and run
  history.
- Proactive Task: schedules or triggers a Worker. It is a runtime trigger, not
  the Worker definition.

The core product loop is:

```text
one successful chat task
  -> run trace and artifacts
  -> save as draft Worker
  -> user reviews inputs/tools/delivery
  -> verify Worker
  -> activate Worker
  -> manual or scheduled runs
  -> feedback and run history
  -> proposed Worker or Skill improvement
  -> user approval and versioned upgrade
```

## ImpactStatementDraft

Affected product layers:
- Chat: add a non-intrusive "Save as Worker" path after successful runs.
- Preview/Files/Terminal: run trace and artifacts become evidence for Worker
  creation.
- Settings: add Worker management without changing the existing visual style.
- Proactive: schedule Workers instead of storing every job concept directly in a
  proactive prompt.
- Skills: remain method-level metadata in this slice; future Skill
  Precipitation can use Worker run evidence as source material.
- Memory: remains knowledge-level context; Worker creation may optionally
  create or reference Memory, but cannot treat Memory as executable logic.

Affected backend layers:
- Add a Worker model and Worker version model.
- Add Worker run records, or map runs to existing artifact/audit owners through
  an explicit Worker run owner.
- Add APIs for Worker draft creation, activation, manual run, schedule binding,
  disable, rollback, and history.
- Add verification gates before activation or version upgrade.
- Keep tenant isolation and admin/member authorization aligned with existing
  Settings-backed resources.

Compatibility boundaries:
- Existing proactive tasks continue to work during migration.
- Existing passive Skill APIs remain compatible.
- Existing Memory behavior remains compatible.
- Existing chat execution remains available without forcing Worker creation.
- UI changes must reuse current components and style language.

## Product Risk Lens

Value: this turns Chainless from a general chat agent into a platform that
discovers reusable enterprise work from real usage. It lets the product stay
general while still accumulating repeatable workflows.

Non-goals: this is not a fully autonomous self-improving agent. The product must
stay auditable and user-controlled.

Trade-offs: a new Worker object is more implementation work than reusing
Proactive Task, but it prevents conflating task definition, schedule, execution
history, and method memory.

Decision needed: accept Worker as the canonical source of truth for executable
work.

## Architecture Integrity Lens

Invariant: an executable job must have one canonical owner. The schedule, agent,
memory, skill, and artifacts may support the job, but none of them should become
the hidden source of truth for the job definition.

Canonical owner / contract:
- Worker owns executable job definition.
- WorkerVersion owns immutable execution contract snapshots.
- WorkerRun owns each execution attempt and its status.
- Proactive Task owns schedule/trigger only.
- Skill owns method metadata only.
- Memory owns knowledge only.
- Artifact owns durable files and diffs only.
- Agent owns model/persona/tool defaults only.

Responsibility overlap today:
- Proactive Task stores prompt, agent id, authorized tools, trigger, and channel.
  This is enough for scheduling, but too narrow to be a reusable product object.
- Skill stores passive metadata and trigger terms, but intentionally does not
  execute.
- Conversation history and artifacts contain evidence, but not a stable
  reusable task contract.

Higher-level simplification: create Worker as the source-of-truth layer and let
existing systems reference it. Do not grow Proactive Task into a generic Worker
by adding more fields.

Retirement / falsifier:
- If the implementation requires proactive task records to contain the only copy
  of Worker prompt/tool/delivery behavior, the design has failed.
- If Skill execution behavior becomes active without versioning and user
  approval, the design has failed.
- If a Worker upgrade can silently change production behavior without review,
  the design has failed.

Verdict: proceed with a new Worker owner.

## Baseline Role Alignment

Product / Requirement Baseline: Chainless is being repositioned as a
private-deployable proactive AI Worker platform. It should turn repeated
knowledge work into private Workers that can be observed, corrected, reused, and
scheduled.

Architecture / Runtime Boundary Baseline: existing Memory, Skill, Agent,
Artifact, and Proactive Task owners are valid but incomplete for the new product
model.

Result: missing-authority.

Scope: both requirements and architecture.

Next action: write an implementation plan for the Worker layer after this spec
is accepted.

## Options Considered

### Option A: Reuse Proactive Task as Worker

Summary: expand proactive task records until they can represent reusable work.

Pros:
- Fastest first implementation.
- Reuses the scheduler and run-history path.
- Avoids a new top-level Settings section at first.

Cons:
- Confuses schedule with executable work.
- Makes manual runs, versioning, and templates awkward.
- Risks turning Redis-backed proactive state into a product source of truth.

Verdict: reject for long-term architecture.

### Option B: Add Worker as a First-Class Object

Summary: Worker is the executable job definition. Proactive Task schedules it,
Skill can inform it, Memory can provide context, Artifact provides files, and
Agent executes it.

Pros:
- Clean product language and ownership.
- Supports manual run, scheduled run, versioning, rollback, feedback, and
  template evolution.
- Fits the "private AI Worker platform" positioning.

Cons:
- Requires new model/API/UI.
- Requires migration or compatibility bridge for existing proactive tasks.
- Needs careful verification so "self-evolution" remains auditable.

Verdict: adopt.

### Option C: Save as Skill First, Worker Later

Summary: implement conversation-to-skill precipitation first and later add
execution/scheduling.

Pros:
- Leverages existing skill UI and trigger matching.
- Feels close to the original "experience to skill" concept.

Cons:
- Skill is method-level, not job-level.
- Existing reconciliation explicitly keeps Skill Precipitation as V2.
- Risks creating active behavior from passive metadata without enough audit
  structure.

Verdict: defer. Worker run history can later become evidence for Skill
Precipitation.

## Chosen Direction

Adopt Option B: Worker as a first-class object.

Definitions:
- Worker: a reusable executable job definition.
- WorkerVersion: immutable version of a Worker execution contract.
- WorkerRun: one execution attempt.
- WorkerProposal: a draft generated from conversation or run evidence. It has
  no production effect until accepted.
- WorkerSchedule: a binding between WorkerVersion and a trigger. This may be
  implemented through the existing Proactive Task runtime.

## Requirements

### R1. Save a successful conversation as a Worker draft

The user can select a successful conversation or assistant run and create a
draft Worker.

The draft must capture:
- name
- description
- source conversation id
- source message ids or run id
- execution prompt
- input contract
- required or optional attachment references
- authorized tool names
- selected agent/provider
- expected artifact outputs
- delivery target, if known
- schedule suggestion, if known
- source evidence summary

The draft must not become active automatically.

### R2. Worker activation requires explicit review

Before activation, the user must see:
- prompt
- tool permissions
- input contract
- memory usage policy
- delivery target
- schedule, if any
- recent source evidence
- risk warnings

Activation must create WorkerVersion `1`.

### R3. Worker versions are immutable

After activation, changing prompt, input contract, tools, memory policy,
delivery, or schedule-affecting behavior creates a new draft version.

The user can:
- compare versions
- activate a new version after verification
- rollback to a previous version
- disable the Worker

### R4. Worker runs are observable

Each run must record:
- worker id and version id
- trigger type: manual, cron, event, delayed, or api
- status: queued, running, succeeded, failed, blocked, cancelled
- started and ended timestamps
- input payload summary
- attachment ids
- tool calls
- tool errors
- generated artifacts
- delivery result
- verification result, if applicable
- safe error message

Run records must be tenant-scoped and secret-free.

### R5. Proactive tasks schedule Workers

Proactive Task should become a trigger binding for Worker execution.

The schedule must reference:
- Worker id
- WorkerVersion id or active version policy
- trigger config
- channel config reference

The schedule must not be the only owner of prompt, tools, or output contract.

### R6. Skill remains method-level

Worker creation may suggest Skill creation only when the source run contains a
generalizable method, not just a specific job.

Skill suggestions must remain draft proposals until reviewed.

Examples:
- Good Skill candidate: "When summarizing competitor updates, include source,
  impact, confidence, and next action."
- Bad Skill candidate: "Every Monday, summarize competitor updates and send to
  Feishu." That is a Worker.

### R7. Memory remains knowledge-level

Worker creation may reference or create Memory only for durable knowledge, not
for executable control flow.

Examples:
- Good Memory candidate: "The sales team prefers weekly summaries in Chinese."
- Bad Memory candidate: "Call web_search, then file_write, then send Feishu."
  That belongs in Worker or Skill.

### R8. Self-evolution is proposal-first

The system may propose:
- new Worker from a successful run
- Worker version upgrade from repeated manual corrections
- Skill from a recurring method
- Memory from stable user preference or project fact

The system must not:
- activate a Worker silently
- upgrade a Worker silently
- grant additional tool permissions silently
- schedule a Worker silently
- deliver externally without user-approved channel configuration

### R9. Verification gates block unsafe upgrades

A Worker activation or version upgrade should require a verification result
appropriate to the Worker risk level.

Minimum verification levels:
- text-only, no tools: dry-run preview is enough
- safe tools only: test run must succeed
- risky tools or file writes: test run must produce expected artifact or status
- destructive tools or external delivery: explicit confirmation plus test run
- scheduled/external delivery: channel test or dry-run delivery evidence

Failed verification keeps the Worker draft inactive.

### R10. Product UI preserves current style

The feature should use existing visual language:
- Chat action: "Save as Worker"
- Settings section: "Workers"
- Worker detail: Overview, Versions, Runs, Schedule, Inputs, Tools, Delivery
- Run detail: trace, terminal/tool output, files, errors, delivery

No frontend style redesign is allowed by this spec.

## Suggested Data Model

Exact schema is implementation-plan work, but the model should include these
owners:

```text
workers
- id
- tenant_id
- name
- description
- active_version_id
- enabled
- created_by_user_id
- source_conversation_id
- metadata
- created_at
- updated_at

worker_versions
- id
- worker_id
- version_number
- status: draft | active | archived | failed_verification
- prompt
- input_schema
- tool_policy
- memory_policy
- output_contract
- delivery_policy
- agent_id
- llm_provider
- verification_status
- verification_summary
- source_evidence
- created_at
- activated_at

worker_runs
- id
- worker_id
- worker_version_id
- tenant_id
- trigger_type
- status
- input_summary
- attachment_artifact_ids
- output_artifact_ids
- tool_trace
- delivery_result
- error_code
- error_message
- started_at
- ended_at

worker_proposals
- id
- tenant_id
- source_type: conversation | run | feedback | manual
- source_id
- proposal_type: worker | worker_version | skill | memory
- payload
- status: draft | accepted | rejected | expired
- created_at
- reviewed_at
```

## API Surface Sketch

The implementation plan should refine exact request and response shapes.

```text
GET    /api/v1/workers
POST   /api/v1/workers
GET    /api/v1/workers/{worker_id}
PATCH  /api/v1/workers/{worker_id}
DELETE /api/v1/workers/{worker_id}

POST   /api/v1/workers/from-conversation
POST   /api/v1/workers/{worker_id}/versions
POST   /api/v1/workers/{worker_id}/versions/{version_id}/verify
POST   /api/v1/workers/{worker_id}/versions/{version_id}/activate
POST   /api/v1/workers/{worker_id}/rollback

POST   /api/v1/workers/{worker_id}/runs
GET    /api/v1/workers/{worker_id}/runs
GET    /api/v1/worker-runs/{run_id}

POST   /api/v1/workers/{worker_id}/schedule
DELETE /api/v1/workers/{worker_id}/schedule/{schedule_id}

GET    /api/v1/worker-proposals
POST   /api/v1/worker-proposals/{proposal_id}/accept
POST   /api/v1/worker-proposals/{proposal_id}/reject
```

## Open Questions for Implementation Planning

These should be answered in the detailed plan:

1. Should Worker execution reuse the conversation chat stream owner, or have a
   separate Worker execution service that calls the agent engine directly?
2. Should Worker schedules use active-version policy or pin an exact version?
3. How much of Worker run trace should be stored as JSONB versus normalized
   artifact/audit references?
4. Should member users be allowed to create draft Workers, or only admins?
5. How should failed runs feed back into Worker improvement proposals?
6. Which verification gates are mandatory for V1 versus later maturity?

## Acceptance Criteria

- Worker is documented as the canonical owner for executable reusable work.
- Proactive Task is documented as schedule/trigger only.
- Skill is documented as method-level only.
- Memory is documented as knowledge-level only.
- Worker activation and upgrade are proposal-first and user-approved.
- Worker versions are immutable after activation.
- Worker runs have observable trace and artifact evidence.
- Existing V1 behavior remains compatible.
- No frontend style redesign is required or authorized.

## Spec Self-Review

Placeholder scan: no TODO/TBD placeholders remain.

Internal consistency: Worker owns executable work; Proactive schedules Worker;
Skill and Memory support but do not own execution.

Scope check: this spec defines product and architecture boundaries only. It does
not specify exact migrations, UI component implementation, or final API schemas.

Ambiguity check: "self-evolution" is explicitly proposal-first and auditable,
not autonomous production mutation.

Boundary check: durable owner boundaries, non-goals, compatibility boundaries,
and verification gates are explicit enough for `aegis:writing-plans`.
