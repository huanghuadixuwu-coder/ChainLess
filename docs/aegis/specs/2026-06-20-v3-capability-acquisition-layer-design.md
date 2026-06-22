# Chainless V3 Capability Acquisition Layer Design Spec

Date: 2026-06-20
Status: Design Spec for user review
Scope: V3 product and architecture design

## 1. TaskIntentDraft

Outcome:
Create Chainless V3's Capability Acquisition Layer: a private, auditable layer
that lets the Agent discover missing capabilities, use Code-as-Action for
low-risk exploration, recommend new tools or methods when exploration is not
enough, and activate verified capabilities only after explicit user approval.

Core product sentence:
When the Agent finds that current Memory, Skill, Worker, or Tool capability is
insufficient, it should first try safe Code-as-Action exploration; if that
succeeds, it should bridge the result into V2 capability sedimentation; if that
fails or is unstable, it should create a reviewable acquisition path for the
user.

Why this exists:
Without this layer, Chainless risks becoming a manually maintained builtin-tool
platform. V3 keeps Chainless aligned with the private AI Worker OS direction:
the system can discover, test, propose, approve, verify, activate, and audit new
capabilities instead of waiting for developers to hand-code every domain tool.

Success evidence:
- A failed or unstable task can create a private Capability Gap with evidence.
- Low-risk public data or file tasks can trigger safe Code-as-Action exploration.
- Exploration success can generate V2 Memory, Skill, or Worker candidates.
- Exploration failure can generate a Recommendation and an Acquisition Proposal.
- A Proposal requires separate exploration approval and activation approval.
- A verified runtime Proposal can activate a typed target such as MCP Tool,
  API Tool, Workspace Connector, Browser Automation, Worker, Skill, or Memory.
- A verified development patch proposal can produce a handoff-ready patch,
  tests, rollback plan, and review checklist, but never runtime activation.
- Activation targets carry explicit permissions, verification evidence, audit
  events, and rollback plans.
- A private generated ACQUISITION.md journal records the lifecycle but never
  serves as runtime authority.
- No new runtime capability becomes available to the Agent before verification
  and explicit activation approval.

Stop condition:
The design is ready for implementation planning when data owners, lifecycle
states, trigger rules, approval gates, permission rules, activation targets,
UI placement, journal behavior, policy guard behavior, and test expectations
are explicit enough to plan workstreams without re-litigating the product
shape.

Non-goals:
- Do not build a public marketplace in V3.
- Do not silently install MCP servers, packages, browser extensions, or tools.
- Do not silently modify production Chainless code or deployment configuration.
- Do not let model-generated text or Markdown directly change runtime ability.
- Do not replace V2 Capability Candidates, Workers, Skills, or Memories.
- Do not put Acquisition state into conversation rows, proactive tasks, or the
  V2 Capability Inbox.
- Do not redesign the existing frontend style, chat layout, sidebar behavior,
  scroll behavior, or visual language.
- Do not rely on host Python or host Node for verification; runtime work must
  stay in the Docker-supported environment.

## 2. BaselineReadSetHint

Authority refs:
- `AGENTS.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-02-chainless-implementation.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-16-v2-capability-operating-layer-design.md`
- `docs/aegis/plans/2026-06-17-v2-capability-operating-layer-execution-plan.md`

Relevant existing owners:
- Agent runtime:
  - `backend/app/core/agent/engine.py`
  - `backend/app/core/agent/code_executor.py`
  - `backend/app/services/conversation_stream_service.py`
- V2 capability layer:
  - `backend/app/core/capabilities/`
  - `backend/app/api/v1/capabilities.py`
  - `backend/app/models/capability.py`
- Worker layer:
  - `backend/app/core/workers/`
  - `backend/app/api/v1/workers.py`
  - `backend/app/models/worker.py`
- Tool and MCP layer:
  - `backend/app/core/tools/`
  - `backend/app/core/tools/mcp/`
  - `backend/app/api/v1/tools.py`
  - `backend/app/models/tool_configuration.py`
- Memory and generated Markdown pattern:
  - `backend/app/core/memory/persistent.py`
  - `backend/app/models/memory.py`
- Existing UI surfaces:
  - `frontend/src/components/chat/`
  - `frontend/src/components/settings/`
  - `frontend/src/stores/capability-store.ts`
  - `frontend/src/stores/platform-store.ts`

Current baseline facts:
- V2 has private Capability Candidates, Memory, Skill, Worker, WorkerVersion,
  WorkerRun, semantic Worker matching, policy hooks, and Settings management.
- V2 Capability Candidate types are Memory, Skill, and Worker. V3 must not
  overload that Inbox with Gap and Acquisition lifecycle states.
- Existing Memory uses DB rows as authority and generated Markdown as derived
  human-readable source. V3 should follow the same source-of-truth pattern.
- Existing Tool/MCP registration is available, but V3 needs approval,
  verification, permission, and rollback contracts around activation.
- Existing MCP registration is memory-backed at runtime; V3 must add a durable
  MCP server configuration owner before MCP activation is production-ready.
- Generic API Tool, Workspace Connector, and Browser Automation runtime owners
  do not yet exist. V3 must add them rather than treating them as simple
  bridges to current tools.
- Existing Code-as-Action is a strong exploration primitive, but V3 must record
  exploration evidence and prevent exploration from becoming silent activation.

## 3. ImpactStatementDraft

Affected product layers:
- Chat: show lightweight notices when a task creates a Gap, starts safe
  exploration, creates a Recommendation, or needs approval.
- Right panel: show current-run Acquisition cards with status and link to full
  review. Keep visual style and scroll behavior intact.
- Settings: add an Acquisition section for Gaps, Explorations,
  Recommendations, Proposals, Verifications, Activations, and Journal views.
- Capability Inbox: remains V2-only for Memory, Skill, and Worker candidates.
- Workers: can be created or improved as secondary activation targets.
- Tools/MCP: can be activation targets, with explicit verification and rollback.
- Memory/Skill: can be derived from successful exploration or activated as
  secondary targets.
- Audit and observability: must record approvals, denials, verification results,
  activation, rollback, policy blocks, and runtime confirmation decisions.

Affected backend layers:
- New Acquisition owner under `backend/app/core/acquisition/`.
- New API owner under `backend/app/api/v1/acquisition.py`.
- New persistence models for Gap, ExplorationRun, Recommendation, Proposal,
  ActivationTarget, Verification, and Journal snapshots.
- New policy facade for exploration and activation decisions.
- New journal renderer for private generated ACQUISITION.md files.
- New durable runtime owners for activated acquired capability:
  - `MCPServerConfiguration` under the Tool/MCP owner.
  - `APIToolConfiguration` under a generic API tool owner.
  - `WorkspaceConnector` under a workspace connector owner.
  - `BrowserAutomationConfiguration`, session, and trace owner for built-in
    Playwright/Chromium automation.
- New `RuntimePlanningIssue` owner for cases where existing capability was
  available but the planner missed it.
- Thin seams from conversation streaming and agent runtime into Acquisition.
- Bridges into existing V2 candidate, Worker, Tool/MCP, Memory, and Skill
  owners.

Compatibility:
- Existing chat behavior must keep working if Acquisition is disabled.
- Existing V2 Capability Candidates must keep their current route contract and
  type semantics.
- Existing Workers, Skills, Memories, Tools, MCP registration, confirmations,
  and artifacts remain source-of-truth owners for their own runtime behavior.
- Existing Memory Markdown generation remains derived and non-authoritative.

Migration:
- V3 adds new tables and APIs. It does not migrate existing V2 candidates into
  Acquisition.
- Existing tool failure logs and V2 improvement candidates do not need
  backfill. V3 starts recording new evidence after deployment.

## 4. Product Risk Lens

Value:
V3 makes Chainless meaningfully different from a generic Agent chat or tool
catalog. It turns failure and workaround into a product loop: discover a gap,
try safe code, propose a capability, verify it, activate it, and reuse it.

Non-goals:
Do not make every failure a product event. Do not show noisy gaps for simple
misunderstandings, missing user inputs, transient provider errors, or ordinary
unknown facts.

Trade-offs:
The independent Acquisition layer adds schema and UI complexity, but it keeps
V2 Capability Inbox clean and preserves a clear safety boundary between
learning from success and acquiring missing runtime capability.

Decision:
Adopt a separate Acquisition Center plus lightweight chat/right-panel hints.
Use generated private ACQUISITION.md for evidence visibility, not authority.

## 5. First-Principles Invariants

Non-negotiable goal:
Chainless must become self-extending without becoming silently self-modifying.

Non-negotiable constraints:
- No silent tool installation.
- No silent credential use.
- No silent host filesystem access.
- No silent external write.
- No silent production code change.
- No runtime permission can be granted by generated Markdown.
- Every activated capability must be reversible or explicitly marked
  non-reversible before approval.

Historical assumptions to delete:
- More builtin tools equals more generality.
- A failed task is only an error, not a learning signal.
- A successful fallback means the underlying capability exists.
- A user saying "yes" to exploration means "install and activate it."
- A Markdown note can safely double as runtime state.

Smallest sufficient path:
Add a dedicated Acquisition owner that records gaps, explorations,
recommendations, proposals, verifications, and activations, then bridges to
existing owners for actual runtime capability.

Escalation signal:
Any design that lets model output directly register a tool, install a package,
save credentials, access host files, run browser writes, or modify production
code without user approval must be rejected.

## 6. Baseline Role Alignment

Product / Requirement Baseline:
V2 handles successful work becoming Memory, Skill, or Worker. V3 handles missing
capability becoming a verified, approved runtime extension or a documented
rejected path.

Architecture / Runtime Boundary Baseline:
Acquisition owns the acquisition lifecycle only. Existing runtime owners keep
runtime authority: Tool/MCP owns tools, Worker owns executable templates, Memory
owns facts, Skill owns methods, Policy owns hard guards, Audit owns durable
records, and Agent runtime executes tasks.

Result:
Aligned, with new V3 authority required.

Scope:
Both requirements and architecture.

Next action:
Write this Design Spec, then create a detailed execution plan after user review.

## 7. Architecture Integrity Lens

Invariant:
An inactive acquisition record must never affect Agent planning or tool
availability. Only verified and activated targets may enter runtime capability.

Canonical owner / contract:
- `core/acquisition` owns Gap, ExplorationRun, Recommendation, Proposal,
  ActivationTarget, Verification, Activation, and Journal rendering.
- `core/capabilities` owns V2 Memory, Skill, and Worker candidate generation and
  acceptance.
- `core/workers` owns Worker runtime, WorkerVersion verification, activation,
  rollback, and match feedback.
- `core/tools` and `core/tools/mcp` own tool and MCP registry behavior.
- `core/tools/mcp` owns durable MCP server configuration, restart recovery,
  connection lifecycle, discovered schemas, and execution.
- `core/tools/mcp_runtime` owns isolated MCP stdio runtime execution,
  approved command provenance, container/image or package digest checks,
  filesystem and network policy, resource limits, lifecycle cleanup, and
  restart-safe process supervision.
- `core/tools/api` owns generic API tool configuration, credential references,
  request execution, schema validation, rate limits, retries, and error
  contracts.
- `core/workspace_connectors` owns approved host/server path mappings and
  bounded file access through connector IDs.
- `core/browser_automation` owns built-in Playwright/Chromium sessions,
  profile isolation, screenshots, DOM/action traces, cleanup, and browser
  action execution.
- `core/credentials` owns user-private CredentialConnection records, encrypted
  secret material or external vault references, rotation, revocation, metadata
  redaction, and usage audit for V3 acquired MCP, API, Workspace, Browser, and
  future acquisition runtime targets.
- `core/security/egress_policy` owns reusable network egress validation for
  API, MCP HTTP/SSE, Browser, and Code-as-Action network calls, including DNS
  resolution, private network denial, redirect policy, response size caps, and
  per-target allowlists.
- `core/memory` owns Memory persistence and generated Memory Markdown.
- `audit` owns durable approval and activation records.
- `policy` decisions remain hard runtime gates.
- `core/planning_issues` owns RuntimePlanningIssue records for planner misses
  that are not acquisition gaps.

Responsibility overlap to avoid:
- Do not add Gap or Proposal states to V2 `CapabilityCandidate`.
- Do not let conversation streaming own acquisition persistence.
- Do not let proactive tasks own Worker behavior or acquisition state.
- Do not let Worker definitions own tool installation.
- Do not let generated Markdown own state transitions.
- Do not let Acquisition directly execute MCP, API, workspace, browser,
  Worker, Skill, or Memory behavior after handoff.
- Do not let runtime owners store raw credential material in their own tables,
  metadata blobs, prompts, traces, logs, or artifacts.
- Do not let callers pass arbitrary URLs, host paths, cookies, or credentials
  directly into tools as a substitute for approved owners.
- Do not execute user-approved MCP stdio commands inside the backend or worker
  process/container. Stdio MCP must cross the MCP Runtime Isolation owner.
- Do not put planner misses into CapabilityGap.

Higher-level simplification:
Use one Acquisition lifecycle that bridges to existing owners instead of adding
local fallback logic to every tool failure path.

Retirement / falsifier:
If implementation requires multiple owners to independently decide whether a
new MCP, Worker, or connector is approved, the design has drifted. Approval and
activation authority must be centralized in Acquisition plus Policy.

Verdict:
Proceed with a new dedicated owner and strict bridges to existing runtime owners.

## 8. V3 Conceptual Model

V3 separates four concerns:

```text
Agent Runtime
  observes task evidence and performs safe exploration

Acquisition Layer
  owns missing capability lifecycle and user approval

Runtime Owners
  activate specific capabilities after verification

Journal
  renders private human-readable evidence from DB state
```

End-to-end flow:

```text
User task
-> Agent uses current Memory / Skill / Worker / Tool set
-> Existing capability is insufficient
-> Acquisition records or updates a CapabilityGap
-> Low-risk exploration may run with Code-as-Action
-> Exploration succeeds
   -> create V2 Memory / Skill / Worker candidates
-> Exploration fails or is unstable
   -> create Recommendation
   -> draft AcquisitionProposal
   -> user approves activation
   -> verification runs
   -> verified target is activated through its canonical owner
   -> private ACQUISITION.md journal is regenerated
```

## 9. Domain Objects

### 9.1 CapabilityGap

Purpose:
Record a missing or insufficient capability.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `source_kind`
- `source_run_id`
- `conversation_id`
- `dedupe_key`
- `title`
- `description`
- `gap_type`
- `severity`
- `status`
- `evidence`
- `first_seen_at`
- `last_seen_at`
- `occurrence_count`
- `created_at`
- `updated_at`

Gap types:
- `missing_tool`
- `missing_mcp`
- `missing_api`
- `missing_credential`
- `missing_workspace_access`
- `missing_browser_automation`
- `unstable_public_source`
- `unsupported_external_action`
- `requires_product_change`
- `requires_code_patch`
- `blocked_by_policy`

Statuses:
- `detected`
- `exploration_recommended`
- `exploration_approved`
- `exploring`
- `explored_success`
- `explored_failed`
- `recommendation_created`
- `proposal_drafted`
- `dismissed`
- `snoozed`
- `superseded`
- `blocked_by_policy`

Rules:
- A Gap is private to `tenant_id` and `user_id`.
- A Gap is deduped by tenant, user, gap type, normalized target domain/tool,
  and source class.
- A Gap can collect multiple occurrences.
- A Gap does not change Agent planning by itself.
- Planner misses are not CapabilityGaps. They are RuntimePlanningIssues because
  they show the Agent failed to use an existing capability, not that a new
  capability is missing.

### 9.2 ExplorationRun

Purpose:
Record the Agent's attempt to solve the gap using current approved capability,
especially Code-as-Action.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `gap_id`
- `source_run_id`
- `risk_level`
- `approval_id`
- `status`
- `strategy`
- `tool_events`
- `script_ref`
- `artifact_refs`
- `stdout_excerpt`
- `stderr_excerpt`
- `result_summary`
- `failure_reason`
- `started_at`
- `completed_at`

Strategies:
- `code_as_action`
- `web_search`
- `web_fetch`
- `existing_tool_chain`
- `mcp_probe`
- `workspace_probe`
- `browser_probe`
- `manual_research`

Statuses:
- `queued`
- `running`
- `succeeded`
- `failed`
- `blocked_by_policy`
- `cancelled`
- `timed_out`

Rules:
- Safe exploration may run automatically.
- High-risk exploration requires user approval.
- Exploration output may create V2 candidates or V3 recommendations.
- Exploration does not install tools, save credentials, or alter production
  code.

### 9.3 CapabilityRecommendation

Purpose:
Explain a suggested way to acquire the missing capability.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `gap_id`
- `exploration_run_id`
- `recommendation_type`
- `title`
- `summary`
- `reason`
- `evidence`
- `risk_level`
- `expected_value`
- `required_permissions`
- `candidate_targets`
- `created_at`
- `updated_at`

Recommendation types:
- `mcp_recommendation`
- `api_recommendation`
- `browser_automation_recommendation`
- `workspace_connector_recommendation`
- `credential_recommendation`
- `worker_recommendation`
- `skill_recommendation`
- `memory_recommendation`
- `development_patch_recommendation`

Rules:
- A Recommendation is not an approval request by itself.
- A Recommendation may be dismissed, snoozed, or converted into a Proposal.
- Recommendations may be visible in chat as lightweight hints and fully managed
  in Settings Acquisition.

### 9.4 AcquisitionProposal

Purpose:
Provide a formal, reviewable, verifiable, and reversible activation plan.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `proposal_kind`
- `gap_id`
- `recommendation_id`
- `title`
- `reason`
- `evidence`
- `status`
- `risk_level`
- `permission_bundle`
- `primary_target`
- `secondary_targets`
- `development_handoff`
- `verification_plan`
- `rollback_plan`
- `user_visible_effect`
- `approval_history`
- `activation_snapshot_hash`
- `snapshot_created_at`
- `created_at`
- `updated_at`

Proposal kinds:
- `runtime_activation`
- `development_patch_proposal`

Statuses:
- `drafted`
- `activation_requested`
- `activation_approved`
- `activation_rejected`
- `verifying`
- `verified`
- `verification_failed`
- `activated`
- `partial_activation`
- `activation_failed`
- `rolled_back`
- `handoff_ready`
- `handoff_started`
- `dismissed`
- `superseded`

Rules:
- Proposal mutation occurs only through UI/API.
- Approval must be explicit and auditable.
- A runtime activation Proposal has exactly one `primary_target`.
- A runtime activation Proposal may have zero or more `secondary_targets`.
- A development patch proposal has no runtime ActivationTarget. It stores
  `development_handoff` instead and can only reach `handoff_ready`.
- Primary target verification failure prevents runtime activation.
- Secondary target failure records `partial_activation` but does not roll back
  a successful primary target unless the user chooses rollback.
- Activation requires the verified `activation_snapshot_hash` to match the
  current Proposal, target payloads, permission bundle, verification result, and
  rollback plan.

### 9.5 ActivationTarget

Purpose:
Describe a typed handoff to a runtime owner.

Common fields:
- `target_type`
- `target_name`
- `target_owner`
- `target_payload`
- `permission_bundle`
- `verification_plan`
- `rollback_plan`
- `activation_status`
- `activation_result`
- `activated_resource_ref`

Target types:
- `mcp_tool`
- `api_tool`
- `workspace_connector`
- `browser_automation`
- `worker`
- `skill`
- `memory`

Rules:
- Each target is independently verified, audited, and reversible when possible.
- Secondary targets cannot inherit permission from the primary target.
- Worker allowed tools can reference only activated tools in scope.
- Memory and Skill targets cannot carry runtime permission.
- Development patch proposals are not ActivationTargets and cannot activate into
  production automatically.

### 9.6 AcquisitionVerification

Purpose:
Record verification execution and evidence.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `proposal_id`
- `target_id`
- `status`
- `verification_kind`
- `input_fixture`
- `expected_result`
- `actual_result`
- `artifact_refs`
- `error_code`
- `error_message`
- `verified_snapshot_hash`
- `verified_snapshot_payload`
- `started_at`
- `completed_at`

Statuses:
- `pending`
- `running`
- `passed`
- `failed`
- `blocked_by_policy`
- `cancelled`
- `timed_out`

Rules:
- Runtime activation cannot occur without passing verification. Development
  patch proposal verification produces handoff-ready evidence rather than a
  runtime activation target.
- Verification must use the Docker runtime, not host Python or host Node.
- Verification creates a snapshot hash over the exact target payload,
  permission bundle, verification evidence, rollback plan, and user-visible
  effect that the user approves.

### 9.7 AcquisitionJournal

Purpose:
Render private human-readable evidence as generated Markdown.

File shape:
- Tenant and user scoped.
- Generated from DB state.
- Append/read-only from the product perspective.
- Not committed to repo docs.
- Not a runtime authority.

Suggested paths:

```text
<acquisition_base_path>/<tenant_id>/users/<user_id>/ACQUISITION.md
<acquisition_base_path>/<tenant_id>/users/<user_id>/gaps/<gap_id>.md
```

Rules:
- Users cannot edit the journal directly through Chainless.
- All changes must go through UI/API and audit.
- If a file is manually edited outside the product, Chainless ignores it for
  authority and can regenerate it.
- The Agent may cite journal excerpts as evidence, but cannot treat the journal
  as approval or activation.
- The journal may cross-link related Memory, Skill, Worker, Tool, or Connector
  records, but Acquisition DB rows remain the source of truth.

### 9.8 RuntimePlanningIssue

Purpose:
Record cases where existing runtime capability could have completed the task,
but the Agent planner missed it or chose the wrong path.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `source_run_id`
- `conversation_id`
- `issue_type`
- `available_capability_ref`
- `missed_signal`
- `planner_decision_summary`
- `expected_decision_summary`
- `severity`
- `status`
- `evidence`
- `created_at`
- `updated_at`

Issue types:
- `planner_missed_existing_tool`
- `planner_missed_worker`
- `planner_missed_skill`
- `planner_missed_memory`
- `wrong_risk_classification`
- `wrong_fallback_choice`

Rules:
- RuntimePlanningIssue never creates a CapabilityGap.
- It may produce V2 Skill or Worker improvement candidates.
- It may lower confidence for a Worker match or update planner retrieval tests.
- It must be tenant/user scoped and visible separately from Acquisition Gaps.

### 9.9 CredentialConnection

Purpose:
Represent a user-private credential or connection that runtime owners may
reference without storing raw secret material.

Required fields:
- `id`
- `tenant_id`
- `user_id`
- `name`
- `provider`
- `connection_type`
- `credential_kind`
- `secret_storage_kind`
- `secret_ref`
- `secret_generation`
- `scopes`
- `allowed_target_types`
- `allowed_target_refs`
- `status`
- `metadata_redacted`
- `expires_at`
- `last_validated_at`
- `rotation_required_at`
- `revoked_at`
- `created_at`
- `updated_at`

Connection types:
- `api_key`
- `oauth`
- `bearer_token`
- `basic_auth`
- `browser_cookie`
- `mcp_env_secret`
- `workspace_os_permission`
- `external_vault_ref`

Statuses:
- `draft`
- `active`
- `validation_failed`
- `rotation_required`
- `revoked`
- `expired`

Rules:
- CredentialConnection is not an ActivationTarget and cannot by itself make a
  capability available to the Agent.
- CredentialConnection is scoped to V3 acquired capability credentials. Existing
  `LLMProvider` and `ChannelConfiguration` secret owners remain authoritative
  for model providers and channel delivery unless a later approved migration
  explicitly bridges them.
- A bridge from an existing provider/channel secret to CredentialConnection must
  be explicit, audited, reversible, and cannot copy raw secret material into
  Acquisition metadata.
- Credential material enters Chainless only through explicit credential UI/API
  actions, never through chat inference, generated Markdown, Journal edits, or
  Proposal text.
- Runtime target tables store only `credential_ref` values pointing to
  CredentialConnection plus `secret_generation`; they never copy raw secret
  values.
- UI/API responses expose only `metadata_redacted`, status, scopes, expiry,
  and usage refs.
- Revocation makes dependent target execution fail closed until the target is
  reverified or a replacement credential is approved.
- Rotation changes `secret_generation` and invalidates any activation snapshot
  that referenced the previous generation.
- Cross-user and cross-tenant reads are forbidden.

## 10. Trigger Rules

### 10.1 Create CapabilityGap

Create or update a Gap when at least one strong signal is present:
- Tool result has capability error such as `TOOL_NOT_FOUND`,
  `MCP_NOT_REGISTERED`, `AUTH_REQUIRED`, `PERMISSION_DENIED`,
  `UNSUPPORTED_DOMAIN`, `RATE_LIMITED`, or `UNSUPPORTED_ACTION`.
- Code-as-Action exploration fails for a reason that indicates missing
  capability, not only script syntax.
- The task requires login, paid API, credential, host filesystem access,
  browser automation, system dependency installation, or external write.
- Similar task class fails more than once within a bounded recent window.
- The Agent completes the task only through an unstable workaround such as
  fragile scraping, manual user instructions, or unsourced fallback.
- The user explicitly asks to connect an API, MCP, credential, connector, or
  tool for future use.
- A Worker fails and normal Agent fallback succeeds, proving a reusable
  improvement path exists.

### 10.2 Do Not Create CapabilityGap

Do not create a Gap for:
- Greeting or casual chat.
- Missing user input.
- Ambiguous request that needs clarification.
- A one-off fact question with no tool, method, or future capability signal.
- A transient provider or network failure that can be retried.
- A case where an existing tool can complete the task but the planner missed
  it. Record this as a RuntimePlanningIssue, not an acquisition gap.
- A task that is forbidden by policy.

### 10.3 Automatic Safe Exploration

Safe exploration can run automatically when all conditions hold:
- It stays within the current run, uploaded files, run workspace, public web, or
  current approved tools.
- It uses no credential, login, browser cookie, host directory, paid API, or
  external write.
- It does not bypass access controls, rate limits, paywalls, captcha, or
  anti-abuse systems.
- It writes only temporary artifacts or run workspace files.
- It can be stopped and cleaned up.

### 10.4 Approval-Required Exploration

Exploration requires approval before it starts when it needs:
- Account login.
- Cookie, token, API key, OAuth, or other credential.
- Paid API or quota-consuming service.
- Host or server directory access.
- Browser automation on a live website.
- External write, message send, form submit, booking, payment, or deletion.
- Package installation, MCP installation, service startup, or system dependency.
- Long-running schedule, file watcher, webhook, or background trigger.

## 11. Risk Model

Risk levels:

```text
safe
  Public or user-provided data, read-only, no credentials, no external side
  effects, temporary sandbox only.

risky
  Networked, third-party, workspace access, or configured API use, but bounded
  and reversible with no external state change.

approval_required
  Credentials, login, browser session, host files, external writes, scheduled
  execution, package/MCP install, or sensitive data transfer.

destructive
  Delete, overwrite, submit, send, book, pay, change production config, or alter
  deployed code.

forbidden
  Bypass access controls, steal or guess credentials, evade paywalls/captcha,
  perform unauthorized access, conduct malicious automation, or silently perform
  irreversible user-impacting actions.
```

Policy rule:
If target risk levels differ, Proposal risk is the maximum risk across primary
and secondary targets.

## 12. Approval Model

V3 has two distinct approval phases.

### 12.1 Approve Exploration

Meaning:
The user permits the Agent to research, probe, or test a bounded acquisition
path.

Does not permit:
- Installing MCP.
- Saving credentials.
- Enabling tools.
- Creating active Workers.
- Accessing host directories.
- Running browser writes.
- Modifying production code.

### 12.2 Approve Activation

Meaning:
The user approves a verified Proposal to activate typed targets.

Requires:
- Proposal details.
- Permission bundle.
- Verification plan and result.
- Rollback plan.
- User-visible effects.
- Audit record.

### 12.3 Standing Permission

Standing Permission means activation-time approval allows future automatic
execution inside a fixed boundary.

Allowed for:
- Safe and risky actions.
- Bounded and reversible behavior.
- Fixed domains, tools, workspaces, and scopes.
- Query, read, summarize, draft, artifact write, or approved workspace write.
- Explicit `duration` values: `one_run`, `expires_at`, `until_revoked`, or
  `per_worker_run_confirmation`.
- User-visible revocation from Settings.

Not allowed for:
- Destructive actions.
- Payment, booking, ordering, sending, submitting, deleting, or overwriting
  external state.
- New domains, directories, credentials, tools, or side-effect categories not
  present in the approved permission bundle.
- Production code deployment.

Renewal required when:
- WorkerVersion changes.
- Tool/MCP/API/Browser/Connector configuration changes.
- Domain, host path, credential, write scope, network scope, or side-effect
  category expands.
- The activation snapshot hash no longer matches the approved snapshot.

### 12.4 Runtime Confirmation

Runtime confirmation is still required for:
- Sending emails or channel messages to real users.
- Submitting forms.
- Booking, ordering, or paying.
- Deleting or overwriting external data.
- Changing production config.
- Browser actions with external write or irreversible effects.
- Running a Worker outside its approved standing permission boundary.
- Any payment, booking, order placement, external message send, form submit,
  delete, overwrite, or production deployment, even when a standing permission
  exists.

## 13. Permission Bundle

Every ActivationTarget must include a permission bundle.

Fields:
- `target_id`
- `target_type`
- `target_version_ref`
- `permission_scope`
- `risk_level`
- `confirmation_policy`
- `credential_scope`
- `credential_connection_refs`
- `data_scope`
- `network_scope`
- `egress_policy`
- `write_scope`
- `execution_scope`
- `duration`
- `expires_at`
- `revocation_plan`
- `audit_events`
- `approved_snapshot_hash`

Scopes:

```text
data_scope:
  uploaded_files | run_workspace | project_workspace | host_directory |
  external_service | none

write_scope:
  none | artifact_only | run_workspace | approved_workspace |
  external_service

network_scope:
  none | public_web | allowlisted_domains | configured_api_base |
  arbitrary_network

credential_scope:
  none | user_provided_token | oauth_connection | browser_cookie |
  system_secret

execution_scope:
  code_as_action_temp | mcp_tool | api_tool | browser_session |
  workspace_connector | worker_run | backend_patch

duration:
  one_run | until_revoked | expires_at | per_worker_run_confirmation

confirmation_policy:
  never_for_safe | before_each_external_write | before_each_browser_submit |
  before_activation_only | always
```

Rules:
- Secondary targets cannot inherit permissions from the primary target.
- Permission expansion after activation requires a new approval.
- Credential changes require renewal confirmation.
- Domain, directory, or side-effect expansion requires renewal confirmation.
- `duration` must be explicit. No default infinite permission is allowed.
- `until_revoked` is allowed only when the UI shows the boundary and revocation
  action at approval time and in Settings afterward.
- `credential_connection_refs` must reference active CredentialConnection
  records owned by the current tenant and user.
- `egress_policy` must be explicit for API, MCP HTTP/SSE, Browser, and any
  Code-as-Action exploration that performs network calls.
- `arbitrary_network` is forbidden for activated API, MCP HTTP/SSE, Browser,
  and Worker-bound runtime targets. Use `allowlisted_domains` or
  `configured_api_base` with an explicit egress policy.
- Destructive and external-write actions are never covered by
  `never_for_safe`; they require runtime confirmation.

## 14. Activation Snapshot and Drift Prevention

Runtime activation is two-step: verification proves a target works, then
activation enables it. The system must prevent the approved payload from
drifting between those steps.

Snapshot payload:
- Proposal id, kind, status, and reason.
- Primary target payload.
- Secondary target payloads.
- Permission bundles for every target.
- Verification result and evidence refs.
- Rollback plan.
- User-visible effect.
- Runtime owner version refs.
- CredentialConnection ids and `secret_generation` values referenced by the
  approved targets.
- Egress policy snapshots for every network-capable target.

Rules:
- Verification creates `activation_snapshot_hash`.
- Approval references exactly one `activation_snapshot_hash`.
- Activation recomputes the hash and refuses activation on mismatch.
- Any Proposal, target payload, permission, credential ref, rollback, runtime
  owner version, or verification evidence change invalidates the snapshot.
- Snapshot mismatch status is `verification_stale`.
- `verification_stale` requires re-verification and renewed activation approval.
- Audit must record the approved hash and the activated hash.

Hash contract:
- Use `sha256` over deterministic canonical JSON.
- The canonical JSON payload includes a `snapshot_schema_version`.
- Object keys are sorted lexicographically.
- Arrays that represent sets are sorted by stable id or name.
- Volatile timestamps, retry counters, transient runtime logs, and display-only
  labels are excluded unless explicitly listed in the snapshot payload above.
- Evidence refs are included by immutable artifact id plus digest, not by
  mutable display URL.
- The exact canonical payload is stored as `verified_snapshot_payload` for
  audit and debugging.
- Any canonicalization failure blocks verification and records
  `snapshot_canonicalization_failed`.

## 15. Activation Targets

### 15.1 MCP Tool

Purpose:
Activate an MCP server/tool.

Canonical owner:
`core/tools/mcp` plus durable `MCPServerConfiguration`.

Required durable fields:
- `tenant_id`
- `user_id`
- `name`
- `transport`
- `runtime_kind`
- `command` or `url`
- `args`
- `env_secret_refs`
- `credential_connection_refs`
- `egress_policy`
- `stdio_runtime_image_ref`
- `stdio_command_provenance`
- `stdio_package_digest`
- `stdio_filesystem_policy`
- `stdio_network_policy`
- `stdio_resource_limits`
- `stdio_max_session_seconds`
- `stdio_max_output_bytes`
- `stdio_restart_policy`
- `enabled`
- `risk_level`
- `tool_schema_hash`
- `last_verified_at`
- `last_connected_at`
- `disabled_at`

Runtime kinds:
- `remote_http`
- `remote_sse`
- `isolated_stdio`

Rules:
- `transport=stdio` requires `runtime_kind=isolated_stdio`.
- `remote_http` and `remote_sse` require URL egress policy.
- Stdio command payloads are runtime-local commands inside the isolated MCP
  runtime, not backend or worker shell commands.

Verification:
- Persist draft MCPServerConfiguration.
- Start server.
- Discover tools.
- Execute minimal test call.
- Confirm tool names and schemas.
- Confirm risk classification.
- Confirm timeout and failure behavior.
- Confirm restart/reconnect behavior from durable config.
- Confirm secret values are referenced, not stored raw.
- For HTTP/SSE transport, enforce egress policy before every request.
- For stdio transport, launch only through `core/tools/mcp_runtime`; never run
  the MCP server command in the backend or worker process/container.
- For stdio transport, confirm command, args, image, package digest, env refs,
  filesystem policy, network policy, resource limits, output limits, and
  restart policy are exactly the approved payload.
- For stdio transport, confirm env values come only from CredentialConnection
  refs.
- For stdio transport, confirm the isolated runtime cannot access Docker socket,
  backend filesystem, host filesystem, unapproved workspace connectors, or
  non-allowlisted network targets.
- For stdio transport, confirm runtime cleanup after success, failure, timeout,
  reconnect, backend restart, and rollback.

Activation:
Enable MCPServerConfiguration and register/connect through the Tool/MCP owner.
On backend restart, enabled configurations are reloaded and reconnected through
the same owner. HTTP/SSE configurations connect through egress policy. Stdio
configurations create or attach to an isolated MCP runtime instance through
`core/tools/mcp_runtime`; backend-process stdio execution is forbidden.

Rollback:
Disable MCPServerConfiguration, disconnect server, hide discovered tools, and
revoke related credential refs if requested. For stdio transport, terminate the
isolated runtime instance, delete temporary runtime state according to
retention policy, and record cleanup evidence.

### 15.2 API Tool

Purpose:
Activate an API-backed tool.

Canonical owner:
`core/tools/api` plus durable `APIToolConfiguration`.

Required durable fields:
- `tenant_id`
- `user_id`
- `name`
- `base_url`
- `method`
- `path_template`
- `headers_schema`
- `auth_scheme`
- `credential_ref`
- `credential_generation`
- `input_schema`
- `output_schema`
- `allowed_hosts`
- `deny_private_networks`
- `redirect_policy`
- `allowed_content_types`
- `max_request_bytes`
- `max_response_bytes`
- `idempotency_policy`
- `response_redaction_policy`
- `rate_limit`
- `timeout_s`
- `retry_policy`
- `error_contract`
- `enabled`
- `risk_level`
- `last_verified_at`

Verification:
- Validate credential if needed.
- Call configured base URL.
- Check rate/credit information when exposed.
- Check stable error contract.
- Verify test input and expected output.
- Confirm request/response schema validation.
- Confirm retries and timeouts are bounded.
- Confirm credential material is not written to logs, SSE, Journal, or
  artifacts.
- Reject private, loopback, link-local, multicast, and metadata service
  addresses after DNS resolution.
- Reject DNS rebinding between verification and runtime by resolving and
  validating each request through the egress policy.
- Enforce redirect policy and revalidate every redirect target.
- Enforce request and response byte limits before buffering response bodies.
- Enforce allowed content types before passing data to the Agent.
- Confirm write-like methods have an idempotency or runtime confirmation
  strategy.

Activation:
Enable APIToolConfiguration through the generic API Tool owner. Agent runtime
sees it as a normal tool only after activation. Every runtime request must pass
the same egress policy, schema validation, byte limits, credential lookup, and
redaction rules used during verification.

Rollback:
Disable APIToolConfiguration and revoke or delete credential ref if requested.

### 15.3 Workspace Connector

Purpose:
Grant access to a user-approved local or server workspace path.

Canonical owner:
`core/workspace_connectors` plus durable `WorkspaceConnector`.

Required durable fields:
- `tenant_id`
- `user_id`
- `name`
- `connector_id`
- `display_path`
- `host_realpath_hash`
- `container_mount_path`
- `backend_mount_path`
- `sandbox_mount_path`
- `connector_root`
- `mount_generation`
- `mount_health_status`
- `mode`
- `allowlist_rule`
- `standing_permission_id`
- `enabled`
- `expires_at`
- `last_verified_at`

Verification:
- Resolve real path.
- Confirm path allowlist.
- Check path traversal prevention.
- Check read/write mode.
- Execute read/list/write probe according to selected permission.
- Confirm Docker Desktop or server mount mapping exists.
- Confirm Windows host paths are mapped into the backend/sandbox container
  before activation.
- Confirm file tools access through connector id, not raw host path.
- Confirm sandbox proxy receives a connector-scoped mount bundle and never a raw
  host path.
- Confirm Code-as-Action sees only connector-scoped capabilities for the
  approved connector, mode, and root.
- Confirm stale mount generations fail closed.

Activation:
Create and enable WorkspaceConnector. Runtime exposes bounded file tools that
require a connector id and resolve only within the approved connector root.
Runtime callers must not pass `workspace_base` strings for host access. File
tools, sandbox proxy, and Code-as-Action must resolve through the
WorkspaceConnector owner.

Rollback:
Disable connector and invalidate any standing permission.

### 15.4 Browser Automation

Purpose:
Allow controlled built-in browser automation.

Canonical owner:
`core/browser_automation` plus durable `BrowserAutomationConfiguration`,
BrowserSession, and BrowserTrace records.

Required durable fields:
- `tenant_id`
- `user_id`
- `name`
- `allowlisted_domains`
- `credential_ref`
- `credential_generation`
- `runtime_service_name`
- `runtime_image_ref`
- `runtime_health_check`
- `network_policy`
- `cookie_scope`
- `profile_policy`
- `profile_storage_ref`
- `profile_retention_policy`
- `max_session_seconds`
- `max_actions_per_run`
- `concurrency_limit`
- `cpu_limit`
- `memory_limit_mb`
- `max_trace_bytes`
- `trace_retention_days`
- `action_redaction_policy`
- `write_confirmation_policy`
- `enabled`
- `last_verified_at`

Verification:
- Launch browser in supported runtime.
- Navigate to allowlisted domains.
- Check session isolation.
- Check screenshot/DOM/action trace capture.
- Confirm external write actions require runtime confirmation.
- Confirm Playwright/Chromium runtime exists inside Docker-supported runtime.
- Confirm the Docker Compose service or runtime image is declared, buildable,
  health-checked, and separate from gstack QA browser.
- Confirm per-user profile isolation and cleanup.
- Confirm captcha, paywall, login bypass, and unauthorized automation remain
  forbidden.
- Confirm concurrency, timeout, and resource cleanup behavior.
- Confirm browser sessions cannot access Docker socket, host filesystem, or
  non-allowlisted network targets.
- Confirm trace retention, trace byte caps, screenshot redaction, and cookie
  redaction.
- Confirm runtime confirmation resume passes through the same policy gate as
  normal tool execution.

Activation:
Enable BrowserAutomationConfiguration. Runtime exposes a browser tool that can
navigate, read DOM, screenshot, and act only inside the approved boundary.
External writes always pause for runtime confirmation. Browser sessions are
created through the Browser Automation owner, counted against per-user and
system concurrency limits, and cleaned up on completion, timeout, rollback, or
backend restart.

Rollback:
Disable configuration, terminate sessions, clear profiles, delete traces after
retention, and revoke cookies or credential refs if requested.

### 15.5 Worker

Purpose:
Create or update an executable Agent-callable work template.

Verification:
- Draft WorkerVersion.
- Validate input schema.
- Validate allowed tools.
- Validate risk and standing permission boundaries.
- Execute dry-run or fixture-based verification.
- Bind WorkerVersion, allowed tools, and permission bundle into the activation
  snapshot hash.

Activation:
Use existing Worker verification and activation flow.

Rollback:
Disable, rollback version, or soft delete Worker.

### 15.6 Skill

Purpose:
Create or update method guidance.

Verification:
- Check trigger terms or semantic match.
- Confirm no runtime permission is embedded.
- Confirm method does not contradict hard policy.

Activation:
Create or update private Skill.

Rollback:
Disable or delete Skill.

### 15.7 Memory

Purpose:
Create or update private factual or preference context.

Verification:
- Confirm source evidence.
- Confirm user scope.
- Confirm no hidden credential or sensitive raw secret is written.

Activation:
Create or update Memory through Memory owner.

Rollback:
Delete or archive Memory.

### 15.8 Development Patch Proposal

Purpose:
Propose changes to Chainless source code.

Canonical owner:
Acquisition owns the proposal and evidence. Normal development workflow owns
implementation only after the user explicitly requests it.

Required handoff fields:
- `base_git_commit`
- `patch_artifact_ref`
- `patch_digest`
- `test_plan_ref`
- `rollback_plan_ref`
- `review_checklist_ref`
- `apply_check_status`
- `working_tree_mutation_allowed`
- `handoff_requested_at`
- `handoff_requested_by`

Verification:
- Generate patch.
- Generate tests.
- Generate rollback plan.
- Generate review checklist.
- Check patch applies to the current git revision.
- Do not mutate the working tree unless the user starts a development workflow.
- Store the patch as an artifact, not as an applied working-tree change.
- Confirm `working_tree_mutation_allowed` is false before `handoff_ready`.
- Confirm patch digest and base git commit match at handoff time.

Terminal state:
`handoff_ready`. No runtime activation occurs. Production changes require normal
code, test, review, commit, push, and deploy steps after a separate user
request. `handoff-development-patch` returns artifact refs and status only; it
must not stage, commit, push, deploy, or edit files.

Rollback:
Git revert, patch rollback, or branch discard according to development process.

## 16. Composite Target Policy

Adopt single-primary, multi-secondary targets.

Rules:
- One runtime activation Proposal has exactly one `primary_target`.
- One runtime activation Proposal can have zero or more `secondary_targets`.
- Primary target verification failure blocks activation.
- Primary target activation failure blocks activation.
- Secondary target failure records `partial_activation`.
- `partial_activation` does not automatically roll back the primary target.
- User can manually roll back any activated target.
- Every target has independent permission, verification, audit, and rollback.
- A development patch proposal is not composite runtime activation. It may link
  related Skill/Worker/Tool recommendations but cannot activate them in the
  same step.

Example:

```text
Train Query Capability
primary_target: mcp_tool train_query
secondary_targets:
  worker Train Query Worker
  skill Ticket query versus booking risk method
  memory User prefers Wuxi as departure city
```

## 17. Runtime Integration

### 17.1 Agent Runtime

Agent runtime responsibilities:
- Emit structured tool failure evidence.
- Emit Code-as-Action exploration events.
- Emit artifact references and source run IDs.
- Ask Acquisition whether safe exploration is allowed.
- Show lightweight user-visible notices.
- Execute activated acquired capability only through the target's canonical
  runtime owner.

Agent runtime must not:
- Own Acquisition persistence.
- Activate targets.
- Mutate permission bundles.
- Treat generated Journal Markdown as approval.
- Bypass activation snapshot validation.

### 17.2 Conversation Stream Service

Conversation streaming should call an Acquisition facade after completed runs
and on eligible tool failure events.

Allowed dependency:

```text
conversation_stream_service -> acquisition orchestration facade
```

Disallowed dependencies:

```text
conversation_stream_service -> acquisition model internals
conversation_stream_service -> tool installation internals
conversation_stream_service -> worker activation internals
```

### 17.3 Code-as-Action

Code-as-Action becomes the main exploration primitive.

Rules:
- Safe exploration can run automatically.
- Approval-required exploration needs explicit approval.
- Exploration runs in sandbox.
- Exploration writes only permitted artifacts.
- Exploration output must be captured into ExplorationRun evidence.
- Successful exploration may produce V2 candidates.
- Failed exploration may produce Recommendation.

## 18. UI Design Boundary

Frontend style rule:
Do not redesign the existing visual style, chat layout, sidebar behavior, right
panel behavior, scroll behavior, or Settings visual language.

### 18.1 Chat

Chat shows lightweight notices:
- Gap detected.
- Safe exploration started.
- Exploration succeeded.
- Exploration failed.
- Recommendation created.
- Approval required.
- Activation verified.
- Activation completed.

Notices should be non-blocking unless user approval is required.

### 18.2 Right Panel

Right panel shows current-run Acquisition cards:
- Gap card.
- Exploration card.
- Recommendation card.
- Approval-needed card.
- Activated target card.

Cards link to Settings Acquisition for full lifecycle.

### 18.3 Settings Acquisition

Settings gets a new Acquisition section.

Views:
- Open gaps.
- Exploration history.
- Recommendations.
- Proposals needing approval.
- Verification results.
- Activated targets.
- Journal view.

Actions:
- Approve exploration.
- Reject exploration.
- Dismiss or snooze gap.
- Convert recommendation to proposal.
- Approve activation.
- Reject activation.
- Retry verification.
- Roll back activation.
- Open linked V2 Worker, Skill, Memory, or Tool record.
- Revoke standing permission.
- Renew expired permission.
- View activation snapshot hash and verification evidence.
- Open RuntimePlanningIssue records separately from Acquisition Gaps.

Interaction state contract:

```text
SURFACE              | LOADING                 | EMPTY
---------------------|-------------------------|-----------------------------
Chat notices         | Inline "checking..."     | No Acquisition notice
Right panel card     | Skeleton card            | Existing right panel content
Settings gaps        | Existing list skeleton   | "No open capability gaps"
Settings proposals   | Existing list skeleton   | "No proposals need approval"
Verification detail  | "Verification running"   | "No verification has run yet"
Journal view         | "Generating journal"     | "No acquisition history yet"
Runtime issues       | Existing list skeleton   | "No planner issues recorded"

SURFACE              | ERROR                   | SUCCESS / PARTIAL
---------------------|-------------------------|-----------------------------
Chat notices         | Problem + next step      | Non-blocking completion note
Right panel card     | Error badge + link       | Status badge + evidence link
Settings gaps        | Retry + reason           | Dismiss/snooze/convert actions
Settings proposals   | Block reason + fix       | Approve/reject/rollback actions
Verification detail  | Failed check + remedy    | Verified snapshot hash
Journal view         | Regenerate action        | Read-only evidence
Runtime issues       | Evidence + improvement   | Linked Skill/Worker candidate
```

User-visible copy contract:
- Problem: what capability is missing or what planner miss happened.
- Cause: why current Memory, Skill, Worker, Tool, or permission was insufficient.
- Risk: what data, network, credential, workspace, browser, or write scope is
  involved.
- Next step: approve exploration, configure credential, retry verification,
  approve activation, revoke permission, or ignore.
- Recovery: how to roll back, renew, or retry.
- No raw credential, cookie, token, local absolute path, or secret appears in
  chat notices, SSE events, Journal text, or screenshots.

Style boundary:
- Reuse existing Settings shell, cards, buttons, badges, sidebar, scroll areas,
  typography, spacing, and visual language.
- Do not add a new visual theme or redesign the chat/right panel/sidebar.
- Browser QA must capture screenshots and DOM/scroll assertions for chat,
  right panel, sidebar actions, and Settings Acquisition.

## 19. API Surface

Recommended public route prefix:

```text
/api/v1/acquisition
```

Core routes:

```text
GET    /api/v1/acquisition/gaps
GET    /api/v1/acquisition/gaps/{gap_id}
POST   /api/v1/acquisition/gaps/{gap_id}/dismiss
POST   /api/v1/acquisition/gaps/{gap_id}/snooze

GET    /api/v1/acquisition/explorations
GET    /api/v1/acquisition/explorations/{exploration_id}
POST   /api/v1/acquisition/gaps/{gap_id}/approve-exploration

GET    /api/v1/acquisition/recommendations
GET    /api/v1/acquisition/recommendations/{recommendation_id}
POST   /api/v1/acquisition/recommendations/{recommendation_id}/draft-proposal

GET    /api/v1/acquisition/proposals
GET    /api/v1/acquisition/proposals/{proposal_id}
POST   /api/v1/acquisition/proposals/{proposal_id}/approve-activation
POST   /api/v1/acquisition/proposals/{proposal_id}/reject-activation
POST   /api/v1/acquisition/proposals/{proposal_id}/verify
POST   /api/v1/acquisition/proposals/{proposal_id}/activate
POST   /api/v1/acquisition/proposals/{proposal_id}/rollback
POST   /api/v1/acquisition/proposals/{proposal_id}/handoff-development-patch

GET    /api/v1/acquisition/runtime-planning-issues
GET    /api/v1/acquisition/runtime-planning-issues/{issue_id}
POST   /api/v1/acquisition/runtime-planning-issues/{issue_id}/dismiss

GET    /api/v1/acquisition/credential-connections
GET    /api/v1/acquisition/credential-connections/{credential_id}
POST   /api/v1/acquisition/credential-connections
POST   /api/v1/acquisition/credential-connections/{credential_id}/validate
POST   /api/v1/acquisition/credential-connections/{credential_id}/rotate
POST   /api/v1/acquisition/credential-connections/{credential_id}/revoke

GET    /api/v1/acquisition/browser-sessions
GET    /api/v1/acquisition/browser-sessions/{session_id}
GET    /api/v1/acquisition/browser-traces/{trace_id}
POST   /api/v1/acquisition/browser-sessions/{session_id}/terminate

GET    /api/v1/acquisition/permissions
POST   /api/v1/acquisition/permissions/{permission_id}/revoke
POST   /api/v1/acquisition/permissions/{permission_id}/renew

GET    /api/v1/acquisition/journal
```

Route rules:
- All list routes require pagination with default limits.
- All records are scoped by tenant and user.
- Activation routes require current user identity.
- Approval routes create audit records.
- Activation cannot run before verification passes.
- Activation must fail with `VERIFICATION_STALE` when the recomputed
  `activation_snapshot_hash` differs from the approved snapshot.
- Development patch handoff never mutates the working tree. It returns a patch
  artifact/ref and `handoff_ready` status only.
- RuntimePlanningIssue routes are read/manage routes only; they cannot activate
  acquisition targets.
- Credential routes never return raw secret material.
- Browser trace routes return redacted artifacts only and enforce tenant/user
  scope plus trace retention policy.

## 20. Events and Observability

SSE event names:
- `acquisition_gap`
- `acquisition_exploration`
- `acquisition_recommendation`
- `acquisition_approval_required`
- `acquisition_verification`
- `acquisition_activation`
- `acquisition_runtime_planning_issue`
- `acquisition_permission`
- `acquisition_browser_trace`

Metrics:
- `acquisition_gaps_created`
- `acquisition_gaps_deduped`
- `acquisition_explorations_started`
- `acquisition_explorations_succeeded`
- `acquisition_explorations_failed`
- `acquisition_recommendations_created`
- `acquisition_proposals_created`
- `acquisition_activations_approved`
- `acquisition_activations_rejected`
- `acquisition_verifications_passed`
- `acquisition_verifications_failed`
- `acquisition_verifications_stale`
- `acquisition_policy_blocks`
- `acquisition_rollbacks`
- `acquisition_permissions_revoked`
- `acquisition_permissions_renewed`
- `acquisition_runtime_planning_issues_created`
- `acquisition_mcp_reconnect_failures`
- `acquisition_api_tool_failures`
- `acquisition_workspace_connector_blocks`
- `acquisition_browser_sessions_started`
- `acquisition_browser_sessions_cleaned`
- `acquisition_browser_runtime_confirmations`

Audit actions:
- `acquisition.gap.created`
- `acquisition.exploration.approved`
- `acquisition.exploration.started`
- `acquisition.recommendation.created`
- `acquisition.proposal.created`
- `acquisition.activation.approved`
- `acquisition.verification.started`
- `acquisition.verification.passed`
- `acquisition.verification.failed`
- `acquisition.target.activated`
- `acquisition.target.rollback`
- `acquisition.policy.blocked`
- `acquisition.activation.snapshot_mismatch`
- `acquisition.permission.revoked`
- `acquisition.permission.renewed`
- `acquisition.runtime_planning_issue.created`
- `acquisition.development_patch.handoff_ready`
- `acquisition.browser.trace.created`

## 21. Security and Policy

Hard guard rules:
- Generated Markdown cannot mutate runtime state.
- Proposal approval cannot be inferred from chat text unless routed through an
  explicit confirmation action.
- Exploration approval cannot imply activation approval.
- Activation approval cannot bypass target-specific runtime confirmation.
- Worker standing permission cannot exceed target permission bundles.
- Development patch proposals cannot activate as runtime production code.
- Credentials must be redacted in logs, Journal, SSE events, and artifacts.
- Host directory access must use explicit allowlists and path traversal checks.
- API, MCP HTTP/SSE, Browser, and networked Code-as-Action calls must pass
  egress policy checks that deny private networks, loopback, link-local,
  multicast, metadata endpoints, DNS rebinding, unsafe redirects, and oversized
  responses.
- MCP stdio servers must run only inside the MCP Runtime Isolation boundary.
  Backend or worker subprocess execution of user-approved MCP commands is
  forbidden.
- MCP stdio runtime must enforce approved command provenance, image or package
  digest, filesystem policy, network policy, resource limits, output limits,
  lifecycle cleanup, and no Docker socket or host filesystem access.
- Browser automation external writes require runtime confirmation.
- Forbidden tasks cannot create executable acquisition paths.
- Activation approval must bind to `activation_snapshot_hash`.
- MCP, API, Workspace, and Browser configurations store credential references,
  never raw credential material.
- Workspace Connector runtime accepts connector ids, never arbitrary host paths.
- Browser automation must use isolated profiles and record screenshot/DOM/action
  traces without exposing secret material.
- Built-in browser automation is a product runtime owner; gstack QA browser is
  not a production runtime dependency.

Forbidden acquisition:
- Bypass captcha, paywall, login, or authorization.
- Obtain, guess, exfiltrate, or misuse credentials.
- Perform hidden scraping or malicious automation.
- Execute payment, booking, message send, delete, or external write without
  runtime confirmation.
- Modify production code or deployment config silently.

## 22. Journal Contract

Journal name:
`ACQUISITION.md`

Role:
Private generated evidence, not authority.

Generation:
- Regenerate on Gap, Exploration, Recommendation, Proposal, Verification,
  Activation, Rollback, or dismissal state changes.
- Use deterministic ordering.
- Include source references and target refs.
- Redact credentials and sensitive values.

Suggested structure:

```text
# ACQUISITION.md

This user-private journal is generated from durable Acquisition records.
It is evidence, not authority.

## Open Gaps
...

## Proposals Needing Approval
...

## Activated Capabilities
...

## Rejected or Dismissed
...

## Runtime Planning Issues
...

## Development Patch Proposals
...
```

Rules:
- UI can render the Journal.
- Agent may cite the Journal as evidence.
- Agent may not treat Journal text as permission.
- Manual filesystem edits are ignored and overwritten by regeneration.

## 23. Relationship to V2

V2 Candidate generation remains success-driven:
- Memory remembers knowledge.
- Skill remembers method.
- Worker remembers executable work.

V3 Acquisition is gap-driven:
- Gap remembers missing ability.
- Exploration remembers attempted acquisition.
- Recommendation remembers possible acquisition paths.
- Proposal remembers approval-ready activation plan.
- ActivationTarget remembers the target owner handoff.
- RuntimePlanningIssue remembers cases where existing capabilities were missed
  rather than acquired.
- DevelopmentPatchProposal remembers self-modification handoff evidence without
  changing runtime ability.

Bridge rules:
- Exploration success can create V2 candidates.
- Worker target activation uses V2 Worker verification and activation.
- Skill and Memory target activation use existing owners.
- Acquisition does not put Gap, Recommendation, or Proposal records into the V2
  Capability Inbox.
- V2 failure and Worker fallback may create V3 Gap or Recommendation records.
- Planner misses may create RuntimePlanningIssue and then V2 Skill/Worker
  improvement candidates, but not Acquisition Gaps.

## 24. Product Examples

### 24.1 Train Query

User asks for train options.

Flow:
- Existing tools cannot provide stable train data.
- Gap created: missing stable train query capability.
- Safe exploration attempts public data.
- Exploration fails due unstable source or login requirement.
- Recommendation: train query MCP or browser automation.
- Proposal primary target: MCP Tool.
- Secondary targets: Train Query Worker, ticket-query risk Skill, user travel
  preference Memory.
- User approves activation.
- Verification queries a fixture route.
- MCP activates. Worker draft is verified and activated through V2 rules.

### 24.2 Local Files

User asks Agent to process a folder on the local machine.

Flow:
- Gap created: missing workspace connector.
- Exploration requires approval because host directory access is outside run
  workspace.
- Proposal primary target: Workspace Connector.
- User selects exact path and read/write mode.
- Verification checks path allowlist and read/list/write according to mode.
- Verification confirms Docker Desktop or server mount mapping into runtime.
- Connector activates with standing permission inside that path only.

### 24.3 Weather API

Public weather scraping is unreliable.

Flow:
- Gap created: unstable weather source.
- Safe exploration tries public endpoint.
- Recommendation: configure weather API.
- Proposal primary target: API Tool.
- Secondary target: Weather Summary Worker.
- Verification calls test city/date and checks response schema.
- API tool activates, Worker follows V2 activation.

### 24.4 Development Patch Proposal

Agent discovers Chainless lacks a durable connector type.

Flow:
- Gap created: requires product code change.
- Recommendation: development patch proposal.
- Proposal kind: development_patch_proposal.
- Verification produces patch, tests, rollback, and review checklist.
- Proposal reaches `handoff_ready`; no runtime activation occurs.
- User must explicitly start development workflow.

### 24.5 Planner Miss

Agent tells the user it cannot read a file, but an approved WorkspaceConnector
already exists.

Flow:
- Do not create CapabilityGap.
- Create RuntimePlanningIssue: `planner_missed_existing_tool`.
- Link available capability ref to the WorkspaceConnector.
- Generate a Skill or Worker improvement candidate if evidence is strong.
- Future eval checks the planner uses the connector.

## 25. Testing and Verification Plan

Backend tests:
- Gap creation from tool failure.
- No Gap for missing user input, greeting, transient retryable failure, or
  planner-missed existing tool.
- Safe exploration auto-runs only within public/read-only/run-workspace bounds.
- Approval-required exploration blocks until approved.
- Exploration success creates V2 candidate through bridge.
- Exploration failure creates Recommendation.
- Proposal requires primary target.
- Composite target records partial activation when secondary target fails.
- Activation cannot run before verification.
- Activation fails with `VERIFICATION_STALE` when `activation_snapshot_hash`
  changes after verification or approval.
- Standing Permission blocks out-of-bound actions.
- Standing Permission requires renewed approval after WorkerVersion, tool config,
  domain, path, credential, write scope, network scope, or side-effect expansion.
- Runtime confirmation is required for destructive/external writes.
- Journal generation is user-private, deterministic, redacted, and
  non-authoritative.
- Cross-user and cross-tenant isolation.
- Pagination and default limits for all list endpoints.
- Durable MCPServerConfiguration reloads and reconnects after backend restart.
- MCP HTTP/SSE egress policy blocks private network, unsafe redirect, oversized
  response, and credential leakage paths.
- MCP stdio configurations require MCP Runtime Isolation, approved command
  provenance, image/package digest, filesystem and network policy, resource
  limits, output limits, cleanup, and restart/reconnect behavior.
- MCP stdio activation fails closed if runtime isolation is unavailable, if the
  command would run in the backend/worker container, or if command provenance
  cannot be verified.
- APIToolConfiguration validates schema, rate limit, timeout, retry, and error
  contract.
- APIToolConfiguration blocks SSRF, DNS rebinding, unsafe redirects, disallowed
  content types, oversized responses, and non-idempotent writes without
  confirmation.
- CredentialConnection stores encrypted or external-vault-backed secret refs,
  returns redacted metadata only, rotates secret generations, revokes dependent
  target execution, and invalidates activation snapshots.
- WorkspaceConnector blocks path traversal and raw host path access.
- WorkspaceConnector propagates connector id and mount generation through file
  tools, sandbox proxy, and Code-as-Action without raw host paths or
  caller-provided `workspace_base`.
- BrowserAutomationConfiguration enforces domain allowlist, isolated profiles,
  trace capture, timeouts, and cleanup.
- BrowserAutomationConfiguration verifies Docker runtime/image health, resource
  quotas, trace retention, redaction, no host/Docker socket access, and
  confirmation-resume policy parity.
- RuntimePlanningIssue is created for planner misses and does not enter
  Acquisition Gap lists.
- Development patch proposals stop at `handoff_ready` and do not mutate runtime
  or working tree.
- Development patch proposals store base commit, patch artifact ref, digest,
  test plan, rollback plan, review checklist, and fail if the patch no longer
  applies to the current git revision.

Security tests:
- No credential appears in Journal, SSE, audit details, or artifacts.
- Host path traversal is blocked.
- API/MCP/Browser network egress denies SSRF, DNS rebinding, unsafe redirects,
  private IP ranges, metadata endpoints, and oversized responses.
- MCP stdio cannot execute in the backend or worker process/container.
- MCP stdio rejects unapproved command, args, image, package digest, env source,
  filesystem policy, network policy, and resource limit changes.
- MCP stdio runtime cannot access Docker socket, backend filesystem, host
  filesystem, unapproved workspace connector mounts, or non-allowlisted network.
- Browser external write requires runtime confirmation.
- Development patch proposal cannot activate as runtime capability.
- Development patch handoff cannot stage, commit, push, deploy, or edit the
  working tree.
- Generated Journal edits do not mutate DB state.
- MCP/API/Browser credential material is never exposed in logs, SSE, Journal,
  browser traces, or artifacts.

Frontend/browser QA:
- Chat shows lightweight Gap, Exploration, Recommendation, and Approval cards.
- Right panel shows current-run Acquisition cards without scroll/style
  regression.
- Settings Acquisition lists Gaps, Explorations, Recommendations, Proposals,
  Verifications, Activations, and Journal.
- Approve Exploration and Approve Activation are separate actions.
- Rollback is visible for activated targets.
- V2 Capability Inbox remains focused on Memory, Skill, and Worker candidates.
- Existing chat, right panel, sidebar, Settings, and scroll behavior are
  preserved.
- Acquisition UI states show problem, cause, risk, next step, and recovery
  without changing existing visual style.
- Screenshots and DOM/scroll assertions cover chat notices, right panel cards,
  Settings Acquisition, sidebar actions, and existing Settings navigation.

Eval scenarios:
- Low-risk public data task auto-explores and records ExplorationRun.
- Failed train query creates Gap and Recommendation, not a fake successful
  answer.
- Local folder task requests approval for Workspace Connector.
- Weather unreliable source recommends API Tool and can activate a Worker after
  verification.
- Browser automation task launches built-in isolated browser runtime, captures
  screenshot/DOM/action trace, and pauses before external write.
- Development patch path creates patch proposal only, never runtime activation.
- Planner miss creates RuntimePlanningIssue, not CapabilityGap.

## 26. Plan-Time Complexity Check

Likely high-pressure files:
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/capabilities/service.py`
- `frontend/src/stores/capability-store.ts`
- Settings shell components

Better file boundary:
- Add `backend/app/core/acquisition/` for lifecycle, rules, policy, journal,
  orchestration, schemas, and tasks.
- Add `backend/app/api/v1/acquisition.py` for public route contract.
- Add `backend/app/models/acquisition.py` for persistence.
- Add or extend target-owner modules:
  - `backend/app/core/tools/mcp/` and MCPServerConfiguration persistence.
  - `backend/app/core/tools/mcp_runtime/` for isolated stdio MCP execution.
  - `backend/app/core/tools/api/` for generic API tool execution.
  - `backend/app/core/workspace_connectors/`.
  - `backend/app/core/browser_automation/`.
  - `backend/app/core/credentials/` for V3 acquired capability credential refs.
  - `backend/app/core/security/egress_policy.py` or equivalent owner for
    reusable egress validation.
  - `backend/app/core/planning_issues/`.
- Add a frontend `acquisition-store` or equivalent dedicated owner rather than
  overloading capability store.
- Add Settings Acquisition section using existing component patterns.
- Add chat/right-panel cards using existing visual primitives.

Recommendation:
Split task by owner. Do not edit-in-place into the existing V2 capability owner
except for narrow bridge calls.

## 27. ADR Signals

ADR recommended after implementation starts:
- Acquisition Layer as canonical owner for missing capability lifecycle.
- Generated ACQUISITION.md as evidence, not authority.
- Two-phase approval model.
- Activation snapshot hash as verification/activation drift guard.
- Composite Target model with one primary target.
- Standing Permission versus Runtime Confirmation boundary.
- Durable MCPServerConfiguration as Tool/MCP runtime owner.
- MCP Runtime Isolation as the only stdio MCP execution path.
- Generic APIToolConfiguration as runtime owner.
- WorkspaceConnector as approved path mapping owner.
- Built-in Browser Automation runtime owner.
- CredentialConnection scope as V3 acquisition credential owner, with existing
  LLM/channel secret owners retained unless explicitly bridged later.
- RuntimePlanningIssue as planner miss owner separate from Acquisition Gap.
- Development patch proposal as development workflow handoff, not runtime
  activation.

## 28. Acceptance Criteria

V3 is complete when:
- Capability Gap is a first-class durable private object.
- Safe Code-as-Action exploration is recorded and bounded by policy.
- Recommendations and Proposals are durable, reviewable, and auditable.
- Exploration approval and activation approval are separate.
- Composite targets support one primary target and multiple secondary targets.
- Runtime activation targets bridge to canonical MCP, API Tool, Workspace
  Connector, Browser Automation, Worker, Skill, and Memory owners.
- MCP, API Tool, Workspace Connector, and Browser Automation have durable
  runtime owners and restart-safe configuration.
- MCP stdio activation is isolated by `core/tools/mcp_runtime`; user-approved
  MCP commands never execute in the backend or worker process/container.
- MCP stdio runtime verifies command provenance, image/package digest,
  filesystem/network policy, resource/output limits, cleanup, and restart
  behavior before activation.
- CredentialConnection is the only owner for user-private credential material
  acquired through V3 capability acquisition, while existing LLM/channel secret
  owners remain authoritative unless explicitly bridged by a later approved
  migration.
- API, MCP HTTP/SSE, Browser, and networked Code-as-Action calls are bounded by
  explicit egress policies that block SSRF, unsafe redirects, private networks,
  metadata endpoints, DNS rebinding, and oversized responses.
- Browser Automation has a compose-managed or otherwise declared runtime image,
  health check, resource limits, trace retention, profile isolation, and cleanup
  contract independent of gstack QA.
- Workspace Connector propagates connector ids and mount generations through
  file tools, sandbox proxy, and Code-as-Action without raw host paths.
- Development patch proposals reach `handoff_ready` and never become runtime
  activation.
- Activation uses `activation_snapshot_hash` and blocks stale or drifted
  activation.
- Standing Permission is supported only for bounded safe/risky behavior.
- Runtime confirmation blocks destructive or external-write actions.
- ACQUISITION.md is generated, private, redacted, read-only, and
  non-authoritative.
- V2 Capability Inbox remains unpolluted by Gap and Acquisition records.
- RuntimePlanningIssue is separate from Acquisition Gap and can generate
  Skill/Worker improvement candidates.
- Browser QA proves UI additions preserve existing style and scroll behavior.

## 29. Spec Self-Review

Placeholder scan:
No placeholders remain. Deferred items are named as non-goals or ADR signals.

Internal consistency:
The spec consistently treats Acquisition as the lifecycle owner, runtime owners
as activation authorities, and Journal as evidence only.

Scope check:
This is a high-complexity V3 design that can be planned as a single V3
execution plan with multiple workstreams. It should not be reduced to a UI-only
or Gap-only MVP.

Ambiguity check:
The difference between exploration approval and activation approval is explicit.
The difference between Standing Permission and Runtime Confirmation is explicit.
The difference between V2 Capability Candidates and V3 Acquisition records is
explicit. CredentialConnection is explicit as a supporting owner, not a runtime
ActivationTarget. CredentialConnection does not silently replace existing
LLM/channel secret owners. Development patch proposal handoff is explicit as
artifact handoff, not a working-tree mutation. MCP stdio runtime isolation is
explicit; backend-process command execution is forbidden.

Boundary check:
Hard safety boundaries, ownership boundaries, non-goals, compatibility, and ADR
signals are explicit. The spec does not permit silent self-modification or
runtime authority from Markdown.
