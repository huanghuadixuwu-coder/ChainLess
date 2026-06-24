# Capability Acquisition Layer

Date: 2026-06-24

## Purpose

The Capability Acquisition Layer lets Chainless treat missing capability as a
first-class runtime object instead of silently failing or waiting for developers
to add builtin tools. The Agent can record a Gap, explore safe temporary
solutions, recommend durable targets, create activation Proposals, verify them,
and activate only after user approval and audit.

This layer connects the product thesis:

- Code-as-Action explores one-off temporary capability.
- Memory, Skill, and Worker preserve reusable facts, methods, and executable
  work patterns.
- MCP, API Tool, Workspace Connector, Browser Automation, and
  development_patch_proposal cover external capability acquisition without
  silent production self-modification.

## Canonical Owners

- `backend/app/models/acquisition.py` owns V3 durable domain state.
- `backend/app/core/acquisition/lifecycle.py` owns Gap, Exploration,
  Recommendation, and Proposal lifecycle transitions.
- `backend/app/core/acquisition/verification.py` owns verification runs and the
  verified `activation_snapshot_hash`.
- `backend/app/core/acquisition/activation.py` owns the activation state machine
  and activation saga.
- `backend/app/core/acquisition/rollback.py` owns rollback saga,
  compensation, manifest hiding, permission revocation, session termination,
  journal/audit updates, and idempotent replay.
- `backend/app/core/acquisition/policy.py` owns final permission and
  confirmation decisions. Target owners may narrow policy, but they do not
  bypass this gate.
- `backend/app/core/security/egress_policy.py` owns network and egress checks.
- `backend/app/core/credentials/` owns `CredentialConnection` storage,
  rotation, revocation, and dependent snapshot invalidation.
- `backend/app/core/workspace_connectors/` owns Workspace Connector
  configuration, host path approval binding, sanitized mount bundles, and
  runtime materialization.
- `backend/app/core/tools/mcp_runtime/` and `mcp-runtime/` own isolated MCP
  stdio execution.
- `backend/app/core/tools/api_runtime/` owns acquired API Tool execution.
- `backend/app/core/browser_automation/` and `browser-runtime/` own Browser
  Automation runtime execution and trace boundaries.
- `backend/app/core/planning_issues/` owns `RuntimePlanningIssue`; acquisition
  only cross-links to it.
- `backend/app/core/observability/runtime_metrics.py` owns acquisition metric
  names and safe labels.

## State Machine

Runtime activation Proposals must move through the hard order:

```text
drafted -> verification_requested -> verifying -> verified(snapshot_hash)
-> activation_requested -> activation_approved(hash) -> activating -> activated
```

Approval before verification is forbidden. Activation approval binds the exact
verified `activation_snapshot_hash`; stale approval reuse after re-verification
is rejected. A partial target failure moves the Proposal to
`partial_activation`, and rollback moves it to `rolled_back` after target
compensation.

`development_patch_proposal` is deliberately not a runtime target. It is a
durable handoff containing patch, test, rollback, and review evidence; no
runtime path may edit, commit, push, deploy, or mutate production code.

## Composite Targets

A Proposal can contain a primary target plus secondary targets. Primary failure
blocks activation. Secondary failure records `partial_activation`, preserves
the activated primary evidence, and exposes rollback. Each target has its own
permission bundle, verification evidence, audit trail, activation result, and
rollback path.

Supported activation target families:

- `mcp_server`: isolated MCP stdio runtime through `mcp-runtime`.
- `api_tool`: generic API Tool runtime with egress, schema, retry, timeout,
  content-type, size, and write confirmation checks.
- `workspace_connector`: approved local/workspace path mapping, exposed to file
  tools and sandbox/code-as-action through sanitized mount bundles.
- `browser_automation`: compose-managed Browser Runtime with isolated profile,
  allowed hosts, redacted screenshots/traces, action limits, and cleanup.
- `worker`, `skill`, `memory`: V2 owners remain source of truth for reusable
  capability effects.
- `development_patch_proposal`: review handoff only, not runtime activation.

## Runtime Boundaries

MCP stdio and Browser Automation are separate images/services. Neither shares
the sandbox-proxy Docker socket authority. MCP stdio receives only approved
payload hashes, pinned image refs, pinned package digests, command provenance,
resource limits, no raw env, no backend filesystem access, no host filesystem
access, and no Docker socket. Browser Automation uses its own runtime URL,
isolated profile, request interception, redacted trace output, and explicit
external-write confirmation boundaries.

Workspace Connectors never expose raw host paths to the Agent. The backend
stores trusted path material encrypted, then materializes approved read-only
runtime snapshots under connector paths that file tools and Code-as-Action can
read.

Acquired tools are exposed through a per-user tool manifest. Activation bumps
manifest versions; rollback, permission revoke, or credential revoke hides tools
from future and resumed runs. Normal execution and confirmation resume both
must pass the same acquisition policy gate.

## Disabled Mode

`ACQUISITION_ENABLED` and runtime capability flags can disable V3 acquisition
without breaking normal chat, V2 inbox, Workers, file tools, Code-as-Action, or
ordinary Agent execution. Disabled mode must not enqueue acquisition records.

## Journal And UI

The Acquisition API is rooted at `/api/v1/acquisition/*`. List routes use
pagination/default limits/max limits and tenant/user isolation.

`ACQUISITION.md` is a generated, user-private, read-only journal rendered from
durable records. It is evidence, not authority. Users cannot manually edit it
through Chainless; changes go through UI/API/audit paths.

The frontend extends the existing chat right panel and Settings shell without
changing visual style. It must show problem, cause, risk, next step, recovery,
separate exploration/activation approvals, revocation, rollback visibility,
and empty/disabled states.

## Observability

Acquisition analysis uses a durable outbox with bounded batch size, lease,
retry, timeout metrics, idempotency, and safe labels. Credential material, raw
paths, raw browser inputs, cookies, and secrets must not appear in Journal,
SSE, audit, artifacts, browser traces, logs, or metrics labels.

`RuntimePlanningIssue` exists so planner misses, bad tool choice, and missing
user input do not pollute acquisition Gap data. Only true capability deficits
become Gaps.

## Verification Baseline

The V3 layer is considered healthy only when these pass together:

- Full backend test suite.
- Live Docker Workspace Connector/runtime tests.
- Frontend lint/build.
- Compose build and health smoke.
- Windows browser QA suite `capability-acquisition`.
- Eval suites `capability_acquisition` and `spec_complete`.
- Acquisition observability tests.

