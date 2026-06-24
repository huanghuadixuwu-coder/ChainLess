# V3 Capability Acquisition Layer Checkpoint

## TodoCheckpointDraft

Current todo: Workstream 6 complete; ready for Workstream 7.

Completed todos:
- Plan engineering review completed and patched.
- Execution entered subagent-driven mode.
- Long-task intent/checkpoint/evidence records initialized.
- W1 implementation subagent completed code changes but Docker verification was
  blocked by unavailable Docker Desktop/Linux engine.
- W1 spec compliance review found 3 gaps: typed proposal target/permission
  contracts, explicit source-evidence fields, and incomplete required-column
  model test coverage.
- W1 spec-fix subagent resolved those gaps; spec re-review passed.
- W1 Docker verification passed for acquisition API contract and model tests:
  `16 passed, 2 warnings`.
- W1 code quality review found 2 Important issues: missing
  `verification_requested` / `activating` proposal states and plain string
  request enums that should be typed before W2.
- W1 quality-fix subagent resolved those issues plus MCP pairing/numeric
  constraints; controller reran Alembic + W1 tests: `22 passed, 2 warnings`.
- W1 spec re-review found 2 remaining schema gaps: unconstrained
  `ActivationTargetContract.activation_status` and raw `AcquisitionJournalView`
  entries.
- W1 final schema-fix subagent resolved those gaps; controller reran Alembic +
  W1 tests: `25 passed, 2 warnings`.
- W1 final spec review passed.
- W1 final code quality review found 2 Important drift risks: explicit
  `source_evidence` was not persisted separately, and schema validators did not
  match MCP/StandingPermission DB constraints.
- W1 post-fix quality review found 1 Critical migration defect: three explicit
  PostgreSQL constraint names exceeded the 63-character identifier limit.
  Reviewer left the test DB at `0011` after failed re-upgrade.
- W1 migration-name fix subagent resolved the Critical issue; controller reran
  `alembic downgrade 0011 && alembic upgrade head && pytest ...`: `28 passed,
  2 warnings`.
- W1 final closure review found no Critical or Important issues. W1 is ready
  for W2.
- W2.1 implementation added the acquisition repository and lifecycle owner for
  Gap, ExplorationRun, Recommendation, and Proposal state changes.
- W2.1 initial spec review found lifecycle gaps in status validation,
  premature activation, fragile idempotency, and split-owner dedupe.
- W2.1 spec-fix passes resolved those issues. Final spec review passed with
  evidence that proposal verification order is enforced, exploration
  idempotency ignores changed `source_run_id`, and W2.1 activation remains
  blocked until W2.2 snapshot verification exists.
- W2.1 code-quality review found production blockers around parent-scope
  validation, durable idempotency, audit transaction boundaries,
  proposal-kind-aware transitions, unsafe approval validation, and occurrence
  evidence retention.
- W2.1 quality-fix passes resolved those issues, including a durable
  `acquisition_idempotency_records` authority, non-committing audit helper,
  parent-scope validation, approval ownership validation, proposal-kind
  transition maps, and bounded source-evidence merging.
- W2.1 final code-quality re-review found no Critical or Important issues.
- Controller final W2.1 verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py` -> `54 passed, 2 warnings`.
- Controller final audit compatibility verification passed:
  `pytest -q tests/test_audit.py tests/test_acquisition_lifecycle.py` ->
  `32 passed, 2 warnings`.
- W2.2 implementation added split owners for activation snapshots,
  verification runs, and activation approval/start guards:
  `backend/app/core/acquisition/snapshot.py`,
  `backend/app/core/acquisition/verification.py`, and
  `backend/app/core/acquisition/activation.py`.
- W2.2 initial spec review found Critical gaps in credential-generation
  snapshot redaction and generic repository bypass of guarded activation
  states, plus Important gaps in `activating -> activated` and runtime
  `verified -> handoff_ready` transitions.
- W2.2 spec-fix passes resolved those gaps: credential refs and
  `secret_generation` remain in snapshots while raw secrets are omitted;
  generic repository transitions into `activation_approved`, `activating`, and
  `activated` require `guarded_transition=True`; runtime proposals no longer
  enter `handoff_ready`; and the `activating -> activated` edge exists for the
  later activation owner.
- W2.2 code-quality review found Important issues around mutable completed
  verification evidence, incomplete approval/start idempotent replay, and
  approval binding stale verification evidence.
- W2.2 quality-fix passes made completed verification rows immutable except
  exact replay, added full request-equivalence metadata for approval/start
  replay, locked/re-hashed verification evidence during approval, and required
  approval-time snapshot recomputation before writing `activation_approved`.
- W2.2 final spec re-review passed with no Critical or Important issues.
- W2.2 final code-quality re-review found no Critical or Important issues.
- Controller final W2.2 snapshot verification passed:
  `pytest -q tests/test_acquisition_snapshot.py` -> `24 passed, 2 warnings`.
- Controller final W2.2 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py` ->
  `78 passed, 2 warnings`.
- Controller final W2.2 audit compatibility verification passed:
  `pytest -q tests/test_audit.py tests/test_acquisition_lifecycle.py
  tests/test_acquisition_snapshot.py` -> `56 passed, 2 warnings`.
- W2.3 implementation added activation saga orchestration, rollback owner,
  no-side-effect activation/rollback hooks, and user-scoped manifest hiding
  support.
- W2.3 spec compliance review passed with no Critical or Important issues.
  Reviewer noted manifest version bumps remain later-scope.
- W2.3 code-quality review found one Important issue: secondary-only
  `target_ids` could activate without primary target coverage.
- W2.3 quality-fix pass added secondary-only activation guards, required all
  materialized targets to be active before proposal `activated`, and extended
  tests so primary failure proves secondary targets are not executed.
- W2.3 code-quality re-review found no Critical or Important issues. The
  remaining Minor defensive assertion was also added before closure.
- Controller final W2.3 verification passed:
  `pytest -q tests/test_acquisition_lifecycle.py::test_secondary_only_target_ids_require_primary_before_proposal_activated
  tests/test_acquisition_lifecycle.py tests/test_acquisition_policy.py
  tests/test_tool_manifest.py` -> `36 passed, 2 warnings`.
- Controller final W2.3 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py` -> `88 passed,
  2 warnings`.
- W2.4 implementation added generated, user-private acquisition journal
  rendering, tenant/user-scoped read-model queries, section limits/totals/API
  links, redaction, and idempotent persisted snapshot writing.
- W2.4 initial spec review found Important issues in scalar redaction and
  non-canonical Runtime Planning Issue links. Fixes applied scalar redaction
  across rendered fields and switched links/source refs to
  `/api/v1/acquisition/runtime-planning-issues`.
- W2.4 spec re-review passed with no Critical, Important, or Minor issues.
- W2.4 code-quality review found Important issues in concurrent first-time
  snapshot writes and aggregate markdown size. Fixes added a partial unique
  snapshot index, PostgreSQL upsert, per-item JSON truncation, final persisted
  snapshot byte budgeting, and regression tests.
- W2.4 final code-quality re-review found no Critical, Important, or Minor
  issues.
- Controller final W2.4 journal verification passed:
  `pytest -q tests/test_acquisition_journal.py` -> `7 passed, 2 warnings`.
- Controller final W2.4 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `95 passed, 2 warnings`.

- W3.1 implementation added the V3 CredentialConnection owner with encrypted
  secret storage, redacted response serialization, runtime resolution,
  rotate/revoke handling, dependent activation snapshot invalidation, and
  dependent target/config disabling.
- W3.1 spec review initially found Critical gaps around revocation/rotation
  invalidating `activating` proposals, fresh verification accepting revoked
  credential refs, runtime-path revocation coverage, and dependent target/config
  disabling. Fixes closed those gaps and final spec re-review passed.
- W3.1 code-quality review found Important issues in malformed credential-ref
  handling and direct durable config disabling when proposal bundles are stale.
  Fixes normalized malformed scalar refs to canonical
  `CREDENTIAL_REFERENCE_NOT_FOUND`, disabled direct API/browser/MCP config refs
  independently of proposal-bundle discovery, and added regressions.
- W3.1 final code-quality re-review found no Critical or Important issues.
- Controller final W3.1 focused verification passed:
  `pytest -q tests/test_acquisition_snapshot.py tests/test_acquisition_policy.py`
  -> `36 passed, 2 warnings`.
- Controller final W3.1 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `105 passed, 2 warnings`.
- W3.2 implementation added `core/security/egress_policy.py` as a pure
  reusable egress owner with host normalization, allowlist checks, DNS evidence
  hooks, rebinding denial, redirect target validation, private/metadata IP
  denial, response byte caps, streaming byte checks, runtime DNS/connect guard,
  and activated `arbitrary_network` denial.
- W3.2 spec review passed with no Critical or Important gaps.
- W3.2 code-quality review found Important security-owner gaps in mandatory
  response byte caps, easy-to-misuse DNS/connect sequencing, and legacy numeric
  IPv4 forms. Fixes added activated-runtime cap requirements,
  `validate_egress_response_chunk`, `prepare_egress_runtime_guard`,
  `validate_runtime_egress`, non-canonical IPv4 rejection, invalid-port
  normalization, and regression coverage.
- W3.2 final code-quality re-review found no Critical or Important issues.
  A Minor malformed prior-DNS-evidence issue was also fixed and covered.
- Controller final W3.2 focused verification passed:
  `pytest -q tests/test_acquisition_policy.py` -> `27 passed, 2 warnings`.
- Controller final W3.2 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `125 passed, 2 warnings`.
- W3.3 implementation added `core/acquisition/policy.py` as the final
  acquisition permission gate with permission bundle validation, standing
  permission lookup, expiration/revocation checks, boundary snapshot
  comparison, confirmation context binding, egress-policy layering, and
  target-policy narrowing.
- W3.3 spec review found Important gaps in standing permission boundary
  completeness, target permission bundle inheritance, and free-form action
  category confirmation bypass. Fixes added full boundary snapshots, removed
  target bundle inheritance in activation materialization, expanded action
  aliases, and required confirmation from effective request/bundle risk.
- W3.3 final spec re-review passed with no Critical or Important gaps.
- W3.3 code-quality review found Important gaps in risk-level vocabulary,
  unknown action category fail-open behavior, and `expires_at` string
  persistence, plus a Minor list-of-dicts subset reliability issue. Fixes
  aligned risk ordering to `safe/risky/high_risk/blocked`, made unknown actions
  require confirmation, normalized `expires_at` before StandingPermission
  persistence, and canonicalized list comparisons.
- W3.3 final code-quality re-review found no Critical or Important issues.
- Controller final W3.3 targeted verification passed:
  `pytest -q tests/test_acquisition_policy.py tests/test_acquisition_lifecycle.py`
  -> `98 passed, 2 warnings`.
- Controller final W3.3 migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `165 passed, 2 warnings`.
- Controller W3 closure focused verification passed:
  `pytest -q tests/test_acquisition_policy.py tests/test_acquisition_lifecycle.py
  tests/test_acquisition_snapshot.py` -> `127 passed, 2 warnings`.
- Controller W3 closure migration/acquisition verification passed:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `165 passed, 2 warnings`.
- Confirmed `git status --short -- frontend` returned no frontend changes
  during W3 closure.
- W4.1 implementation added isolated MCP stdio runtime ownership:
  `backend/app/core/tools/mcp_runtime/`, `mcp-runtime/`, durable
  `MCPServerConfiguration` registration/recovery, startup recovery wiring,
  and compose-managed `mcp-runtime` isolation.
- W4.1 retired backend-process stdio MCP execution. The backend now delegates
  stdio discovery/calls to `mcp-runtime`; the only `mcp.client.stdio` usage is
  inside the isolated runtime service.
- W4.1 quality fixes made MCP configuration tenant-scoped, added migration
  `0013_tenant_scoped_mcp_config_identity`, deduped historical enabled
  duplicates before the partial unique index, serialized same-key durable
  register/unregister/recovery with process-local locks, and made failed
  replacement preserve the existing enabled runtime/config.
- W4.1 remote HTTP/SSE direct transport is fail-closed until a future safe
  remote MCP transport owner can provide connected-peer evidence and streaming
  response-cap enforcement.
- W4.1 spec compliance review passed after fixing durable restart recovery,
  runtime-side approved payload binding, explicit egress fail-closed behavior,
  and runtime-side policy validation.
- W4.1 code-quality review passed after fixing replacement atomicity,
  concurrent replacement serialization, migration duplicate safety, response
  cap boundaries, and startup recovery isolation.
- Controller final W4.1 verification passed:
  `pytest -q tests/test_mcp_runtime_isolation.py tests/test_mcp_transports.py`
  -> `33 passed, 2 warnings`.
- Controller final W4.1 API compatibility verification passed:
  `pytest -q tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server
  tests/test_api_contracts.py::test_tools_mcp_failures_do_not_leak_exception_details`
  -> `2 passed, 2 warnings`.
- Controller final W4.1 migration/runtime verification passed:
  `alembic downgrade 0012 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_mcp_runtime_isolation.py
  tests/test_mcp_transports.py` -> `46 passed, 2 warnings`.
- Confirmed `git status --short -- frontend` returned no frontend changes
  during W4.1 closure.
- W4.2 implementation added the generic API tool runtime owner with
  `core/tools/api_runtime`, canonical per-user tool names, API tool activation
  hooks, registry exposure only after user-scoped activation, schema
  validation, credential reference resolution, egress checks, byte caps,
  content-type checks, retry/timeout/rate-limit contracts, and confirmation
  handling for non-idempotent/external writes.
- W4.2 spec/code-quality review passed after fixes for canonical tool-name
  collisions, credential generation binding, unsupported auth schemes,
  model-supplied confirmation bypass, no-user stream compatibility, and
  JSON-schema/runtime contract coverage.
- Controller final W4.2 verification passed:
  `pytest -q tests/test_api_tool_runtime.py tests/test_acquisition_policy.py`
  -> `92 passed, 2 warnings`.
- Controller W4.2 enhanced regression verification passed:
  `pytest -q tests/test_api_tool_runtime.py tests/test_acquisition_policy.py
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_hook_upserts_enabled_verified_manifest
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_user_scoped_tool_name_collision
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_binds_current_credential_generation
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_credential_not_allowed_for_api_tool
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_credential_target_ref_mismatch
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_unresolvable_credential_storage
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_unsupported_auth_scheme
  tests/test_sse_contract.py::test_execute_confirmed_api_tool_passes_backend_acquisition_confirmation_context
  tests/test_sse_contract.py::test_disconnected_stream_cancels_running_agent_task`
  -> `101 passed, 2 warnings`.
- W4.3 implementation added `development_patch_proposal` as a durable handoff
  owner. Runtime activation is explicitly denied; patch handoff requires an
  artifact ref, digest binding, current revision match, dry-apply validation,
  audit, rollback/test-plan/checklist fields, and no runtime repo mutation.
- W4.3 review initially found digest, local-path, dry-apply, and audit gaps.
  Fixes bound `sha256:` artifact content, rejected local/file paths, added a
  pure-Python dry-apply validator for the backend-test container, and wrote
  handoff-ready audit events.
- Controller final W4.3 verification passed:
  `pytest -q tests/test_development_patch_proposal.py` -> `11 passed,
  2 warnings`.
- Controller W4.3 regression verification passed:
  `pytest -q tests/test_development_patch_proposal.py
  tests/test_acquisition_models.py::test_development_patch_proposal_cannot_be_runtime_active
  tests/test_acquisition_lifecycle.py::test_development_patch_proposal_rejects_runtime_only_states_with_lifecycle_error
  tests/test_acquisition_journal.py::test_journal_groups_open_gaps_proposals_activated_rejected_runtime_issues_and_patch_proposals`
  -> `14 passed, 2 warnings`.
- W4.4 implementation added V2 activation targets through their existing
  owners: Worker activation/rollback via `core/workers/service.py`, Skill
  activation/disable via `core/capabilities/service.py`, Memory create/delete
  via `core/memory/persistent.py`, and a thin acquisition adapter in
  `core/acquisition/v2_targets.py`.
- W4.4 verification now rejects invalid Worker/Skill/Memory targets before
  activation approval: Worker requires object input schema and allowed tools;
  Skill requires trigger or semantic-match evidence and forbids embedded
  runtime permission; Memory requires private user scope, source evidence,
  content, and raw-secret rejection.
- W4.4 review found Important gaps in Worker update rollback, V2 side-effect
  audit accuracy, partial rollback retry idempotency, pending Worker activation
  gate restoration, and target-level transaction boundaries. Fixes added
  Worker restore snapshots, runtime/durable side-effect audit/history flags,
  already-rolled-back target skipping, shallow manifest evidence, pending
  activation-gate restoration, and nested savepoints for V2 activation and
  compensation.
- Controller final W4.4 verification passed:
  `pytest -q tests/test_v2_activation_targets.py` -> `13 passed,
  2 warnings`.
- Controller final W4.4 plan verification passed:
  `pytest -q tests/test_v2_activation_targets.py tests/test_capability_candidates.py
  tests/test_worker_runtime.py` -> `65 passed, 2 warnings`.
- Controller W4 runtime regression verification passed:
  `pytest -q tests/test_v2_activation_targets.py
  tests/test_acquisition_lifecycle.py tests/test_development_patch_proposal.py
  tests/test_api_tool_runtime.py tests/test_mcp_transports.py
  tests/test_mcp_runtime_isolation.py` -> `120 passed, 2 warnings`.
- W4.4 final spec review passed with no Critical/Important findings.
- W4.4 final code-quality review passed with no Critical/Important findings.
  Minor residual: Memory target raw-secret detection is conservative and may
  reject benign keys containing words such as `token`; this is accepted as a
  safe false-positive risk for W4.
- Confirmed `git status --short -- frontend` returned no frontend changes
  during W4.4 closure.
- W5.1 implementation added Workspace Connector owner files,
  encrypted trusted host-path source storage, sanitized mount bundle contracts,
  sandbox-proxy mount-bundle validation, approval binding, revocation handling,
  and migration `0015_workspace_connector_host_path_secret.py`.
- W5.1 initial spec review failed on non-authoritative approval validation and
  missing trusted source-of-truth for real host paths. Fixes bound connector
  creation to approved tenant/user `ToolConfirmation` records and added
  encrypted-at-rest `host_path_secret_ref` for trusted mount orchestration only.
- W5.1 second spec review failed because public `WorkspaceConnectorContract`
  exposed `host_realpath_hash`. Fix removed the hash from the public contract
  while keeping internal DB-only hash and encrypted path source.
- W5.1 code-quality review found approval replay/argument binding gaps,
  unsafe `allowlist_rule` merging, trusted-source race error handling gaps, and
  loose sandbox-proxy mount schema. Fixes bound approval to action, purpose,
  mode, host identity, tenant/user, and one-time use; sanitized caller
  allowlist metadata; converted trusted-source races to
  `WorkspaceConnectorMountError`; and required explicit v1 schema plus
  connector-id-matching paths in sandbox-proxy.
- W5.1 final code-quality re-review found no Critical/Important findings after
  adding forced fresh ORM refresh/row lock on trusted-source lookup and
  external-session disable regression coverage.
- Controller final W5.1 verification passed:
  `pytest -q tests/test_workspace_connectors.py tests/test_acquisition_api_contracts.py`
  -> `31 passed, 2 warnings`.
- Controller final W5.1 migration/API/model verification passed:
  `alembic downgrade 0014 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_workspace_connectors.py` -> `44 passed, 2 warnings`.
- Confirmed `git status --short -- frontend` returned no frontend changes
  during W5.1 closure.
- W5.2 implementation made file tools connector-aware, blocked raw
  `workspace_base` host overrides, kept run workspaces scoped under the
  configured workspace root, propagated connector mount bundles to
  sandbox/code-as-action, and wired production chat/confirmation routes to
  build server-side connector runtime context.
- W5.2 review found and fixed multiple closure gaps: missing plan test file,
  skipped live Docker connector reads, missing production route context,
  untrusted connector context embedded in tool args, lack of approved-source
  materialization into the shared Docker volume, hot-path per-connector row
  locking, and misleading `read_write` snapshot semantics.
- W5.2 now materializes approved connector sources into
  `/workspace/connectors/<connector_id>` before runtime use. Runtime
  materialized connectors are intentionally snapshot-only and exposed as
  `read_only`; durable explicit owner resolvers still preserve connector mode.
- Controller final W5.2 verification passed:
  `pytest -q tests/test_file_tools.py tests/test_workspace_connectors.py
  tests/test_file_task_closure.py` -> `42 passed, 1 skipped, 2 warnings`.
- Controller final W5.2 API route verification passed:
  `pytest -q tests/test_api_contracts.py -k connector` -> `1 passed,
  21 deselected, 2 warnings`.
- Controller final W5.2 live Docker verification passed:
  `pytest -q tests/test_workspace_connectors.py -m live_docker` -> `1 passed,
  30 deselected, 2 warnings`; the live test proves approved-source
  materialization before sandbox/code-as-action reads.
- W5.2 final spec compliance review and final code-quality review passed with
  no Critical/Important findings. All W5.2 subagents/reviewers were closed
  after completion.
- Confirmed `git diff --check` passed with CRLF warnings only and
  `git status --short -- frontend` returned no frontend changes during W5.2
  closure.
- W5.3 implementation added runtime-facing acquisition facade
  `backend/app/core/acquisition/facade.py`, bridge export wiring, and
  code-as-action engine integration. Code-as-action success/failure now emits
  structured evidence with script digest, bounded outputs, tool call metadata,
  risk classification, connector summaries, and redacted paths.
- W5.3 review found and fixed a live-runtime failure classification gap:
  sandbox runs with nonzero `exit_code` previously completed the stream and
  could be recorded as successful exploration evidence. `stream_code_as_action`
  now yields captured stdout/stderr, emits an error event, and raises so the
  engine records a failed acquisition gap/exploration.
- W5.3 code-quality review found and fixed hot-path and privacy issues:
  acquisition recording no longer blocks success or failure tool completion,
  engine-side evidence capture uses capped buffers before recorder handoff, and
  facade redaction covers Windows and POSIX host paths plus connector/workspace
  paths.
- Controller final W5.3 verification passed:
  `pytest -q tests/test_acquisition_agent_integration.py` -> `9 passed,
  2 warnings`.
- Controller W5 closure regression verification passed:
  `pytest -q tests/test_file_tools.py tests/test_workspace_connectors.py
  tests/test_file_task_closure.py` -> `42 passed, 1 skipped, 2 warnings`;
  `pytest -q tests/test_api_contracts.py -k connector` -> `1 passed,
  21 deselected, 2 warnings`; live Docker
  `pytest -q tests/test_workspace_connectors.py -m live_docker` -> `1 passed,
  30 deselected, 2 warnings`.
- W5.3 final spec compliance review and final code-quality review passed with
  no Critical/Important findings. The remaining quality Minor was fixed before
  closure so both success and failure acquisition recording are scheduled as
  non-blocking best-effort tasks with bounded timeout and logging.
- Confirmed `git diff --check` passed with CRLF warnings only and
  `git status --short -- frontend` returned no frontend changes during W5
  closure.
- W6.1 implementation added the compose-managed Browser Automation Runtime
  owner/service/client: `backend/app/core/browser_automation/`,
  `browser-runtime/Dockerfile`, `browser-runtime/runtime_service.py`, compose
  wiring, and `backend/tests/test_browser_automation_runtime.py`.
- W6.1 initial spec review failed on incomplete browser egress coverage and
  implicit `allowed_hosts`. Fixes made runtime allowed hosts explicit,
  blocked service workers, added fail-closed WebSocket routing, sanitized
  runtime results, and bound per-action write confirmations.
- W6.1 code-quality review failed on sensitive input trace leakage, unpinned
  runtime URL/proxy trust, inline runtime service maintainability, missing real
  runtime smoke evidence, missing final fatal network check, and disabled
  policy handling. Fixes split `runtime_service.py`, pinned
  `http://browser-runtime:9222`, set `httpx` `trust_env=False`, rejected
  disabled policies, removed sensitive input redaction opt-outs, fixed
  `type` action text handling, added final `guard.raise_if_violations()`,
  and switched to a buildable Playwright image plus pinned Python package.
- Controller final W6.1 verification passed:
  `pytest -q tests/test_browser_automation_runtime.py` -> `20 passed,
  2 warnings`; `docker-compose ... build browser-runtime` succeeded;
  real compose runtime `/health` returned ok; real `/run` to
  `https://example.com` returned HTTP 200 with `Example Domain`; real `/run`
  to `https://www.iana.org` with allowlist `example.com` returned HTTP 400
  `host is not allowlisted`.
- W6.1 final spec compliance review and targeted code-quality re-review passed
  with no Critical/Important findings. All W6.1 subagents/reviewers were
  closed after completion.
- Confirmed `git diff --check` had no whitespace errors, only CRLF warnings.
  Confirmed `git status --short -- frontend` returned no frontend changes
  during W6.1 closure.
- W6.2 implementation registered Browser Automation as a real activation
  target: activation hooks materialize durable
  `BrowserAutomationConfiguration` records, active verified browser tools are
  exposed in Agent/tool APIs, tool-router execution dispatches `browser__*`
  tools, manifest evidence is versioned, rollback hides/disables target
  manifest refs, and confirmation resume passes through the same acquisition
  runtime policy gate.
- W6.2 spec review initially found Important gaps in acquisition egress
  authority and live compose-runtime proof. Fixes bound browser activation
  hosts to `permission_bundle.egress_policy.allow_hosts`, preflight every
  explicit browser action URL through acquisition egress policy with DNS
  evidence, made `backend-test` depend on the compose `browser-runtime`
  healthcheck, and added a live activated browser target runtime test.
- W6.2 code-quality review found Important gaps in public browser argument
  leakage and confirmation replay of redacted values. Fixes separated public
  redacted args from backend persisted executable args, stripped internal
  `__*` fields before SSE, redacted browser `value/text`, URL query/fragment,
  and URL userinfo, and added regressions proving public redaction plus
  original-arg replay on approval.
- W6.2 final targeted spec and code-quality re-reviews passed with no
  Critical/Important findings. All W6.2 subagents/reviewers were closed after
  completion.
- Controller final W6.2 verification passed:
  `pytest -q tests/test_browser_automation_runtime.py tests/test_acquisition_policy.py`
  -> `100 passed, 2 warnings`; the Docker output showed
  `chainless-browser-runtime-test` running and healthy.
- Controller W6.2 API/SSE regression verification passed:
  `pytest -q tests/test_api_contracts.py
  tests/test_file_upload_security.py::test_available_tools_endpoint_is_user_readable_for_chat_picker
  tests/test_sse_contract.py` -> `42 passed, 2 warnings`.
- Confirmed `git diff --check` had no whitespace errors, only CRLF warnings.
  Confirmed `git status --short -- frontend` returned no frontend changes
  during W6.2 closure.

Active slice:
- Workstream 7 complete; ready for Workstream 8 after user approval.

Next step:
- Enter Workstream 8 only after user approval or next instruction.

Blocked-on:
- None.

## ResumeStateHint

Resume by reading:
- `docs/aegis/work/2026-06-22-v3-capability-acquisition-layer/10-intent.md`
- this checkpoint
- V3 spec and execution plan
- latest `git status --short`

Do not resume from memory alone.

## DriftCheckDraft

Current decision: continue.

Scope alignment:
- Inside V3 execution plan.
- W6 is now authorized by the user after W5 closure.

Compatibility boundary:
- No frontend style edits.
- No commits.
- Docker-based verification only.

Retirement track:
- No old runtime path retired in W1; W1 only adds persistence/contracts.
- W2.1 did not wire lifecycle into routes or agent runtime; direct runtime
  writes retire only in later facade/integration workstreams.
- W2.2 did not activate runtime targets directly; it added verification,
  approval binding, and activation-start guards only.
- W2.3 implemented activation saga/rollback orchestration without wiring real
  target-specific runtime owners beyond typed hook seams. Runtime target owners
  and manifest version bumps remain later workstreams.
- W2.4 must render a bounded user-private journal from durable records without
  making the generated markdown an editable source of truth.
- W2.4 completed this journal boundary. W3 now begins credential ownership and
  policy foundations; LLM provider and channel credentials must not be re-owned.
- W4.1 completed the isolated stdio MCP runtime boundary. Backend-process
  stdio launch is retired; direct remote HTTP/SSE MCP is intentionally
  fail-closed until a future safe remote transport owner provides connected-peer
  evidence and streaming response-cap enforcement.
- W4.2 completed the generic API runtime boundary. Builtin tools remain
  available, while acquired API tools only enter runtime registry after
  activation, policy, and user-scope checks.
- W4.3 completed the self-modification safety boundary. Development patch
  proposals are durable review handoffs only; no runtime path applies patches,
  edits repo files, stages, commits, pushes, deploys, or mutates production.
- W4.4 completed the V2 capability target boundary. Acquisition owns
  verification/approval/snapshot/audit/rollback state; Worker, Skill, and
  Memory persistence/runtime effects remain in their V2 owners. Candidate
  metadata remains inert and is not used as V3 activation state.
- W5.1 completed the Workspace Connector ownership boundary. Acquisition
  stores internal hashes and encrypted host path source only for trusted mount
  orchestration; public contracts, agent context, sandbox payloads, and audit
  records remain sanitized.
- W5.2 completed the connector runtime propagation boundary. Production chat
  and confirmation routes build server-side connector context, file tools and
  code-as-action receive sanitized mount bundles, approved sources are
  materialized into the shared workspace volume for sandbox visibility, and
  materialized runtime connectors are snapshot-only/read-only until a future
  sync-back owner is explicitly designed.
- W5.3 completed the code-as-action acquisition evidence boundary. The engine
  emits bounded evidence through the acquisition facade/bridge seam, while
  acquisition lifecycle remains the durable owner for gaps, explorations, and
  recommendations. Runtime recording is best-effort and cannot block user task
  completion.

Evidence state:
- W1 accepted for next phase by Docker verification plus final spec/code-quality
  review.
- W2.1 accepted for W2.2 by Docker verification plus final spec/code-quality
  review.
- W2.2 accepted for W2.3 by Docker verification plus final spec/code-quality
  review.
- W2.3 accepted for W2.4 by Docker verification plus final spec/code-quality
  review.
- W2.4 accepted for W3 by Docker verification plus final spec/code-quality
  review.
- W3.1 accepted for W3.2 by Docker verification plus final spec/code-quality
  review.
- W3.2 accepted for W3.3 by Docker verification plus final spec/code-quality
  review.
- W3.3 accepted for W3 closure by Docker verification plus final
  spec/code-quality review.
- W3 accepted for W4 by W3 closure Docker verification and drift check.
- W4.1 accepted for W4.2 by Docker verification plus final
  spec/code-quality review. Residual risk: same-key durable MCP
  register/unregister serialization is process-local; multi-replica deployments
  will need a future DB advisory lock or version guard.
- W4.2 accepted for W4.3 by Docker verification plus final
  spec/code-quality review.
- W4.3 accepted for W4.4 by Docker verification plus final
  spec/code-quality review.
- W4.4 accepted for W4 closure by Docker verification plus final
  spec/code-quality review.
- W4 accepted for W5 by W4 runtime-target regression verification and drift
  check.
- W5.1 accepted for W5.2 by Docker verification plus final spec/code-quality
  review. Residual risk: W5.2 must still wire connector bundles into file tools
  and code-as-action; W5.1 only establishes the owner and mount contract.
- W5.2 accepted for W5.3 by Docker verification plus final spec/code-quality
  review. Residual risk: W5.3 must still record code-as-action exploration
  evidence into acquisition outcomes; W5.2 only makes connector-backed runtime
  access real and sanitized.
- W5.3 accepted for W5 closure by Docker verification plus final
  spec/code-quality review. The initial spec review failure on nonzero sandbox
  exit classification was fixed and re-reviewed. The quality review failures
  on inline recording, POSIX host-path redaction, and uncapped engine evidence
  capture were fixed and re-reviewed. A later Minor on failure-path blocking
  was fixed before closure.
- W5 accepted for next phase by W5.1, W5.2, and W5.3 Docker verification,
  final review loops, live Docker connector verification, and drift check.
- W6.1 accepted for W6.2 by Docker verification, real compose runtime smoke,
  final spec review, and final code-quality review. Residual risk: browser
  egress allowlisting is enforced at runtime/Playwright policy plus Docker
  service isolation; kernel/firewall per-domain egress remains defense-in-depth
  and is not required by W6.1.
- W6 accepted for W7 by W6.1 and W6.2 Docker verification, live compose
  Browser Runtime execution, final spec/code-quality review loops, API/SSE
  regression coverage, frontend no-change check, and drift check. Residual
  risk: `__persisted_args` intentionally carries backend-only raw replay args
  internally; current SSE paths strip double-underscore fields, and future
  direct serializers must preserve that boundary.
- W7 implementation added the runtime acquisition facade/outbox seam,
  RuntimePlanningIssue owner, acquired tool manifest enforcement, ARQ
  acquisition analysis task registration, runtime Worker acquisition policy
  checks, disabled-mode behavior, and observability metrics.
- W7 review found and fixed two production boundary issues before closure:
  durable candidate/acquisition outbox enqueue originally happened after SSE
  `done`, which could be skipped by clients closing immediately after `done`;
  API acquired confirmation public args also leaked backend-only
  `__acquired_tool_manifest_version`. Both were fixed with regressions.
- W7 accepted for next phase by Docker verification plus final read-only
  re-review. Evidence included targeted sensitive/manifest tests, W7 runtime
  and plan-command regressions, candidate outbox regressions, migration
  roundtrip, `git diff --check`, and frontend no-change check. Residual risk:
  the legacy admin MCP test route still directly calls the MCP manager for
  administrative smoke testing; this is outside the acquired Agent runtime and
  confirmation path reviewed for W7.
- W8 implementation added the public acquisition API route surface, dedicated
  frontend acquisition API/store owner, chat right-panel and Settings
  acquisition surfaces, acquisition SSE notice handling, and the
  `capability-acquisition` Windows browser QA suite. UI changes reused existing
  zinc/card/button/settings patterns and did not change global styles or layout
  primitives.
- W8 local Docker drift was resolved without deleting volumes: main DB schema
  had already received parts of 0008-0011 while `alembic_version` lagged. The
  repair made 0009, 0010, and 0011 migrations idempotent for already-existing
  constraints, columns, and indexes, then verified the running backend reached
  Alembic `0016`.
- W8 browser QA initially failed only because the QA script did not recognize
  V3 acquisition empty-state copy. Product UI already rendered explicit empty
  states such as `No capability gaps recorded.` and `No acquisition proposals
  recorded.` The fix centralized empty/disabled text recognition. Final review
  then found two weak QA assertions: acquisition API overview passed if only
  one route worked, and Settings could be misdetected through Capabilities or
  Workers fallback text. Both were tightened before closure, including a final
  step-level guard requiring `settingsSurface.present`.
- W8 accepted for next phase by Docker backend API contract tests, Docker
  frontend lint/build, Docker Node syntax checks for QA scripts, local compose
  health, and real Windows browser QA against `http://localhost`. Residual
  risk: browser QA currently covered empty acquisition data plus runtime controls
  absence; seeded activated-target rollback/control interaction remains a W9
  full-QA/eval candidate if fixture data is added.
