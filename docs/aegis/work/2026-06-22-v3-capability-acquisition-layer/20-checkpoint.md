# V3 Capability Acquisition Layer Checkpoint

## TodoCheckpointDraft

Current todo: Workstream 4 complete; ready for Workstream 5.

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

Active slice:
- Workstream 4 complete.

Next step:
- Enter Workstream 5 when the user asks to proceed.

Blocked-on:
- None at start.

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
