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

## Pending Evidence

- W5 RED/GREEN evidence.
- W5 spec compliance review.
- W5 code quality review.
