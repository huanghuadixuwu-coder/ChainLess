# V3 Capability Acquisition Layer Evidence

## Evidence Log

- 2026-06-22: Initialized implementation work records.
- 2026-06-22: Confirmed current branch is `codex/v1-spec-completion`.
- 2026-06-22: Confirmed V3 plan/spec are present as untracked files and must be
  used as the current execution authority.
- 2026-06-22: W1 implementer reported code changes in acquisition model,
  migration, exports, schemas, and tests. Docker verification failed because the
  Docker API pipe `npipe:////./pipe/dockerDesktopLinuxEngine` was unavailable.
- 2026-06-22: W1 spec reviewer found 3 compliance gaps and W1 was kept open.
- 2026-06-22: W1 spec-fix subagent reported `git diff --check` exit 0 and
  Docker command `pytest -q tests/test_acquisition_api_contracts.py
  tests/test_acquisition_models.py` -> `16 passed, 2 warnings`.
- 2026-06-22: W1 spec re-review passed with no compliance issues.
- 2026-06-22: Controller reran the same Docker test command locally:
  `16 passed, 2 warnings in 0.63s`.
- 2026-06-22: W1 code quality review found 2 Important issues and W1 was kept
  open.
- 2026-06-22: W1 quality-fix subagent reported Docker command
  `alembic upgrade head && pytest -q tests/test_acquisition_api_contracts.py
  tests/test_acquisition_models.py` -> `22 passed, 2 warnings`.
- 2026-06-22: Controller reran that command locally: `22 passed, 2 warnings in
  0.60s`.
- 2026-06-22: W1 spec re-review found 2 final schema gaps and W1 was kept open.
- 2026-06-22: W1 schema-fix subagent reported Docker command
  `pytest -q tests/test_acquisition_api_contracts.py tests/test_acquisition_models.py`
  -> `25 passed, 2 warnings`.
- 2026-06-22: Controller reran `alembic upgrade head && pytest -q
  tests/test_acquisition_api_contracts.py tests/test_acquisition_models.py` ->
  `25 passed, 2 warnings in 0.57s`.
- 2026-06-22: W1 final spec review passed.
- 2026-06-22: W1 final code quality review found 2 Important issues and W1 was
  kept open.
- 2026-06-22: W1 drift-fix subagent reported Docker command
  `pytest -q tests/test_acquisition_api_contracts.py tests/test_acquisition_models.py`
  -> `27 passed, 2 warnings`.
- 2026-06-22: Controller reran `alembic upgrade head && pytest -q
  tests/test_acquisition_api_contracts.py tests/test_acquisition_models.py` ->
  `27 passed, 2 warnings in 0.59s`.
- 2026-06-22: Final spec review passed.
- 2026-06-22: Final quality review found a Critical migration identifier-length
  defect. Reviewer's `alembic downgrade 0011 && alembic upgrade head` failed
  and left test DB at `0011`.
- 2026-06-22: W1 migration-name fix subagent reported `alembic downgrade 0011
  && alembic upgrade head && pytest -q tests/test_acquisition_models.py
  tests/test_acquisition_api_contracts.py` -> `28 passed, 2 warnings`.
- 2026-06-22: Controller reran the same downgrade/upgrade command locally:
  `28 passed, 2 warnings in 0.55s`, including downgrade and upgrade log lines.
- 2026-06-22: Final closure reviewer found no Critical or Important issues and
  declared W1 ready for W2.
- 2026-06-22: W2.1 implementation subagent reported repository/lifecycle owner
  files and lifecycle tests with initial Docker results `6 passed` and combined
  acquisition tests `34 passed`.
- 2026-06-22: Controller reran W2.1 lifecycle tests locally in Docker:
  `6 passed, 2 warnings`.
- 2026-06-22: W2.1 spec review found 4 issues: missing explicit transition
  validation, premature activation behavior, fragile JSON idempotency, and
  default dedupe prefixing by runtime owner.
- 2026-06-22: W2.1 spec-fix subagent added transition validation, blocked W2.1
  activation, repaired JSON metadata preservation and default dedupe, and
  reported lifecycle `12 passed` plus combined acquisition `40 passed`.
- 2026-06-22: Controller reran combined acquisition tests: `40 passed,
  2 warnings`.
- 2026-06-22: W2.1 spec re-review found 2 remaining issues: proposal state
  machine allowed `drafted -> verifying/verified`, and exploration idempotency
  remained scoped to changed `source_run_id`.
- 2026-06-22: W2.1 second spec-fix subagent tightened proposal transitions and
  exploration idempotency, reporting lifecycle `14 passed` and combined
  acquisition `42 passed`.
- 2026-06-22: Controller reran migration/combined acquisition verification:
  `42 passed, 2 warnings`.
- 2026-06-22: Final W2.1 spec review passed with evidence for mandatory
  proposal verification order, exploration idempotency by gap/key, and W2.1
  activation rejection.
- 2026-06-22: W2.1 code-quality review found 1 Critical parent-scope validation
  issue and 5 Important issues: JSON-only idempotency authority, audit helper
  committing caller transactions, proposal-kind-unaware transitions, raw UUID
  approval acceptance, and duplicate occurrence evidence loss.
- 2026-06-22: W2.1 quality-fix subagent added durable
  `acquisition_idempotency_records`, non-committing `add_audit_log`, parent
  scope validation, proposal-kind transition maps, confirmation ownership
  validation, and source-evidence merging. It reported migration/combined
  acquisition `50 passed` and audit/lifecycle `28 passed`.
- 2026-06-22: Controller reran migration roundtrip plus acquisition tests:
  `50 passed, 2 warnings`.
- 2026-06-22: Controller reran audit compatibility plus lifecycle tests:
  `28 passed, 2 warnings`.
- 2026-06-22: W2.1 code-quality re-review found one remaining Important issue:
  same-key concurrent create idempotency could still double-create before the
  idempotency row was recorded.
- 2026-06-22: Final W2.1 idempotency-fix subagent added pre-domain-row
  idempotency reservation, `FOR UPDATE` locking, request fingerprint conflict
  detection, and same-key concurrent create tests for exploration,
  recommendation, and proposal. It reported migration/combined acquisition
  `54 passed` and audit/lifecycle `32 passed`.
- 2026-06-22: Controller reran final migration roundtrip plus acquisition
  tests: `54 passed, 2 warnings`.
- 2026-06-22: Controller reran final audit compatibility plus lifecycle tests:
  `32 passed, 2 warnings`.
- 2026-06-22: Final W2.1 code-quality re-review found no Critical or Important
  issues and declared the prior same-key concurrent idempotency race cleared.
- 2026-06-22: Confirmed `git status --short -- frontend` returned no frontend
  changes during W2.1.
- 2026-06-22: W2.2 implementation subagent added activation snapshot,
  verification, and activation guard owners plus `tests/test_acquisition_snapshot.py`.
  Initial controller verification passed: `pytest -q
  tests/test_acquisition_snapshot.py` -> `7 passed, 2 warnings`; migration
  roundtrip plus acquisition tests -> `61 passed, 2 warnings`; audit/lifecycle
  plus snapshot tests -> `39 passed, 2 warnings`.
- 2026-06-22: W2.2 spec review found Critical gaps in over-redacted credential
  snapshot fields and unguarded repository transitions into activation states,
  plus Important transition gaps around `activating -> activated` and runtime
  `verified -> handoff_ready`.
- 2026-06-22: W2.2 spec-fix subagent preserved credential refs/generations in
  snapshots, blocked unguarded `activation_approved` / `activating` /
  `activated` transitions, added the guarded `activating -> activated` edge,
  and removed runtime `verified -> handoff_ready`. Controller verification
  passed: snapshot `12 passed`, migration/acquisition `66 passed`, and
  audit/lifecycle/snapshot `44 passed`.
- 2026-06-22: W2.2 spec re-review passed with no Critical or Important issues.
- 2026-06-22: W2.2 code-quality review found Important issues in completed
  verification mutability, approval/start idempotent replay, and approval
  binding without re-hashing selected verification evidence.
- 2026-06-22: W2.2 quality-fix subagent made completed verification immutable
  except exact replay, added idempotent approval/start replay handling, locked
  and re-hashed verification evidence at approval, and updated the W2.3
  activation diagnostic. Controller verification passed: snapshot `19 passed`,
  migration/acquisition `73 passed`, and audit/lifecycle/snapshot `51 passed`.
- 2026-06-22: W2.2 code-quality re-review found two remaining Important issues:
  approval could bind a stale current snapshot after verification-time drift,
  and replay matching ignored approval reason / activation verification_id /
  target_ids.
- 2026-06-22: Final W2.2 quality-fix subagent added approval-time current
  snapshot recomputation before `activation_approved`, complete
  request-equivalence metadata for approval/start replay, and tests for reason,
  verification_id, and ordered target_ids mismatch. Controller verification
  passed: snapshot `24 passed`, migration/acquisition `78 passed`, and
  audit/lifecycle/snapshot `56 passed`.
- 2026-06-22: Final W2.2 code-quality re-review found no Critical or Important
  issues. The reviewer also ran a local Docker snapshot suite and observed
  `24 passed, 2 warnings`.
- 2026-06-22: W2.3 implementation added activation saga orchestration,
  rollback owner, no-side-effect activation/rollback hooks, manifest hiding,
  permission revocation, journal/audit updates, and rollback recovery state.
  Controller verification passed: lifecycle/policy/tool-manifest `34 passed`
  and migration/acquisition `87 passed`.
- 2026-06-22: W2.3 spec review passed with no Critical or Important issues.
  Reviewer noted manifest version bumping remains later-scope and W2.3 only
  owns invalidation/hide semantics.
- 2026-06-22: W2.3 code-quality review found one Important issue in
  secondary-only `target_ids` activation. Quality-fix pass added the primary
  target guard and all-targets-active activation check.
- 2026-06-22: W2.3 code-quality re-review found no Critical or Important
  issues and confirmed the prior Important issue closed. A remaining Minor
  defensive assertion was added to prove rejected secondary-only activation does
  not persist side effects.
- 2026-06-22: Controller reran W2.3 focused verification:
  `pytest -q
  tests/test_acquisition_lifecycle.py::test_secondary_only_target_ids_require_primary_before_proposal_activated
  tests/test_acquisition_lifecycle.py tests/test_acquisition_policy.py
  tests/test_tool_manifest.py` -> `36 passed, 2 warnings`.
- 2026-06-22: Controller reran W2.3 final migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py` -> `88 passed,
  2 warnings`.
- 2026-06-22: W2.4 implementation added `journal.py`, `read_model.py`, and
  `test_acquisition_journal.py`. Initial controller verification passed:
  `pytest -q tests/test_acquisition_journal.py` -> `5 passed, 2 warnings`;
  acquisition regression -> `89 passed, 2 warnings`.
- 2026-06-22: W2.4 spec review found Important gaps in scalar redaction and
  Runtime Planning Issue link canonicality. Fixes applied `_safe_text`
  rendering, broadened path redaction, and switched links/source refs to
  `/api/v1/acquisition/runtime-planning-issues`.
- 2026-06-22: W2.4 spec re-review passed with no Critical, Important, or Minor
  issues.
- 2026-06-22: W2.4 code-quality review found Important risks in concurrent
  first-time snapshot writes and aggregate markdown size. Fixes added
  `uq_acq_journal_snapshot_user`, PostgreSQL upsert, per-item JSON
  preview/hash truncation, final persisted snapshot byte budgeting, and tests
  for concurrency and large aggregate evidence.
- 2026-06-22: W2.4 final code-quality re-review found no Critical, Important,
  or Minor issues and confirmed both Important findings closed.
- 2026-06-22: Controller reran W2.4 focused verification:
  `pytest -q tests/test_acquisition_journal.py` -> `7 passed, 2 warnings`.
- 2026-06-22: Controller reran W2.4 final migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `95 passed, 2 warnings`.
- 2026-06-22: W3.1 implementation added `core/credentials` with encrypted
  CredentialConnection create/rotate/revoke/resolve, redacted response
  serialization, dependent snapshot invalidation, and dependent target/config
  disabling. Controller focused verification passed:
  `pytest -q tests/test_acquisition_policy.py` -> `6 passed, 2 warnings`;
  combined snapshot/policy verification passed: `32 passed, 2 warnings`;
  migration/acquisition verification passed: `101 passed, 2 warnings`.
- 2026-06-22: W3.1 spec review found Critical gaps in revoked/rotated
  credentials invalidating `activating` proposals, fresh verification accepting
  revoked refs, runtime-path revocation coverage, and dependent target/config
  disabling. Fixes expanded invalidation states, rejected non-active refs during
  fresh verification, tested `start_activation` / revoke / `run_activation_saga`,
  and disabled dependent ActivationTarget/API/MCP/Browser/Workspace surfaces.
  Controller verification passed: focused `33 passed, 2 warnings`; broad
  migration/acquisition `102 passed, 2 warnings`.
- 2026-06-22: W3.1 spec re-review passed with no Critical or Important gaps.
- 2026-06-22: W3.1 code-quality review found Important gaps in malformed
  `credential_connection_refs` bubbling raw errors and direct durable config
  refs not being disabled if proposal bundles were stale. Fixes added canonical
  malformed-ref errors and direct config disabling. Controller verification
  passed: focused `35 passed, 2 warnings`; broad migration/acquisition
  `104 passed, 2 warnings`.
- 2026-06-22: W3.1 code-quality re-review found one remaining Important issue:
  non-list truthy credential refs such as `123` could still raise raw
  `TypeError` during snapshot helper extraction.
- 2026-06-22: Final W3.1 fix normalized scalar/non-iterable credential refs so
  verification returns canonical `409 CREDENTIAL_REFERENCE_NOT_FOUND`, and
  added a regression for `credential_connection_refs = 123`. Controller focused
  verification passed: `pytest -q tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py` -> `36 passed, 2 warnings`.
- 2026-06-22: Controller reran final W3.1 migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `105 passed, 2 warnings`.
- 2026-06-22: Final W3.1 code-quality re-review found no Critical or Important
  findings. Residual risk: direct no-bundle config coverage is explicit for
  revoke; rotate relies on the same shared invalidation helper.
- 2026-06-22: W3.2 implementation added `backend/app/core/security/egress_policy.py`
  and egress tests covering declared public hosts, private IPs, DNS rebinding,
  forbidden redirects, metadata endpoint denial, oversized response contracts,
  and activated `arbitrary_network` denial. Controller focused verification
  passed: `pytest -q tests/test_acquisition_policy.py` -> `14 passed,
  2 warnings`.
- 2026-06-22: W3.2 spec review passed with no Critical or Important gaps. The
  reviewer reran the focused policy tests and observed `14 passed, 2 warnings`.
- 2026-06-22: W3.2 code-quality review found Important issues in uncapped
  activated runtime responses, advisory DNS/connect sequencing, and incomplete
  non-canonical numeric IPv4 rejection. Fixes added mandatory runtime response
  caps, streaming response chunk validation, runtime DNS/connect guard helpers,
  invalid-port handling, and legacy numeric IPv4 rejection. Controller focused
  verification passed: `22 passed, 2 warnings`; migration/acquisition
  regression passed: `120 passed, 2 warnings`.
- 2026-06-22: W3.2 re-review found one remaining Important numeric IPv4 gap for
  forms such as `127.1`, `127.0.1`, `0x7f000001`, and octal-ish short forms.
  Fixes broadened legacy numeric IPv4 detection and added regressions.
  Controller focused verification passed: `26 passed, 2 warnings`;
  migration/acquisition regression passed: `124 passed, 2 warnings`.
- 2026-06-22: W3.2 final code-quality re-review found no Critical or Important
  issues. A Minor malformed `validated_resolved_ips` issue was fixed afterward
  with a regression returning `INVALID_DNS_RESOLUTION` instead of raw
  `ValueError`.
- 2026-06-22: Controller reran final W3.2 focused verification:
  `pytest -q tests/test_acquisition_policy.py` -> `27 passed, 2 warnings`.
- 2026-06-22: Controller reran final W3.2 migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `125 passed, 2 warnings`.
- 2026-06-22: W3.3 implementation added `backend/app/core/acquisition/policy.py`
  with structured permission decisions, permission bundle validation, standing
  permission lookup, expiration/revocation checks, boundary reapproval,
  confirmation-context validation, egress-policy layering, and target-policy
  narrowing. Controller focused verification passed:
  `pytest -q tests/test_acquisition_policy.py` -> `33 passed, 2 warnings`;
  migration/acquisition regression passed: `131 passed, 2 warnings`.
- 2026-06-22: W3.3 spec review found Important gaps in standing permission
  boundary completeness, target permission bundle inheritance from proposal, and
  free-form action-category bypass. Fixes added boundary snapshots, removed
  inheritance in activation target materialization, expanded action aliases, and
  required confirmation from effective action categories. Controller targeted
  verification passed: `83 passed, 2 warnings`; migration/acquisition regression
  passed: `150 passed, 2 warnings`.
- 2026-06-22: W3.3 spec re-review found one remaining Important bypass where a
  dangerous bundle action could be hidden by request `action_category="read"`.
  Fixes made confirmation context bind the effective request/bundle action and
  added residual boundary tests. Controller focused verification passed:
  `60 passed, 2 warnings`; migration/acquisition regression passed:
  `159 passed, 2 warnings`.
- 2026-06-22: W3.3 final spec re-review passed with no Critical or Important
  gaps.
- 2026-06-22: W3.3 code-quality review found Important issues in risk-level
  vocabulary, unknown action category fail-open behavior, and ISO `expires_at`
  persistence, plus a Minor list-of-dicts subset issue. Fixes aligned
  `RISK_ORDER` to `safe/risky/high_risk/blocked`, made unknown actions require
  confirmation, normalized `expires_at` before StandingPermission persistence,
  and canonicalized list comparisons.
- 2026-06-22: Controller reran final W3.3 targeted verification:
  `pytest -q tests/test_acquisition_policy.py tests/test_acquisition_lifecycle.py`
  -> `98 passed, 2 warnings`.
- 2026-06-22: Controller reran final W3.3 migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `165 passed, 2 warnings`.
- 2026-06-22: W3.3 final code-quality re-review found no Critical or Important
  findings.
- 2026-06-22: Controller reran W3 closure focused verification:
  `pytest -q tests/test_acquisition_policy.py tests/test_acquisition_lifecycle.py
  tests/test_acquisition_snapshot.py` -> `127 passed, 2 warnings`.
- 2026-06-22: Controller reran W3 closure migration/acquisition verification:
  `alembic downgrade 0011 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_acquisition_journal.py` -> `165 passed, 2 warnings`.
- 2026-06-22: Confirmed `git status --short -- frontend` returned no frontend
  changes during W3 closure.
- 2026-06-23: W4.1 implementation added a compose-managed isolated MCP stdio
  runtime service, backend `core/tools/mcp_runtime` owner, durable
  `MCPServerConfiguration` registration/recovery, tenant-scoped enabled
  uniqueness migration `0013`, and startup recovery.
- 2026-06-23: W4.1 spec review initially found durable recovery, real runtime
  execution, egress, runtime-side policy, and approved-payload binding gaps.
  Fixes added real `mcp-runtime` HTTP service execution, runtime-side
  approved-payload hashes, explicit fail-closed egress, durable restart
  recovery, and isolated compose boundaries.
- 2026-06-23: W4.1 code-quality review found identity mismatch,
  DB/runtime side-effect ordering, startup recovery isolation, remote HTTP/SSE
  evidence, response-cap materialization, migration duplicate safety, failed
  replacement, and same-key concurrent replacement issues. Fixes made MCP
  identity tenant-scoped, deduped duplicate enabled rows in migration `0013`,
  fail-closed direct remote HTTP/SSE until a safe adapter owner exists,
  serialized same-key operations with process-local locks, and preserved old
  runtime/config on failed replacement.
- 2026-06-23: Controller reran W4.1 targeted verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_mcp_runtime_isolation.py tests/test_mcp_transports.py"` ->
  `33 passed, 2 warnings`.
- 2026-06-23: Controller reran W4.1 affected API contract verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server
  tests/test_api_contracts.py::test_tools_mcp_failures_do_not_leak_exception_details"` ->
  `2 passed, 2 warnings`.
- 2026-06-23: Controller reran W4.1 migration/runtime verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && alembic
  downgrade 0012 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_mcp_runtime_isolation.py
  tests/test_mcp_transports.py"` -> `46 passed, 2 warnings`, including
  `0013 -> 0012 -> 0013/head` roundtrip.
- 2026-06-23: W4.1 final spec compliance review passed with no
  Critical/Important findings.
- 2026-06-23: W4.1 final code-quality review passed with no
  Critical/Important findings. Minor residuals: same-key MCP operation locks
  are process-local, so multi-replica deployments still need a future DB
  advisory lock or version guard; direct remote HTTP/SSE MCP stays fail-closed
  until a safe remote transport owner exists.
- 2026-06-23: Confirmed `git diff --check` had no whitespace errors and
  `git status --short -- frontend` returned no frontend changes during W4.1
  closure.
- 2026-06-23: W4.2 implementation added generic API runtime files under
  `backend/app/core/tools/api_runtime/`, canonical per-user API tool names,
  activation hooks, registry exposure for active user-scoped targets, runtime
  schema validation, credential resolution by reference, egress/content/byte
  bounds, retry/timeout/rate-limit contracts, and confirmation enforcement for
  non-idempotent/external writes.
- 2026-06-23: W4.2 final verification passed:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_tool_runtime.py tests/test_acquisition_policy.py"` ->
  `92 passed, 2 warnings`.
- 2026-06-23: W4.2 enhanced regression verification passed:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_tool_runtime.py tests/test_acquisition_policy.py
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_hook_upserts_enabled_verified_manifest
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_user_scoped_tool_name_collision
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_binds_current_credential_generation
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_credential_not_allowed_for_api_tool
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_credential_target_ref_mismatch
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_unresolvable_credential_storage
  tests/test_acquisition_lifecycle.py::test_api_tool_activation_rejects_unsupported_auth_scheme
  tests/test_sse_contract.py::test_execute_confirmed_api_tool_passes_backend_acquisition_confirmation_context
  tests/test_sse_contract.py::test_disconnected_stream_cancels_running_agent_task"` ->
  `101 passed, 2 warnings`.
- 2026-06-23: W4.2 final code review found no Critical/Important blockers and
  W4.2 was closed.
- 2026-06-23: W4.3 implementation added development patch proposal handoff
  owner `backend/app/core/acquisition/development_patch.py` and bridge exports.
  Runtime activation is denied; patch handoff requires artifact refs, digest
  binding, current revision check, dry-apply validation, rollback/test-plan
  evidence, and audit.
- 2026-06-23: W4.3 initial review found Important digest, local-path,
  dry-apply, and audit blockers. Fixes bound actual artifact content to
  `sha256:` digest, rejected local/file patch refs, added pure-Python
  unified-diff dry-apply, and wrote `acquisition.development_patch.handoff_ready`
  audit.
- 2026-06-23: Controller reran W4.3 focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_development_patch_proposal.py"` -> `11 passed, 2 warnings`.
- 2026-06-23: Controller reran W4.3 regression verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_development_patch_proposal.py
  tests/test_acquisition_models.py::test_development_patch_proposal_cannot_be_runtime_active
  tests/test_acquisition_lifecycle.py::test_development_patch_proposal_rejects_runtime_only_states_with_lifecycle_error
  tests/test_acquisition_journal.py::test_journal_groups_open_gaps_proposals_activated_rejected_runtime_issues_and_patch_proposals"` ->
  `14 passed, 2 warnings`.
- 2026-06-23: W4.3 final code review found no Critical/Important blockers and
  W4.3 was closed.
- 2026-06-23: W4.4 implementation added V2 target adapter
  `backend/app/core/acquisition/v2_targets.py`, verification prechecks for
  Worker/Skill/Memory target payloads, default activation dispatch for V2
  targets, production rollback dispatch for V2 compensation, Worker
  acquisition activation/rollback owner entrypoints, Skill acquisition
  activation/disable owner entrypoints, Memory acquisition delete rollback, and
  `backend/tests/test_v2_activation_targets.py`.
- 2026-06-23: W4.4 initial review found Important blockers in Worker update
  rollback, inaccurate V2 side-effect audit/history, partial rollback retry
  idempotency, pending Worker activation-gate restoration, and transaction
  boundaries after target activation IntegrityError. Fixes added Worker restore
  snapshots, runtime/durable side-effect evidence, already-rolled-back skip,
  shallow manifest evidence, pending activation-field restoration, and nested
  savepoints for V2 activation/compensation.
- 2026-06-23: Controller reran W4.4 focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_v2_activation_targets.py"` -> `13 passed, 2 warnings`.
- 2026-06-23: Controller reran W4.4 plan verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_v2_activation_targets.py tests/test_capability_candidates.py
  tests/test_worker_runtime.py"` -> `65 passed, 2 warnings`.
- 2026-06-23: Controller reran W4 runtime regression verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_v2_activation_targets.py tests/test_acquisition_lifecycle.py
  tests/test_development_patch_proposal.py tests/test_api_tool_runtime.py
  tests/test_mcp_transports.py tests/test_mcp_runtime_isolation.py"` ->
  `120 passed, 2 warnings`.
- 2026-06-23: W4.4 final spec review passed with no Critical/Important
  findings.
- 2026-06-23: W4.4 final code-quality review passed with no
  Critical/Important findings. Minor residual: Memory raw-secret detection is
  conservative and may reject benign fields with names such as `token`.
- 2026-06-23: Confirmed `git diff --check` on W4.4 touched files had no
  whitespace errors, only CRLF warnings. Confirmed `git status --short --
  frontend` returned no frontend changes during W4.4 closure.
- 2026-06-23: W4 subagents used for spec/code-quality review were closed after
  completion.
- 2026-06-23: W5.1 implementation added Workspace Connector owner files
  `backend/app/core/workspace_connectors/service.py`,
  `backend/app/core/workspace_connectors/mounts.py`, and tests, plus
  `sandbox-proxy/main.py` mount-bundle validation.
- 2026-06-23: W5.1 spec review initially failed on non-authoritative approval
  validation and missing trusted source-of-truth for real host paths. Fixes
  added tenant/user-owned approved `ToolConfirmation` validation and encrypted
  `host_path_secret_ref` via migration `0015_workspace_connector_host_path_secret.py`.
- 2026-06-23: W5.1 spec review later failed because public
  `WorkspaceConnectorContract` exposed `host_realpath_hash`. Fix removed the
  hash from the public contract and added a contract test rejecting the field.
- 2026-06-23: W5.1 code-quality review found approval replay, unsafe
  `allowlist_rule`, trusted-source race, and loose sandbox mount schema
  blockers. Fixes bound approval to action/purpose/mode/host identity and
  one-time use, sanitized allowlist metadata, converted trusted source races to
  `WorkspaceConnectorMountError`, and tightened sandbox schema/path checks.
- 2026-06-23: W5.1 final quality review initially caught a stale ORM
  identity-map risk in trusted-source lookup. Fix added
  `.with_for_update().execution_options(populate_existing=True)` and
  external-session disable regression coverage.
- 2026-06-23: Controller reran W5.1 targeted verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_workspace_connectors.py tests/test_acquisition_api_contracts.py"` ->
  `31 passed, 2 warnings`.
- 2026-06-23: Controller reran W5.1 migration/API/model verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && alembic
  downgrade 0014 && alembic upgrade head && pytest -q
  tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_workspace_connectors.py"` -> `44 passed, 2 warnings`.
- 2026-06-23: W5.1 final spec compliance review and final code-quality review
  passed with no Critical/Important findings. All W5.1 subagents/reviewers
  were closed after completion.
- 2026-06-23: Confirmed `git status --short -- frontend` returned no output
  during W5.1 closure.
- 2026-06-23: W5.2 implementation made file tools, production chat routes,
  confirmation resume, sandbox-proxy, and code-as-action connector-aware.
  Review loops fixed missing plan test coverage, skipped live Docker closure,
  route-level connector context, untrusted args-carried connector context,
  approved-source materialization, hot-path query/lock pressure, and
  `read_write` snapshot semantics.
- 2026-06-23: Controller reran W5.2 focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_file_tools.py tests/test_workspace_connectors.py
  tests/test_file_task_closure.py"` -> `42 passed, 1 skipped, 2 warnings`.
- 2026-06-23: Controller reran W5.2 route-context verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_contracts.py -k connector"` -> `1 passed, 21 deselected,
  2 warnings`.
- 2026-06-23: Controller reran W5.2 live Docker verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile
  live-docker run --rm -e PYTHONPATH=/repo/backend backend-test-live sh -lc
  "cd /repo/backend && pytest -q tests/test_workspace_connectors.py -m
  live_docker"` -> `1 passed, 30 deselected, 2 warnings`. The live test now
  proves approved-source materialization into `/workspace/connectors/<id>`
  before sandbox/code-as-action reads.
- 2026-06-23: W5.2 final spec compliance review passed with no
  Critical/Important findings after production routes built server-side
  connector context and embedded `__workspace_connector_context` was ignored.
- 2026-06-23: W5.2 final code-quality review passed with no
  Critical/Important findings after runtime materialized connectors were made
  snapshot-only/read-only and live materialization replaced target
  pre-population.
- 2026-06-23: Confirmed `git diff --check` had no whitespace errors, only CRLF
  warnings. Confirmed `git status --short -- frontend` returned no frontend
  changes during W5.2 closure.
- 2026-06-23: W5.3 implementation added runtime acquisition evidence capture
  for code-as-action through `backend/app/core/acquisition/facade.py` and the
  bridge seam. Evidence stores script digest, bounded stdout/stderr excerpts,
  sandbox event summaries, tool call metadata, risk classification, connector
  summaries, and redacted paths; raw scripts are not durable keys.
- 2026-06-23: W5.3 initial spec review failed on live sandbox nonzero exit
  classification: `execute_disposable_parent` returns HTTP 200 with
  `exit_code`, so failed Python scripts could be recorded as successful
  exploration evidence. Fix added nonzero-exit detection after stdout/stderr
  streaming and before completion, causing the engine to record failed
  acquisition gap/exploration evidence.
- 2026-06-23: W5.3 code-quality review failed on inline acquisition recording,
  POSIX host-path leakage, and engine-side full-output accumulation before
  truncation. Fixes made success/failure recording non-blocking best-effort
  tasks with timeout/logging, added capped engine-side evidence buffers, and
  expanded redaction for Windows, POSIX, workspace, and connector paths.
- 2026-06-23: Controller reran W5.3 focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_acquisition_agent_integration.py"` -> `9 passed, 2 warnings`.
- 2026-06-23: W5.3 final spec compliance review passed with no
  Critical/Important findings after nonzero-exit coverage was added.
- 2026-06-23: W5.3 final code-quality review passed with no
  Critical/Important findings after slow-recorder success/failure coverage,
  bounded evidence capture, and POSIX path redaction were added.
- 2026-06-23: Controller reran W5 closure regression verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_file_tools.py tests/test_workspace_connectors.py
  tests/test_file_task_closure.py"` -> `42 passed, 1 skipped, 2 warnings`.
- 2026-06-23: Controller reran W5 route-context regression verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_contracts.py -k connector"` -> `1 passed, 21 deselected,
  2 warnings`.
- 2026-06-23: Controller reran W5 live Docker connector verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile
  live-docker run --rm -e PYTHONPATH=/repo/backend backend-test-live sh -lc
  "cd /repo/backend && pytest -q tests/test_workspace_connectors.py -m
  live_docker"` -> `1 passed, 30 deselected, 2 warnings`.
- 2026-06-23: Confirmed `git diff --check` had no whitespace errors, only CRLF
  warnings. Confirmed `git status --short -- frontend` returned no frontend
  changes during W5 closure.
- 2026-06-23: W6.1 implementation added Browser Automation Runtime owner files
  under `backend/app/core/browser_automation/`, the compose-managed
  `browser-runtime` image/service, runtime policy/trace/client owners, and
  `backend/tests/test_browser_automation_runtime.py`.
- 2026-06-23: W6.1 spec review initially failed on runtime egress gaps
  (service worker/WebSocket bypass risk) and implicit `allowed_hosts`. Fixes
  added explicit runtime `allowed_hosts`, service worker blocking,
  fail-closed WebSocket routing, per-action write confirmation, runtime
  deadline payloads, and sanitized runtime results.
- 2026-06-23: W6.1 code-quality review found Important issues in sensitive
  input traces, runtime URL/proxy trust, Dockerfile inline service
  maintainability, missing real runtime smoke evidence, missing final fatal
  network check, and disabled policy handling. Fixes split
  `browser-runtime/runtime_service.py`, pinned internal runtime URL validation,
  set `httpx.AsyncClient(trust_env=False)`, rejected disabled policies,
  redacted `fill/type` `value/text` without opt-out, handled `type.text`, and
  added final `guard.raise_if_violations()`.
- 2026-06-23: Controller reran W6.1 focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_browser_automation_runtime.py"` -> `20 passed, 2 warnings`.
- 2026-06-23: Controller built the real browser runtime image:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml build
  browser-runtime` -> succeeded with `chainless-browser-runtime:w6-1`.
- 2026-06-23: Controller verified real compose browser-runtime behavior:
  `/health` returned `{"ok": true, "runtime_kind": "isolated_browser"}`;
  `route_web_socket` existed in the container; `/run` navigating to
  `https://example.com` with allowlist `example.com` returned HTTP 200 and
  title `Example Domain`; `/run` navigating to `https://www.iana.org` with
  allowlist `example.com` returned HTTP 400 `host is not allowlisted`.
- 2026-06-23: W6.1 final spec compliance review passed with no
  Critical/Important findings and confirmed Docker/firewall per-domain egress
  is not required by written W6.1.
- 2026-06-23: W6.1 final targeted code-quality re-review passed with no
  Critical/Important findings after sensitive input opt-out removal and
  runtime `type.text` handling were verified.
- 2026-06-23: Confirmed `git diff --check` had no whitespace errors, only CRLF
  warnings. Confirmed `git status --short -- frontend` returned no frontend
  changes during W6.1 closure.
- 2026-06-23: W6.2 implementation registered Browser Automation as an
  activation target. New runtime owners added activation materialization,
  active-tool registry exposure, browser tool execution, acquisition policy
  checks, manifest version evidence, rollback hiding, and confirmation replay
  support. Agent/tool APIs now expose active verified `browser__*` tools.
- 2026-06-23: W6.2 spec review initially found Important gaps in acquisition
  egress authority and live compose-runtime proof. Fixes required activation
  `allowed_hosts` to stay within `permission_bundle.egress_policy.allow_hosts`,
  evaluated explicit action URLs through acquisition egress policy with DNS
  evidence before runtime execution, added `browser-runtime` as a
  `backend-test` health dependency, and added a live activated browser runtime
  test.
- 2026-06-23: Controller reran W6.2 focused verification after spec fixes:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_browser_automation_runtime.py tests/test_acquisition_policy.py"`
  -> `97 passed, 2 warnings`; Docker output showed
  `chainless-browser-runtime-test` running and healthy.
- 2026-06-23: W6.2 spec re-review passed with no Critical/Important findings.
  It confirmed acquisition egress checks and live compose runtime proof were
  closed.
- 2026-06-23: W6.2 code-quality review found Important issues in raw browser
  args leaking through public SSE and approved confirmations replaying
  redacted values instead of executable original args. Fixes separated
  backend-only persisted args from public redacted args, stripped internal
  double-underscore fields before SSE, and preserved original executable args
  for approved browser replay.
- 2026-06-23: Targeted quality re-review then found browser URL query/fragment
  and URL userinfo redaction gaps. Fixes made browser public serialization
  strip query/fragment, redact URL userinfo as `[REDACTED]`, and always pass
  browser `__public_args` through the same browser public redactor.
- 2026-06-23: Controller reran browser runtime tests after public/persisted
  argument fixes:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_browser_automation_runtime.py"` -> `31 passed, 2 warnings`.
- 2026-06-23: Controller reran W6.2 final focused verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_browser_automation_runtime.py tests/test_acquisition_policy.py"`
  -> `100 passed, 2 warnings`; Docker output showed
  `chainless-browser-runtime-test` running and healthy.
- 2026-06-23: Controller reran API/SSE regression verification:
  `docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_api_contracts.py
  tests/test_file_upload_security.py::test_available_tools_endpoint_is_user_readable_for_chat_picker
  tests/test_sse_contract.py"` -> `42 passed, 2 warnings`.
- 2026-06-23: W6.2 final targeted code-quality re-review passed with no
  Critical/Important findings. It confirmed prior quality findings were closed:
  public `__public_args` are re-redacted for browser tools, URL userinfo is
  redacted, query/fragment are stripped, and original backend replay args are
  preserved internally.
- 2026-06-23: Confirmed `git diff --check` had no whitespace errors, only CRLF
  warnings. Confirmed `git status --short -- frontend` returned no frontend
  changes during W6.2 closure.

## Workstream 7 Evidence

- 2026-06-24: W7 implementation added acquisition facade/outbox integration,
  RuntimePlanningIssue ownership, per-user acquired tool manifest enforcement,
  acquisition analysis ARQ scheduling, runtime Worker acquisition policy checks,
  disabled-mode behavior, and acquisition observability metrics.
- 2026-06-24: Initial W7 targeted regression verification passed:
  `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm
  backend-test pytest -q
  tests/test_sse_contract.py::test_persisted_confirmation_keeps_raw_args_out_of_message_metadata
  tests/test_sse_contract.py::test_acquired_mcp_confirmation_public_args_are_redacted_but_persisted_args_remain_executable
  tests/test_tool_manifest.py::test_acquired_api_runtime_enforces_manifest_version_on_execution
  tests/test_capability_candidates.py::test_completed_chat_run_persists_inactive_candidate_and_emits_sse_hint
  tests/test_acquisition_observability.py::test_acquisition_analysis_is_registered_on_arq_worker`
  -> `5 passed`.
- 2026-06-24: W7 broad runtime/SSE/policy/tool verification initially passed:
  `tests/test_worker_runtime.py tests/test_sse_contract.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_api_tool_runtime.py
  tests/test_browser_automation_runtime.py::test_activated_browser_target_registers_tool
  tests/test_browser_automation_runtime.py::test_unverified_browser_target_is_not_callable
  tests/test_workspace_connectors.py::test_workspace_connector_runtime_flag_blocks_mount_materialization`
  -> `148 passed`.
- 2026-06-24: W7 acquisition model/API/lifecycle/disabled/observability
  verification passed:
  `tests/test_acquisition_models.py tests/test_acquisition_api_contracts.py
  tests/test_acquisition_lifecycle.py tests/test_acquisition_snapshot.py
  tests/test_acquisition_observability.py tests/test_acquisition_disabled_mode.py
  tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server
  tests/test_api_contracts.py::test_tools_mcp_failures_do_not_leak_exception_details
  tests/test_file_upload_security.py::test_available_tools_endpoint_is_user_readable_for_chat_picker`
  -> `119 passed`.
- 2026-06-24: W7 candidate outbox regression passed:
  `pytest -q tests/test_capability_candidates.py` -> `30 passed`.
- 2026-06-24: W7 planning/workspace/MCP/browser/development-patch regression
  passed:
  `tests/test_planning_issues.py tests/test_workspace_connectors.py
  tests/test_mcp_runtime_isolation.py tests/test_mcp_transports.py
  tests/test_browser_automation_runtime.py
  tests/test_development_patch_proposal.py` -> `111 passed, 1 skipped`.
- 2026-06-24: W7 plan-command verification passed:
  `tests/test_acquisition_agent_integration.py tests/test_acquisition_disabled_mode.py
  tests/test_planning_issues.py tests/test_acquisition_journal.py
  tests/test_acquisition_policy.py tests/test_tool_manifest.py
  tests/test_worker_runtime.py tests/test_acquisition_observability.py`
  -> `138 passed`.
- 2026-06-24: W7 migration roundtrip passed:
  `alembic downgrade 0015 && alembic upgrade head`.
- 2026-06-24: W7 spec review found durable outbox enqueue happened after SSE
  `done`, risking skipped analysis if clients closed immediately after `done`.
  Fix moved durable candidate/acquisition enqueue before `done` and added
  `test_done_is_sent_after_durable_analysis_enqueue`.
- 2026-06-24: After the after-`done` fix, targeted verification passed:
  `tests/test_sse_contract.py::test_done_is_sent_after_durable_analysis_enqueue
  tests/test_sse_contract.py::test_stream_disconnect_does_not_drop_durable_acquisition_analysis
  tests/test_sse_contract.py::test_persisted_confirmation_keeps_raw_args_out_of_message_metadata
  tests/test_tool_manifest.py::test_acquired_api_runtime_enforces_manifest_version_on_execution
  tests/test_capability_candidates.py::test_completed_chat_run_persists_inactive_candidate_and_emits_sse_hint`
  -> `5 passed`; broad runtime/SSE/policy/tool verification updated to
  `149 passed`; W7 plan-command verification remained `138 passed`.
- 2026-06-24: W7 re-review found an Important public-boundary leak:
  API acquired confirmation public args could include backend-only
  `__acquired_tool_manifest_version`. Fix stripped that key in
  `_public_confirmation_args` while retaining it in persisted backend replay
  args.
- 2026-06-24: After the public-boundary fix, targeted verification passed:
  `tests/test_sse_contract.py::test_acquired_api_confirmation_hides_manifest_version_from_public_args
  tests/test_sse_contract.py::test_persisted_confirmation_keeps_raw_args_out_of_message_metadata
  tests/test_sse_contract.py::test_acquired_mcp_confirmation_public_args_are_redacted_but_persisted_args_remain_executable
  tests/test_tool_manifest.py::test_acquired_api_runtime_enforces_manifest_version_on_execution`
  -> `4 passed`.
- 2026-06-24: Final W7 verification passed after all fixes:
  broad runtime/SSE/policy/tool group -> `150 passed`; W7 plan-command group
  -> `138 passed`; candidate outbox group -> `30 passed`; migration
  `downgrade 0015 && upgrade head` passed; `git diff --check` returned no
  whitespace errors beyond CRLF warnings; `git status --short -- frontend`
  returned no frontend changes.
- 2026-06-24: Final W7 read-only re-review passed with no Critical or
  Important findings. Reviewer confirmed the previous manifest-version public
  leak was fixed, stream analysis is durable/outbox based and enqueued before
  `done`, runtime evidence includes `runtime_events` plus
  `runtime_planning_issue`, and acquired API/MCP/browser manifest checks cover
  execution plus confirmation resume. The reviewer was closed after completion.

## Workstream 8 Evidence

- 2026-06-24: W8 implementation added the `/api/v1/acquisition/*` public route
  surface, including gap, exploration, recommendation, proposal, permission,
  credential, browser session/trace, runtime planning issue, workspace
  connector, and journal routes through `backend/app/api/v1/acquisition.py` and
  `backend/app/core/acquisition/api_service.py`.
- 2026-06-24: W8 backend route contract verification passed:
  `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e
  PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q
  tests/test_acquisition_api_contracts.py"` -> `18 passed, 2 warnings`.
- 2026-06-24: Local Docker runtime drift was diagnosed and repaired without
  deleting persistent volumes. The main DB had already-created 0008-0011
  objects while Alembic was behind; the repair updated the local
  `alembic_version` from `0007` to `0008` only after confirming 0008 objects
  existed, then made 0009/0010/0011 migrations skip existing constraints,
  columns, and indexes. `docker compose logs backend` showed migrations running
  through `0016`, and `select version_num from alembic_version;` returned
  `0016`.
- 2026-06-24: W8 frontend acquisition API/store/UI verification passed:
  `docker compose run --rm --no-deps frontend sh -lc "npm run lint && npm run
  build"` -> eslint passed with no warnings; Next build compiled, typechecked,
  and prerendered `/`, `/_not-found`, `/chat`, `/login`, and `/settings`.
- 2026-06-24: W8 QA script syntax verification passed using Docker Node rather
  than host Node:
  `docker run --rm -v "${repo}:/repo:ro" -w /repo node:22-alpine sh -lc "node
  --check scripts/qa/acquisition-suite.cjs && node --check
  scripts/windows-browser-qa.cjs"`.
- 2026-06-24: W8 browser QA initially failed only at
  `acquisition-copy-or-empty-state` because the QA script recognized legacy V2
  empty-state phrases but not V3 acquisition empty-state phrases. UI evidence
  already contained `Problem`, `Cause`, `Risk`, `Next step`, `Recovery`,
  `No capability gaps recorded.`, `No acquisition proposals recorded.`, and
  `No active runtime acquisition controls.` The QA repair centralized V3
  empty/disabled text recognition without changing product UI.
- 2026-06-24: W8 read-only review found two Important QA contract weaknesses:
  `acquisition-api-overview` passed if any acquisition route worked, and
  Settings Acquisition could be misdetected through Capabilities/Workers fallback
  text. Fixes made API overview require zero unavailable acquisition routes and
  made Settings detection require the real `settings-acquisition-section`
  component after opening the `Acquisition` tab. A focused re-review confirmed
  the API route weakness was fixed, then found one remaining step-level bypass;
  the final fix made `settings-acquisition-section` require
  `settingsSurface.present` instead of accepting empty-state copy as a
  substitute for the component.
- 2026-06-24: Final W8 browser QA passed after the stricter QA contract:
  `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url
  http://localhost -Browser chrome -Headless -Suite capability-acquisition
  -TimeoutMs 240000` -> `ok: true`. Covered login, acquisition API overview,
  conversation creation, sidebar rename/delete visibility, chat right-panel
  acquisition presence, chat scroll movement, Settings Acquisition section,
  problem/cause/risk/next/recovery copy, empty-state handling, Settings
  conversation click routing back to `/chat`, and QA conversation cleanup.
  Report:
  `.gstack/qa-reports/local/capability-acquisition-2026-06-24T06-26-00-565Z`.
  Screenshots:
  `01-chat-acquisition-panel.png` and `02-settings-acquisition.png`.

## Pending Evidence

- None for Workstream 8.
