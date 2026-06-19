# Chainless V2 Capability Operating Layer Design Spec

Status: Approved
Type: Design Spec / Product Architecture
Created: 2026-06-16
Approved: 2026-06-17

Parent refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-16-auditable-self-evolution-worker-layer-brief.md`

Relationship to the Worker brief:
- The Worker brief remains valid as a narrower sub-direction.
- This spec supersedes its product framing where the brief over-emphasized
  manual or scheduled Worker reuse.
- In this spec, Worker is an Agent-callable executable capability. Manual run
  and schedule are optional triggers, not the reason Worker exists.

## 1. TaskIntentDraft

Outcome:
Create Chainless V2's Capability Operating Layer: a personal, auditable layer
that lets the Agent turn successful chat tasks into durable private capabilities,
then use those capabilities in future planning.

Goal:
After a user completes useful work in chat, Chainless can suggest that parts of
the experience should become Memory, Skill, or Worker. Suggestions enter a
personal Capability Inbox, remain there until the user acts on them, and only
become active after explicit user acceptance. In future tasks, the Agent can
soft-merge relevant Memory, Skill, and Worker context, choose a matching Worker
when confidence and risk allow, and continue learning from success or failure.

Success evidence:
- A successful chat run can generate private Capability Candidates for Memory,
  Skill, and Worker through a rule-first plus LLM analyzer pipeline.
- Candidates are visible as lightweight chat hints and permanently available in
  the user's Capability Inbox until accepted, dismissed, merged, archived, or
  muted.
- Accepted Memory affects later relevant responses as knowledge with source
  evidence.
- Accepted Skill affects later task method or output shape without becoming an
  executable job.
- Accepted Worker becomes an Agent-callable executable capability with input
  schema, preconditions, tool permissions, output contract, risk level, versions,
  run history, and failure/fallback behavior.
- Agent planning can combine Memory, Skill, and Worker rather than choosing one
  category exclusively.
- Low-risk, high-confidence Worker matches can be invoked by the Agent with a
  visible lightweight notice. Risky or external-effect Worker calls require
  confirmation.
- Worker failure transparently falls back to normal Agent execution when safe,
  lowers future match confidence, and creates an improvement candidate.
- Worker success only creates improvement candidates when there is user feedback
  or a strong runtime signal, avoiding noisy self-suggestions.
- System hard guards enforce tenant/user isolation, input schema, tool
  allowlists, confirmation gates, and audit boundaries regardless of model
  reasoning.

Stop condition:
This design is ready for implementation planning when the product loop, data
owners, runtime decision flow, conflict model, policy guards, hooks, UI
placement, and non-goals are explicit enough to produce a detailed V2 execution
plan without re-litigating the architecture.

Non-goals:
- Do not build team-wide capability publishing or approval in V2 phase 1.
- Do not build a full administrator Managed Settings UI in V2 phase 1.
- Do not let the LLM automatically write active Memory, Skill, or Worker without
  user acceptance.
- Do not let a Worker run create external side effects without required
  confirmation and authorization.
- Do not introduce a public marketplace, template store, or third-party plugin
  system in this phase.
- Do not redesign the existing frontend style, chat layout, sidebar behavior,
  scroll behavior, or visual language.
- Do not treat schedule as part of the Worker definition. Schedule is a trigger
  that may call a Worker.
- Do not treat a successful fallback result as proof that the Worker succeeded.

## 2. BaselineReadSetHint

Authority refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-16-auditable-self-evolution-worker-layer-brief.md`
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

Authority facts:
- V1 already defines layered instruction merging and explicitly separates
  cognitive priority from hard constraints such as permissions, hooks, and
  managed settings.
- V1 already includes Memory, passive Skill metadata, tools, sandbox execution,
  proactive runtime, artifact traces, eval, and audit-like evidence.
- Skill precipitation was historically deferred, but V2 now intentionally
  revisits experience-to-capability learning under explicit user approval.
- W12 makes artifact/workspace/file-task closure a trust foundation for
  reusable Worker execution.

## 3. ImpactStatementDraft

Affected product layers:
- Chat: show non-blocking capability hints after successful runs and lightweight
  Worker-use notices when the Agent invokes an existing Worker.
- Right panel: add a Capability Inbox tab for current-run candidates, recent
  pending suggestions, Worker feedback, and quick actions.
- Settings: add a complete personal capability management surface for Inbox,
  Memory, Skills, Workers, versions, runs, enable/disable, rollback, and soft
  delete.
- Agent runtime: add capability retrieval, soft merge, Worker matching, Worker
  invocation, fallback handling, and learning signals.
- Memory: continue as knowledge/fact/preference context, now with explicit
  candidate acceptance and source evidence.
- Skill: continue as method/heuristic/playbook metadata, now with accepted
  candidate creation and planning influence.
- Worker: add a first-class Agent-callable executable capability, not merely a
  manual task or schedule.
- Proactive runtime: schedule and event triggers may call Workers, but schedule
  is not Worker source of truth.
- Tool system: tools remain atomic capabilities; Workers compose tools and
  Agent steps under a governed contract.

Affected backend layers:
- Candidate generation service: rule-first filter plus LLM analyzer.
- Capability Inbox owner: durable personal candidate records and lifecycle.
- Capability retrieval service: Memory, Skill, and Worker match retrieval for
  Agent planning.
- Worker owner: Worker, WorkerVersion, WorkerRun, match feedback, soft delete,
  and version activation.
- Policy/guard owner: input schema checks, allowed tool checks, risk
  confirmation, isolation checks, and audit hooks.
- Hook owner: internal before/after lifecycle hooks for Worker, tool, failure,
  and candidate events.

Compatibility boundaries:
- Existing chat behavior must keep working without requiring the user to adopt
  the Capability Inbox.
- Existing Memory and passive Skill APIs remain compatible.
- Existing proactive tasks remain compatible; migration to Worker-triggered
  schedules must be explicit and non-destructive.
- Existing artifact and file-task contracts from W12 remain the source of truth
  for file input/output traceability.
- Existing frontend visual style must be preserved. UI work may add controls
  and tabs but must not restyle the product.

## 4. Product Model

Chainless V2 should use these product definitions:

- Memory: knowledge, preference, fact, project context, or reference that helps
  the Agent understand the user or task.
- Skill: method, habit, heuristic, instruction, trigger, or playbook that helps
  the Agent decide how to perform a class of tasks.
- Worker: a user-approved executable capability that the Agent can match and
  invoke. It has purpose, input schema, preconditions, allowed tools, output
  contract, risk level, examples, failure policy, versions, run history, and
  feedback.
- Capability Candidate: an inactive suggestion that may become Memory, Skill,
  or Worker after user acceptance.
- Capability Inbox: the user's personal permanent queue of inactive
  suggestions.
- WorkerRun: one attempt to invoke a Worker, whether triggered by Agent
  planning, explicit user request, schedule, event, API, or manual test.
- Schedule: an optional trigger that can call a Worker. It is not part of the
  Worker definition.
- Channel: an optional delivery target. It is not part of the Worker definition
  unless a WorkerVersion explicitly requires a delivery output contract.

Core product loop:

```text
Chat Run succeeds or fails with useful evidence
  -> Rule filter decides whether analysis is worthwhile
  -> LLM analyzer drafts Memory / Skill / Worker candidates
  -> Deduplicate and merge similar candidates
  -> Chat shows a lightweight hint
  -> Personal Capability Inbox retains the candidate permanently
  -> User accepts, edits, dismisses, snoozes, mutes, merges, or archives
  -> Accepted capabilities influence future Agent planning
  -> Future Worker success/failure creates feedback signals
  -> User-approved versions improve the capability over time
```

## 5. First-Principles Review

First Principle:
The system must convert useful experience into future Agent capability without
making unreviewed production behavior changes.

Non-negotiables:
- User acceptance is required before a candidate becomes active capability.
- Agent autonomy cannot bypass permissions, risk gates, input schema, tool
  allowlists, tenant/user isolation, or external-delivery confirmation.
- Memory, Skill, and Worker must remain distinct owners.
- Worker failure and fallback must be transparent.
- Frontend style must not be redesigned.

Assumptions to drop:
- Worker is not primarily a manual-run button.
- Worker is not inherently a scheduled task.
- Skill is not an executable job.
- Memory is not a hidden workflow store.
- Inbox is not a team approval queue in V2 phase 1.

Smallest sufficient path:
Build a personal Capability Inbox, a rule-first plus LLM candidate generator,
and Agent planning support for accepted Memory, Skill, and Worker. Keep team
publishing and full administrator managed settings out of phase 1.

Escalation signal:
If implementation requires candidates to become active without user acceptance,
or requires schedule/proactive task to become Worker source of truth, return to
design review.

## 6. Product Risk Lens

Value:
This gives Chainless a differentiating product loop: the Agent visibly learns
from real work and later reuses approved capabilities instead of starting from
zero every conversation.

Non-goals:
Do not compete with workflow builders by making users design flows up front.
Do not compete with generic chat by hiding all learning. The product value is
visible, audited capability growth.

Trade-offs:
Personal Inbox first lowers enterprise governance complexity, but delays team
capability sharing. Rule-first generation reduces cost and noise, but requires
careful signal design. Worker auto-invocation creates product magic, but needs
transparent notices and hard guards.

Decision:
Adopt personal Capability Operating Layer as V2 phase 1. Defer team publishing,
full admin policy UI, and external marketplace.

## 7. Baseline Role Alignment

Product / Requirement Baseline:
Chainless is a private-deployable Agent platform. V2 should make it a personal
AI work capability system where Memory remembers knowledge, Skill remembers
methods, and Worker remembers Agent-callable executable work.

Architecture / Runtime Boundary Baseline:
Existing V1 owners for Memory, Skill metadata, Agent execution, tools,
artifacts, proactive tasks, audit, and settings remain valid but incomplete.
V2 adds a Capability Inbox owner and a Worker owner.

Result:
missing-authority

Scope:
both requirements and architecture

Next action:
After user review, write a detailed implementation plan that introduces
Capability Inbox, candidate generation, Worker runtime, policy guards, hooks,
and UI surfaces without changing frontend style.

## 8. Architecture Integrity Lens

Invariant:
Accepted capabilities may influence future Agent behavior, but inactive
candidates must not. Every active behavior must have one canonical owner and a
traceable review path.

Canonical owner / contract:
- Capability Inbox owns inactive candidate suggestions.
- Memory owns accepted knowledge/facts/preferences.
- Skill owns accepted method/playbook guidance.
- Worker owns accepted executable capabilities.
- WorkerVersion owns immutable execution contracts.
- WorkerRun owns execution attempts and trace.
- Policy Guard owns hard runtime constraints.
- Hook Runtime owns internal lifecycle interception.
- Proactive Task owns schedule/event/delayed trigger binding only.
- Artifact owns durable file output/input evidence.

Responsibility overlap:
- Do not grow proactive tasks into Worker definitions.
- Do not let Skill store active execution flow.
- Do not copy Memory or Skill into Worker as hidden stale facts. Workers may
  reference them or accept current planning context.
- Do not let Inbox candidates alter planning before acceptance.

Higher-level simplification:
Use a Capability Operating Layer that sits above existing Memory, Skill, Worker,
tools, artifacts, and proactive runtime rather than embedding capability
learning separately in each subsystem.

Retirement / falsifier:
- If Agent can use an unaccepted candidate, the design fails.
- If Worker auto-invocation can bypass hard guards, the design fails.
- If schedule contains the only copy of Worker behavior, the design fails.
- If user A's private capability affects user B, the design fails.

Verdict:
Proceed with a new personal Capability Operating Layer and Worker owner.

## 9. Chosen Decisions

The following decisions are accepted for this V2 design:

1. V2 direction is Capability Operating Layer, not Worker-only layer.
2. Capability generation starts after successful or evidence-rich chat runs.
3. The system proactively suggests Memory, Skill, and Worker candidates.
4. Suggestions enter a personal Capability Inbox.
5. Chat shows lightweight hints; the full Inbox lives in Settings.
6. The Inbox is personal only in phase 1.
7. Candidates remain permanently until the user acts on them.
8. Candidate generation uses a hybrid pipeline: rules cheaply decide whether
   LLM analysis is worthwhile; LLM drafts classification and content.
9. Memory, Skill, and Worker are all supported in V2 phase 1.
10. Worker is Agent-callable executable capability, not primarily manual reuse.
11. Low-risk, high-confidence Worker matches can be invoked automatically with a
    visible lightweight notice.
12. Uncertain Worker matches should not interrupt the user; normal Agent
    execution proceeds and improvement/create suggestions may be generated
    afterward.
13. Worker improvements create new versions; old versions remain available for
    rollback.
14. Worker delete is supported, including through natural language, but active
    or historical Workers require explicit confirmation and should be soft
    deleted.
15. Worker match uses semantic similarity, input schema fit, precondition fit,
    risk, recent feedback, and success/failure history.
16. Worker failure should transparently fall back to normal Agent execution when
    safe, lower future match confidence, and generate an improvement candidate.
17. Worker success raises confidence. It only generates improvement candidates
    when user feedback or strong runtime evidence exists.
18. Agent planning can combine Memory, Skill, and Worker in one plan.
19. Conflict handling uses Claude Code-style soft merge plus system-level hard
    guards.
20. V2 phase 1 includes minimal hard guards plus internal hooks, but not a full
    administrator Managed Settings UI.

## 10. Capability Candidate Generation

Candidate generation has two stages.

### 10.1 Rule Filter

The rule filter is cheap and deterministic. It decides whether the run deserves
LLM analysis. It does not create active capabilities.

Trigger signals:
- User says terms like "remember", "next time", "always", "never again",
  "every time", "daily", "weekly", "in the future", or equivalents.
- The run uses a meaningful tool chain such as search, file, code, browser,
  channel delivery, MCP, or sandbox.
- The run produces an artifact such as report, table, file, diff, card, or
  structured output.
- The user corrects output format, reasoning standard, data source, or method.
- Similar tasks repeat within recent conversation history.
- A tool failure exposes a concrete capability gap such as weather, booking,
  search, file read, or browser automation failure.
- The Agent performed a fallback that succeeded after a Worker or tool failed.

Non-trigger examples:
- Pure greeting.
- One-off factual answer with no preference, method, tool chain, or output
  contract.
- Ambiguous brainstorm where no stable future behavior can be inferred.

### 10.2 LLM Analyzer

The LLM analyzer only runs when the rule filter matches. It outputs structured
candidate drafts, not active capabilities.

Required analyzer output:

```json
{
  "should_suggest": true,
  "candidate_type": "memory | skill | worker",
  "title": "short user-facing title",
  "proposal": "suggested capability content",
  "reason": "why this should be saved",
  "confidence": 0.86,
  "risk_level": "low | medium | high | destructive | external",
  "source_evidence": ["short evidence item"],
  "source_run_id": "run id",
  "dedupe_key": "stable semantic key"
}
```

Analyzer classification rules:
- Memory candidate: durable fact, preference, project context, or reference.
- Skill candidate: reusable method, judgment rule, output habit, or playbook.
- Worker candidate: executable work with input, steps/tools, output, and future
  invocation value.
- Tool Contract Gap: internal diagnostic when failure shows a missing or weak
  tool contract. It may create an Inbox candidate for admins later, but V2
  phase 1 does not expose it as a fourth user-facing capability category.

### 10.3 Deduplication and Noise Control

The system must avoid Inbox spam:
- Similar candidates merge into one canonical candidate with multiple evidence
  links.
- Chat light hints show at most once per candidate pattern.
- Dismissed candidate patterns can be muted.
- Low-confidence candidates are grouped or de-emphasized in Inbox.
- Pure success does not create improvement candidates unless extra learning
  signals exist.

## 11. Capability Inbox

Capability Inbox is a personal durable queue. It owns inactive candidates only.

Scope:
- Candidates are scoped by `tenant_id` and `user_id`.
- In V2 phase 1, candidates are private to the creating user.
- Team/tenant publishing is deferred.

Retention:
- Candidates are permanent until user action.
- The system may merge, archive, or mute patterns only according to user action
  or deterministic deduplication rules.
- No candidate may auto-expire in phase 1.

Candidate lifecycle:

```text
new
  -> seen
  -> accepted
  -> edited_accepted
  -> dismissed
  -> snoozed
  -> muted_pattern
  -> merged
  -> archived
```

Required candidate fields:
- `id`
- `tenant_id`
- `user_id`
- `candidate_type`
- `status`
- `title`
- `proposal`
- `confidence`
- `risk_level`
- `reason`
- `source_type`
- `source_conversation_id`
- `source_message_ids`
- `source_run_id`
- `source_artifact_ids`
- `source_worker_id`
- `source_worker_version_id`
- `source_evidence`
- `dedupe_key`
- `merged_into_candidate_id`
- `snoozed_until`
- `muted_pattern_key`
- `created_at`
- `updated_at`
- `reviewed_at`

Acceptance behavior:
- Accepting Memory writes a private Memory with source evidence.
- Accepting Skill writes a private Skill or Skill version/draft according to
  the implementation plan.
- Accepting Worker creates a Worker draft or WorkerVersion draft.
- Accepting a Worker improvement never overwrites an active Worker directly.
- Dismissing a candidate does not delete source conversation evidence.

## 12. Memory / Skill / Worker Boundaries

### 12.1 Memory

Memory remembers knowledge:
- User preference
- User fact
- Project context
- Stable reference
- External system pointer
- User correction that is purely factual

Memory must not:
- Store executable control flow.
- Grant tool permission.
- Schedule work.
- Override current user intent.

### 12.2 Skill

Skill remembers method:
- Output format rule
- Evaluation standard
- Reusable heuristic
- Playbook
- Trigger terms
- Preferred tool pattern at a method level

Skill must not:
- Own a full executable job.
- Schedule work.
- Deliver externally.
- Execute tools directly.
- Bypass Worker input schema or policy guards.

### 12.3 Worker

Worker remembers executable work:
- Purpose
- Input schema
- Preconditions
- Tool permissions
- Execution contract
- Output contract
- Risk level
- Examples
- Failure policy
- Versions
- Run history
- Match feedback

Worker is not:
- A schedule.
- A channel.
- A Memory store.
- A Skill note.
- A manually clicked macro only.

Worker is:
- A user-approved, Agent-callable executable capability.

## 13. Agent Planning With Capabilities

Agent planning uses a layered capability assembly flow:

```text
User request
  -> Retrieve relevant Memory
  -> Match relevant Skills
  -> Match relevant Workers
  -> Soft-merge context
  -> Build plan
  -> Policy/guard validation
  -> Execute tools and/or Worker
  -> Record trace
  -> Generate learning signals
```

Capabilities are not mutually exclusive. A plan may use:
- Memory for facts and preferences.
- Skill for method and output standards.
- Worker for executable template.

Example:

```text
User request:
"What is today's Wuxi weather?"

Memory:
- User lives in Wuxi.
- User prefers concise Chinese summaries.

Skill:
- Weather answers should include source and confidence.

Worker:
- Weather Summary Worker: city/date -> weather tool -> source check -> summary.

Plan:
Use Weather Summary Worker with city=Wuxi, date=today. Apply concise Chinese
style and include source/confidence.
```

## 14. Worker Invocation Contract

Worker is an Agent-callable executable capability.

### 14.1 Worker Required Contract

Every active Worker must define:
- `purpose`
- `input_schema`
- `preconditions`
- `tool_permissions`
- `output_contract`
- `risk_level`
- `examples`
- `failure_policy`
- `version`
- `owner_user_id`
- `enabled`
- `soft_deleted_at`

### 14.2 Worker Match Score

Worker matching should combine:

```text
match_score =
  semantic_similarity
+ input_schema_fit
+ precondition_fit
+ success_rate_signal
+ recent_positive_feedback
- risk_penalty
- recent_failure_penalty
- recent_negative_feedback
```

Implementation thresholds are planning details, but the design intent is:
- High confidence and low risk: Agent may invoke with a lightweight visible
  notice.
- High confidence and medium/high risk: Agent must request confirmation.
- Medium confidence: Agent should not interrupt; run normal Agent flow and
  possibly suggest Worker creation or improvement after completion.
- Low confidence: ignore the Worker for this request.

### 14.3 Invocation Visibility

Low-risk Worker calls are not silent. The chat stream should show a lightweight
notice:

```text
Using your "Weather Summary" Worker.
```

The notice should not block execution. It should provide access to trace details
when useful.

Medium-risk or cancellable Worker calls may show:

```text
I plan to use your "Invoice Review" Worker. You can cancel before it starts.
```

High-risk, destructive, external delivery, paid, or permission-sensitive Worker
calls require explicit confirmation.

### 14.4 Manual Run

Manual run exists for:
- Testing a Worker.
- Explicit user command to run a named Worker.
- Verification after editing.
- Debugging failure.

Manual run is not the main product meaning of Worker.

### 14.5 Schedule and Event Triggers

Schedule, delayed run, API call, and event trigger are optional ways to trigger
WorkerRun. They are not the Worker definition.

```text
Schedule / Event / API / Manual / Agent Match
  -> WorkerRun
```

## 15. Worker Lifecycle

Worker lifecycle:

```text
candidate
  -> draft
  -> verified
  -> active
  -> version draft
  -> active new version
  -> archived old version
  -> disabled
  -> soft_deleted
```

Rules:
- A Worker candidate is inactive.
- A Worker draft is inactive until verified and activated.
- Active WorkerVersions are immutable.
- Improvements create a new WorkerVersion draft.
- Activation requires user confirmation and appropriate verification.
- Rollback activates a prior version without deleting later versions.
- Disable removes Worker from auto-match but preserves history.
- Delete should be soft delete by default, preserving WorkerRun and audit
  history.
- Active or historical Worker delete requires explicit confirmation.
- Natural-language delete is allowed only as a confirmation flow starter.

Natural-language delete example:

```text
User:
"Delete my weather Worker."

Agent:
"I found 'Weather Summary'. Deleting it will remove it from future matching.
Historical runs will remain for audit. Confirm delete?"
```

## 16. Worker Failure, Fallback, and Learning

### 16.1 Failure Handling

Default behavior:
- Low-risk Worker failure may transparently fall back to normal Agent execution.
- Medium-risk failure may fall back only if fallback uses comparable or lower
  risk tools; otherwise ask the user.
- High-risk, external-effect, destructive, paid, compliance-sensitive, or
  permission-sensitive failure must stop and ask the user.

Fallback must be transparent:

```text
Your "Weather Summary" Worker failed because the weather tool returned no
source. I will continue with normal Agent execution.
```

Final response must not imply Worker success when fallback produced the result.

WorkerRun status examples:
- `succeeded`
- `failed`
- `failed_fallback_succeeded`
- `failed_fallback_failed`
- `blocked_by_policy`
- `cancelled`
- `needs_user_confirmation`

### 16.2 Failure Learning

When a Worker fails:
- Record failure step and reason.
- Lower future match confidence through recent failure penalty.
- Generate an improvement candidate when evidence is useful.
- If fallback succeeds, capture the fallback path as evidence but do not
  automatically rewrite Worker behavior.

Improvement flow:

```text
Worker failure
  -> Safe fallback succeeds
  -> Improve Worker Candidate
  -> User accepts
  -> New WorkerVersion draft
  -> Verify
  -> Activate
```

### 16.3 Success Learning

Worker success:
- Raises success confidence.
- Reduces recent failure penalty.
- Does not create an improvement candidate by default.

Success may create an improvement candidate only when:
- User explicitly says "next time", "always", "this was good", or similar.
- User corrects output or edits a generated artifact.
- Runtime evidence shows a clearly better tool path.
- Multiple successful runs show a stable simplification.

## 17. Conflict Handling

Chainless V2 uses Claude Code-style soft merge plus system-level hard guards.

### 17.1 Soft Merge

Soft merge means the Agent sees relevant context together and reasons about
which applies:
- Current user intent
- Memory
- Skill
- Worker
- Layered project/user/local rules
- Recent conversation

Soft cognitive priority:

```text
current explicit user intent
> Worker execution invariants
> Skill method rules
> Memory facts/preferences
> historical context
```

This is not code-level replacement. It is an Agent planning priority.

### 17.2 Hard Guards

Hard guards override all prompts and capabilities:
- Permission denied remains denied.
- Tenant/user isolation cannot be overridden.
- Input schema failures block Worker execution.
- Worker allowed-tools list cannot be exceeded.
- External delivery requires confirmation and configured channel authorization.
- Destructive actions require confirmation.
- Delete/disable active Worker requires confirmation.
- Sandbox/file/artifact security boundaries cannot be bypassed.

Example:

```text
User:
"Don't ask, send this to Feishu."

Hard guard:
External delivery still requires configured channel authorization and
confirmation if policy requires it.
```

## 18. Policy Guards and Hooks

V2 phase 1 adopts minimal hard guards plus internal hooks.

### 18.1 Minimal Hard Guards

Required phase 1 guards:
- Tenant isolation.
- User-private capability isolation.
- Worker input schema validation.
- Worker precondition validation.
- Worker allowed tool enforcement.
- Tool risk-level enforcement.
- External delivery confirmation.
- Destructive action confirmation.
- Worker delete/disable confirmation.
- Worker failure fallback transparency.
- WorkerRun trace and audit recording.

### 18.2 Internal Hooks

Hooks are internal lifecycle interception points, not a user script/plugin
system in phase 1.

Required hook points:
- `before_worker_match`
- `before_worker_run`
- `after_worker_run`
- `before_tool_call`
- `after_tool_call`
- `on_worker_failure`
- `on_capability_candidate_created`

Hook responsibilities:
- Validate policy.
- Add audit records.
- Enforce risk confirmation.
- Update match feedback.
- Generate failure/improvement candidates.
- Deduplicate and merge candidates.
- Prevent prompt-derived behavior from bypassing runtime policy.

Non-goals:
- No arbitrary user-authored hook code.
- No hook marketplace.
- No hook access to secrets beyond explicit system-owned redacted context.
- No hook may bypass policy guard decisions.

## 19. UI Design Boundary

UI must preserve existing visual style and interaction feel.

### 19.1 Chat Right Panel Inbox Tab

Add a right-panel tab for lightweight capability feedback:
- Current conversation candidates.
- Recent pending candidates.
- Worker failure/improvement suggestions.
- Quick actions: accept, edit, dismiss, snooze, open in Settings.
- Worker invocation trace links.

The tab should be lightweight. It must not become the full management UI.

### 19.2 Settings Capability Management

Add full personal capability management under Settings:
- Capability Inbox
- Memories
- Skills
- Workers
- Worker versions
- Worker runs
- Worker enable/disable/delete/rollback
- Candidate filters and search
- Muted patterns

### 19.3 Chat Hints and Worker Notices

Chat should show:
- Lightweight candidate hints after relevant runs.
- Lightweight Worker-use notices when an existing Worker is invoked.
- Transparent fallback notices when Worker execution fails.
- Confirmation cards for risky Worker/tool actions.

### 19.4 Style Preservation

The implementation plan must explicitly preserve:
- Existing dark zinc visual language.
- Sidebar behavior.
- Chat scroll behavior.
- Existing composer feel.
- Existing right-panel layout and tabs.
- Existing settings page visual language.

No broad redesign is authorized by this spec.

## 20. Data Model Sketch

Exact schema is implementation-plan work. The model should include these
canonical owners.

```text
capability_candidates
- id
- tenant_id
- user_id
- candidate_type
- status
- title
- proposal
- confidence
- risk_level
- reason
- source_type
- source_conversation_id
- source_message_ids
- source_run_id
- source_artifact_ids
- source_worker_id
- source_worker_version_id
- source_evidence
- dedupe_key
- muted_pattern_key
- merged_into_candidate_id
- snoozed_until
- created_at
- updated_at
- reviewed_at

workers
- id
- tenant_id
- user_id
- name
- description
- purpose
- enabled
- active_version_id
- match_policy
- risk_level
- created_from_candidate_id
- created_at
- updated_at
- disabled_at
- soft_deleted_at

worker_versions
- id
- worker_id
- version_number
- status
- input_schema
- preconditions
- tool_permissions
- output_contract
- execution_contract
- examples
- failure_policy
- source_evidence
- verification_status
- verification_summary
- created_from_candidate_id
- created_at
- activated_at
- archived_at

worker_runs
- id
- tenant_id
- user_id
- worker_id
- worker_version_id
- trigger_type
- status
- input_summary
- matched_request
- match_score
- tool_trace
- output_artifact_ids
- delivery_result
- fallback_used
- fallback_status
- error_code
- error_message
- started_at
- ended_at

worker_match_feedback
- id
- tenant_id
- user_id
- worker_id
- source_run_id
- feedback_type
- reason
- score_delta
- created_at
```

Existing Memory and Skill models may need version/scope extensions in the
implementation plan, but this spec does not require replacing them.

## 21. API Surface Sketch

Exact schemas belong in the implementation plan.

```text
GET    /api/v1/capability-candidates
GET    /api/v1/capability-candidates/{candidate_id}
POST   /api/v1/capability-candidates/{candidate_id}/accept
POST   /api/v1/capability-candidates/{candidate_id}/dismiss
POST   /api/v1/capability-candidates/{candidate_id}/snooze
POST   /api/v1/capability-candidates/{candidate_id}/archive
POST   /api/v1/capability-candidates/{candidate_id}/mute-pattern
POST   /api/v1/capability-candidates/{candidate_id}/merge

GET    /api/v1/workers
POST   /api/v1/workers
GET    /api/v1/workers/{worker_id}
PATCH  /api/v1/workers/{worker_id}
POST   /api/v1/workers/{worker_id}/disable
POST   /api/v1/workers/{worker_id}/enable
DELETE /api/v1/workers/{worker_id}

POST   /api/v1/workers/{worker_id}/versions
POST   /api/v1/workers/{worker_id}/versions/{version_id}/verify
POST   /api/v1/workers/{worker_id}/versions/{version_id}/activate
POST   /api/v1/workers/{worker_id}/rollback

POST   /api/v1/workers/{worker_id}/runs
GET    /api/v1/workers/{worker_id}/runs
GET    /api/v1/worker-runs/{run_id}

POST   /api/v1/worker-runs/{run_id}/feedback
POST   /api/v1/workers/{worker_id}/match-feedback
```

## 22. Acceptance Criteria

Product acceptance:
- A user can complete a chat task and receive a lightweight capability hint.
- The same candidate appears in the user's personal Capability Inbox.
- The candidate remains until user action.
- The user can accept Memory, Skill, and Worker candidates.
- Accepted Memory, Skill, and Worker influence later Agent planning in their
  correct roles.
- The Agent can invoke a high-confidence low-risk Worker with a visible notice.
- The Agent avoids uncertain Worker matches, completes the task normally, and
  may suggest create/improve afterward.
- Worker failure transparently falls back where safe and never claims Worker
  success when fallback produced the result.
- Worker improvement creates a new version, not an overwrite.
- Worker disable/delete works, including natural-language initiated flow, with
  confirmation and soft delete for active/historical Workers.

Architecture acceptance:
- Capability Candidate records cannot influence planning before acceptance.
- User-private candidates and capabilities never affect other users.
- Hard guards cannot be bypassed by current user prompt, Memory, Skill, or
  Worker content.
- Worker matching includes semantic, schema, precondition, risk, feedback, and
  success/failure signals.
- Hooks exist as internal guard/audit lifecycle points.
- Proactive schedule remains a trigger, not Worker source of truth.
- Existing V1 chat, Memory, Skill metadata, artifacts, and proactive behavior
  remain compatible.

UI acceptance:
- Right panel has a lightweight Inbox tab.
- Settings has a full personal capability management page.
- Existing Chainless style, layout, and scroll behavior are preserved.
- Browser QA proves no frontend style regression.

Verification environment:
- Use local Docker Desktop only.
- Backend tests run inside Docker.
- Browser QA uses the configured Windows browser path.
- Do not rely on host Python or host Node.

## 23. Plan-Time Complexity Check

Likely high-pressure files:
- `backend/app/api/v1/conversations.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/engine.py`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/stores/platform-store.ts`
- `frontend/src/components/chat/preview-panel.tsx`
- `frontend/src/app/settings/page.tsx`

Better file boundary:
- Add dedicated backend owners for capability candidates, Worker runtime,
  Worker matching, policy guards, and hooks.
- Do not grow conversation routes into capability-generation controllers.
- Keep chat store focused on chat execution state.
- Keep platform store or a new capability store focused on Settings and Inbox
  management.
- Keep UI additions inside existing right-panel and Settings structures.

Recommendation:
Add owner modules for the Capability Operating Layer rather than patching it
through existing chat and settings files. Avoid broad frontend refactors and
style changes.

## 24. ADR Signals

This design touches durable architecture surfaces:
- New source of truth for inactive capability suggestions.
- New source of truth for executable Agent-callable work.
- New WorkerVersion immutability and rollback boundary.
- New hard-guard and hook boundaries.
- New conflict model using Claude Code-style soft merge plus runtime guards.
- New personal-only capability scope with future team scope deliberately
  deferred.

After implementation proves the boundary, record an ADR for:
- Capability Candidate vs active Memory/Skill/Worker ownership.
- Worker as Agent-callable executable capability.
- Soft merge plus hard guard conflict model.
- Personal capability scope and future team-publishing path.

## 25. Open Questions for Implementation Planning

These are not unresolved product choices; they are implementation details to
settle in `aegis:writing-plans`:

1. Should candidate generation run synchronously after chat completion or via
   background queue?
2. Should candidate analysis use the default user provider or a configured cheap
   internal model?
3. How should Skill accepted from a candidate be represented with the current
   passive `skills` schema?
4. Should Worker execution reuse chat stream service or a new Worker execution
   service that calls the Agent engine directly?
5. How should WorkerRun trace reference tool calls, artifacts, audit records,
   and SSE events without duplicating too much JSON?
6. What exact thresholds should separate high, medium, and low Worker match
   confidence?
7. Which browser QA flows best prove no frontend style regression?

## 26. Spec Self-Review

Placeholder scan:
No TODO/TBD placeholders remain.

Internal consistency:
The spec consistently treats Capability Candidate as inactive, Memory as
knowledge, Skill as method, Worker as Agent-callable executable capability, and
Schedule as trigger only.

Scope check:
The scope is broad but focused enough for one V2 implementation plan if split
into workstreams: candidate pipeline, Inbox UI/API, Memory/Skill acceptance,
Worker runtime, policy guards/hooks, Agent planning integration, and QA.

Ambiguity check:
"Worker reuse" is explicitly defined as Agent matching/invocation, not manual
run as the main path. "Self-evolution" is proposal-first and user-approved, not
silent autonomous mutation.

Boundary check:
Hard guards, personal scope, frontend style preservation, inactive candidate
boundary, Worker lifecycle, soft delete, fallback transparency, and hook
non-goals are explicit.

User review:
Approved by the user on 2026-06-17. Proceed to `aegis:writing-plans`.
