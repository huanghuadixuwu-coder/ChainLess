# V2 Capability Operating Layer Evidence

## EvidenceBundleDraft

Initial evidence:
- Worktree created on branch `codex/v2-capability-layer`.
- Docker server version detected: `29.3.1`.
- docker-compose version detected: `5.1.1`.
- Parent plan/spec are present in the coordination workspace and referenced by
  absolute path because they are not tracked in this new worktree.

Uncovered:
- Full backend suite not run.

## W1 Evidence

RED command:
`docker run --rm --network chainless_default ... chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py`

RED result:
- Exit code: 1
- Expected failure: `ModuleNotFoundError: No module named 'app.core.capabilities'`

Targeted GREEN command:
`docker build --build-arg INSTALL_TEST_DEPS=1 -t chainless-w1-backend-test:local ./backend`
`docker run --rm --network chainless_default ... chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py`

Targeted GREEN result:
- Exit code: 0
- Output: `16 passed in 11.21s`

Tenant isolation command:
`docker run --rm --network chainless_default ... chainless-w1-backend-test:local pytest -q tests/test_tenant_isolation.py`

Tenant isolation result:
- Exit code: 0
- Output: `5 passed in 3.84s`

Broader requested command:
`docker run --rm --network chainless_default ... chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py`

Broader requested result:
- Exit code: 1
- Output: `25 passed, 1 failed in 15.81s`
- Failure: `tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server`
- Observed detail: route returned status `201`, but `registered.json()` failed because the response body was empty.
- W1 assessment: failure is in existing MCP tool-registration contract, not Capability Candidate, Worker, Skill scope, or tenant isolation paths.

## W1 Closure Fix Evidence

Spec compliance fixes:
- Capability analysis outbox enqueue now uses PostgreSQL upsert for run-level
  idempotency under concurrent enqueue.
- Capability analysis claim now uses `FOR UPDATE SKIP LOCKED`.
- `skipped_duplicate` has an explicit outbox lifecycle helper and tests.
- Direct Skill get/update/delete now scopes to current user's private rows plus
  shared/legacy rows.
- Worker rollback now requires confirmation evidence and records the confirming
  user/evidence while reactivating the verified prior version.
- Worker rollback now also uses the same durable activation request/token gate
  as normal activation.
- Capability-layer JSON/error metadata now has app-level byte/depth bounds,
  bounded analysis error truncation, and database size checks.
- Candidate/analysis job/Worker/WorkerVersion/WorkerRun status/type contracts
  now have model and migration check constraints.
- Candidate retrieval helper now exposes only `accepted` and `edited_accepted`
  candidates, scoped to the same tenant/user.

MCP regression fix:
- Verified root cause matched the supplied diagnosis: stdio MCP clients kept a
  long-lived `stdio_client` context across request/task boundaries.
- Stdio discovery and calls now use short-lived contexts opened and closed in
  the same task; HTTP/SSE behavior remains persistent.
- This is recorded as a separate W1-discovered regression-fix slice required to
  keep the broader W1 API regression green. It does not add Capability/Worker
  integration into Agent planning or change Agent semantics.

Test harness note:
- Docker pytest commands now set `CHAINLESS_TESTING=1` before importing the app
  from `tests/conftest.py`, enabling the existing `NullPool` path. This avoids
  asyncpg pooled connections crossing pytest's function-scoped event loops.

W1 targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL=postgresql+asyncpg://chainless:chainless_test@chainless-db-test:5432/chainless_test -e REDIS_URL=redis://chainless-redis-test:6379/0 -e SECRET_KEY=test-secret -e PYTHONPATH=/repo/backend -v "${PWD}:/repo" -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 targeted result:
- Exit code: 0
- Output: `19 passed in 14.08s`

MCP API regression command:
`docker run --rm --network chainless_default -e DATABASE_URL=postgresql+asyncpg://chainless:chainless_test@chainless-db-test:5432/chainless_test -e REDIS_URL=redis://chainless-redis-test:6379/0 -e SECRET_KEY=test-secret -e PYTHONPATH=/repo/backend -v "${PWD}:/repo" -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server -vv`

MCP API regression result:
- Exit code: 0
- Output: `1 passed in 2.28s`

Broader requested command:
`docker run --rm --network chainless_default -e DATABASE_URL=postgresql+asyncpg://chainless:chainless_test@chainless-db-test:5432/chainless_test -e REDIS_URL=redis://chainless-redis-test:6379/0 -e SECRET_KEY=test-secret -e PYTHONPATH=/repo/backend -v "${PWD}:/repo" -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py`

Broader requested result:
- Exit code: 0
- Output: `26 passed in 17.89s`

MCP transport command:
`docker run --rm --network chainless_default -e DATABASE_URL=postgresql+asyncpg://chainless:chainless_test@chainless-db-test:5432/chainless_test -e REDIS_URL=redis://chainless-redis-test:6379/0 -e SECRET_KEY=test-secret -e PYTHONPATH=/repo/backend -v "${PWD}:/repo" -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_mcp_transports.py`

MCP transport result:
- Exit code: 0
- Output: `6 passed in 3.38s`

W1 review-fix RED command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 review-fix RED result:
- Exit code: 1
- Output: `6 failed, 18 passed in 18.37s`
- Expected failures covered unaccepted candidate retrieval, JSON/error bounds,
  durable check constraints, and rollback token gating.

W1 review-fix targeted GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 review-fix targeted GREEN result:
- Exit code: 0
- Output: `24 passed in 17.93s`

W1 review-fix broader GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W1 review-fix broader GREEN result:
- Exit code: 0
- Output: `32 passed in 20.91s`

W1 code-quality review fixes:
- Worker activation requests now persist `activation_requested_version_id`.
  Activation and rollback require token match and requested version match, then
  clear both token and requested version after success.
- App JSON validation now uses a conservative byte limit below the PostgreSQL
  `jsonb::text` check limit, and Worker public write paths translate residual
  bounds/status check failures to `422 VALIDATION_ERROR`.
- Migration `0008` downgrade now preflights duplicate Skill `(tenant_id, name)`
  rows and raises a clear `RuntimeError` before dropping scope/user columns.
- Migration `0010` adds `workers.activation_requested_version_id` with a
  foreign key to `worker_versions`.
- Final quality pass aligned app JSON validation with PostgreSQL-like spaced
  JSON text so array-heavy payloads reject before the database `jsonb::text`
  size checks, and Capability Candidate / outbox write paths translate
  residual constraint failures to `422 VALIDATION_ERROR`.

W1 code-quality RED command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 code-quality RED result:
- Exit code: 1
- Output: `4 failed, 24 passed, 1 warning in 21.04s`
- Expected failures covered cross-version activation token misuse,
  cross-version rollback token misuse, public JSON bounds 500, and missing
  downgrade duplicate-Skill preflight.

W1 code-quality targeted GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 code-quality targeted GREEN result:
- Exit code: 0
- Output: `28 passed in 20.26s`

W1 code-quality broader GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W1 code-quality broader GREEN result:
- Exit code: 0
- Output: `32 passed in 21.00s`

W1 final JSON-bound targeted GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv`

W1 final JSON-bound targeted GREEN result:
- Exit code: 0
- Output: `28 passed in 20.11s`

W1 final regression GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W1 final regression GREEN result:
- Exit code: 0
- Output: `32 passed in 21.21s`

Alembic state command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local sh -c "alembic current && alembic heads"`

Alembic state result:
- Exit code: 0
- Output: `0010 (head)` and `0010 (head)`

Diff hygiene command:
`git diff --check`

Diff hygiene result:
- Exit code: 0
- Output: no whitespace errors; Git reported CRLF conversion warnings for
  existing Windows working-copy settings.

Independent review results:
- W1 spec compliance reviewer returned `SPEC_PASS`.
- W1 code-quality reviewer returned `QUALITY_PASS`.

W1 coverage:
- Capability Candidate create/list/get/status actions/merge/user isolation/tenant isolation/serialization/inactive retrieval stub.
- Candidate analysis job enqueue/claim/complete/fail/run-level idempotency.
- Skill personal scope migration behavior and scoped uniqueness.
- Worker draft/version draft/activation gate/confirmation evidence/disable/enable/soft delete/rollback/user isolation/tenant isolation.

W1 non-goals preserved:
- No Agent planning integration.
- No candidate analyzer runtime.
- No Worker execution runtime.
- No frontend changes.
- No commit.

## W2 Rule-First Candidate Generation Evidence

W2 RED tests added:
- Rule filter coverage for remember, next-time, always, tool-chain, artifact,
  user-correction, fallback useful-run, and pure greeting non-trigger.
- Analyzer parsing coverage with a fake gateway returning valid strict JSON for
  one Memory, one Skill, and one Worker candidate.
- Stream-tail coverage proving a next-time chat run persists an inactive
  candidate and emits `capability_candidate` before `done`.
- Outbox/background coverage proving analyzer timeout leaves a pending durable
  job, background processing later persists a candidate, duplicate processing
  is idempotent, and analyzer failure stores bounded metadata plus metrics.

W2 RED command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py`

W2 RED result:
- Exit code: 1
- Output: `ModuleNotFoundError: No module named 'app.core.capabilities.analyzer'`

W2 implementation summary:
- Added `app.core.capabilities.rules` as the deterministic rule gate.
- Added `app.core.capabilities.analyzer` with strict JSON parsing, allowed
  candidate types only, confidence clamping, bounded evidence, and invalid
  output fallback to no candidates.
- Extended `app.core.capabilities.outbox` with W2-compatible enqueue/claim
  wrappers, duplicate enqueue metrics, and bounded failure result metadata
  while preserving W1 helper names.
- Extended `app.core.capabilities.service` as the capability facade for
  stream-tail enqueue/analyze, deduped inactive candidate persistence,
  dismissed/muted suppression, timeout/failure metrics, and background pending
  job processing.
- Added `app.core.capabilities.tasks.process_capability_analysis` as the
  ARQ-compatible entrypoint.
- Integrated `conversation_stream_service.py` only through the capability
  facade after assistant persistence; stream service does not own rule,
  analyzer, outbox, or candidate persistence internals.

W2 intermediate verification command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py`

W2 intermediate result:
- Exit code: 1
- Output: `1 failed, 36 passed in 16.48s`
- Failure: `test_rules_text_signals_trigger_candidate_analysis` flagged the
  plain preference `Always use pnpm for this repo instead of npm.` as
  `user_correction=True`.
- Fix: tightened correction detection so ordinary `always ... instead of ...`
  preference text does not count as a correction without correction/no/actually
  language.

W2 final GREEN command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py`

W2 final GREEN result:
- Exit code: 0
- Output: `37 passed in 15.33s`

W2 stop condition coverage:
- Useful runs create durable, idempotent analysis jobs.
- Completed analysis creates inactive, deduped personal Memory/Skill/Worker
  candidates.
- Stream-tail completed analysis can emit a lightweight
  `capability_candidate` SSE hint with `active: false`.
- Pure chat noise does not trigger candidate generation.
- Analyzer timeout does not silently lose eligible work because the pending
  outbox job remains for background processing.

W2 non-goals preserved:
- No candidate acceptance into Memory/Skill/Worker.
- No Agent planning/retrieval integration.
- No Worker execution runtime.
- No frontend changes.
- No commit.

## W2 Spec Review Fix Evidence

Review finding 1:
- `conversation_stream_service.py` emitted `capability_candidate`, but
  `backend/app/api/sse.py` did not include it in the canonical `SSEEventName`
  contract.

Resolution 1:
- Added `capability_candidate` to `SSEEventName`.
- Added a focused `sse_event("capability_candidate", ...)` assertion in
  `tests/test_sse_contract.py`.

Review finding 2:
- Broad `muted_pattern` suppression only ran after exact
  tenant/user/type/dedupe lookup, so new dedupe keys matching an existing mute
  pattern could still create candidates and chat hints.

Resolution 2:
- Added same tenant/user/candidate_type muted-pattern scanning before candidate
  creation/hint emission.
- Kept exact dismissed dedupe suppression for exact repeats.
- Added `test_broad_muted_pattern_suppresses_new_matching_candidate_and_hint`
  to prove a broad mute pattern suppresses a new matching candidate and returns
  no SSE hint payload.

W2 review-fix targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py`

W2 review-fix targeted result:
- Exit code: 0
- Output: `38 passed in 16.37s`

W2 review-fix broad regression command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_worker_runtime.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W2 review-fix broad regression result:
- Exit code: 0
- Output: `43 passed in 30.03s`

## W2 Code Quality Fix Evidence

Code quality finding 1:
- Background analysis jobs could be claimed, committed as `running`, and then
  hang forever if the analyzer never returned. Claiming only selected
  `pending` rows.

Resolution 1:
- `claim_pending_analysis` now also reclaims stale `running` rows when
  `claimed_at` is older than a bounded lease.
- `process_pending_capability_analysis` wraps background analyzer processing in
  `asyncio.wait_for`; a hung analyzer marks the job `failed` with
  `ANALYZER_TIMEOUT`, bounded metadata, and timeout/failure metrics.
- Added tests for stale-running reclaim and a hung fake gateway.

Code quality finding 2:
- Future-snoozed candidates could still be updated and returned as chat hints.

Resolution 2:
- Exact dedupe repeats now suppress update/hint while `snoozed_until` is in
  the future.
- Expired snoozes are allowed to update and reopen to `new`.
- Added a future-snooze regression test proving no hint and no candidate update
  before expiry.

Code quality finding 3:
- Exact dedupe lookup returned only the latest row, so a latest merged duplicate
  could cause repeat analysis to create a new candidate despite an older inbox
  or accepted target.

Resolution 3:
- Exact dedupe lookup now follows `merge_target_candidate_id` and otherwise
  resolves by status priority before creating new rows.
- Added a merge-repeat regression test proving the merge target is updated and
  no third duplicate candidate is created.

W2 code-quality targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py`

W2 code-quality targeted result:
- Exit code: 0
- Output: `42 passed in 18.38s`

W2 code-quality broad regression command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_worker_runtime.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W2 code-quality broad regression result:
- Exit code: 0
- Output: `43 passed in 31.22s`

## W3 Candidate Acceptance Evidence

W3 implementation summary:
- `/api/v1/capability-candidates/{id}/accept` now routes accepted candidates
  into real private Memory rows, private passive Skill rows, or inactive Worker
  draft/version rows.
- Accepted Worker improvement candidates create a new draft `WorkerVersion`
  without overwriting prior versions.
- Accepted candidates store target resource IDs in candidate metadata and move
  to `accepted` or `edited_accepted`.
- Optional edited proposals use a strict top-level schema and bounded nested
  JSON validation.
- Memory list/search/merge and chat session context now pass the current
  `user_id` into persistent memory retrieval; Skill visibility is current user
  plus explicit `shared`/`shared_legacy`.

W3 first targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_acceptance.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv`

W3 first targeted result:
- Exit code: 0
- Output: `17 passed in 9.42s`

W3 first broad regression command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_worker_runtime.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W3 first broad regression result:
- Exit code: 0
- Output: `73 passed in 44.49s`

W3 spec review finding:
- Initial independent spec review returned `SPEC_FAIL` because accepted private
  Memory could still leak into another same-tenant user's chat context through
  `conversations.py -> _build_session_context -> get_memories_for_session`
  without `user_id`.

W3 spec-review fix:
- `chat()` now passes `current_user["user_id"]` into `_build_session_context`.
- `_build_session_context` passes `user_id` into persistent memory retrieval.
- Added `tests/test_conversation_memory_context.py` to exercise real chat/SSE
  context and prove another same-tenant user's private accepted Memory is not
  injected.

W3 privacy-fix targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_conversation_memory_context.py tests/test_capability_acceptance.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv`

W3 privacy-fix targeted result:
- Exit code: 0
- Output: `18 passed in 10.86s`

W3 privacy-fix broad regression result:
- Exit code: 0
- Output: `73 passed in 45.36s`

W3 spec re-review result:
- Independent reviewer returned `SPEC_PASS`.

W3 code-quality review finding:
- Initial independent quality review returned `QUALITY_FAIL` because concurrent
  candidate acceptance could create duplicate target resources before the
  candidate status transition.

W3 exactly-once fix:
- Acceptance now loads the scoped candidate row under `SELECT ... FOR UPDATE`
  before status check and target creation.
- Concurrent memory-candidate acceptance regression proves exactly one success,
  one `409 CAPABILITY_CANDIDATE_NOT_ACCEPTABLE`, and one target `Memory`.
- `create_memory(commit=False, write_source=False)` no longer enqueues
  embedding before the outer acceptance transaction commits; acceptance
  enqueues/writes source after commit.

W3 exactly-once targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_acceptance.py tests/test_conversation_memory_context.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv`

W3 exactly-once targeted result:
- Exit code: 0
- Output: `19 passed in 12.09s`

W3 exactly-once broad regression command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_worker_runtime.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W3 exactly-once broad regression result:
- Exit code: 0
- Output: `73 passed in 44.41s`

W3 diff hygiene result:
- Exit code: 0
- Output: no whitespace errors; Git reported CRLF conversion warnings only.

W3 final independent review results:
- Spec compliance reviewer returned `SPEC_PASS`.
- Code-quality reviewer returned `QUALITY_PASS`.

W3 residual risks:
- Accepted Memory source-file write is post-commit and synchronous; future work
  should consider logging/retry/outbox if filesystem writes fail after DB
  acceptance is durable.
- Memory acceptance currently holds the candidate row lock while inline
  embedding may run; correctness is preserved, but slow embedding can extend
  lock wait time.

W3 non-goals preserved:
- No Agent planning/retrieval integration.
- No Worker execution runtime.
- No frontend changes.
- No commit.

## W4 Worker Runtime, Matching, Fallback, and Feedback Evidence

W4 implementation summary:
- Added semantic Worker matching with embedding-backed score, keyword as
  supplemental signal only, input-schema checks, risk/feedback modifiers, and
  ordered match decisions.
- Added minimal Worker policy facade before runtime execution: activation
  state, active verified version, user confirmation/audit requirement, input
  schema, risk confirmation, allowed-tool policy, confirmation-context packing,
  same-worker reentry block, and max-depth guard.
- Added executable Worker runtime through the existing Agent engine rather than
  a parallel executor. Runtime records `WorkerRun`, feedback confidence,
  failure improvement candidates, bounded persisted traces, and fallback
  metadata.
- Connected normal chat/SSE to Worker matching. `auto_notice` Workers execute;
  high-risk/`needs_confirmation` Workers emit `worker_notice` and continue the
  normal Agent path; medium matches do not execute.
- Added fallback transparency with `worker_notice`, final status, and
  canonical terminal events.

W4 first targeted command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv`

W4 first targeted result:
- Exit code: 0
- Output: `36 passed in 19.62s`

W4 first broad W1-W4 regression command:
`docker run --rm --network chainless_default -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_conversation_memory_context.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_tenant_isolation.py tests/test_mcp_transports.py`

W4 first broad W1-W4 regression result:
- Exit code: 0
- Output: `81 passed in 47.62s`

W4 full backend environment lesson:
- Running the full backend suite without `APP_ENV=test`,
  `CHAINLESS_TESTING=1`, and `SANDBOX_IMAGE=chainless-sandbox:latest` fails at
  the explicit isolated-test guard and sandbox-proxy import.
- Correct full-suite Docker env must include those three values in addition to
  `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, and `PYTHONPATH`.

W4 full backend command after correct env:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`

W4 full backend result after correct env:
- Exit code: 0
- Output: `410 passed, 4 skipped, 1 warning in 136.12s`

W4 spec-review finding:
- Initial independent spec review returned `SPEC_FAIL` because active Workers
  were not actually callable from normal chat and fallback status was not
  event-transparent.

W4 spec-review fix:
- `run_agent_stream()` now calls Worker matching before normal Agent execution.
- `_maybe_execute_worker_for_stream()` executes only `auto_notice` Workers
  through `execute_worker_run`.
- `needs_confirmation` and high-risk Workers emit `worker_notice` and continue
  normal Agent flow.
- Fallback now emits a visible Worker failure/fallback notice before fallback
  events.

W4 spec re-review result:
- Independent reviewer returned `SPEC_PASS`.

W4 first code-quality finding:
- Independent quality review returned `QUALITY_FAIL` because
  `execute_worker_run()` returned DB-bounded `output_payload["events"]` as the
  live stream source. When a Worker emitted more than `MAX_CAPTURED_EVENTS`
  events, the final terminal event could be clipped, and SSE could wait forever
  on heartbeats.

W4 first code-quality fix:
- Runtime now separates live events from bounded persisted trace.
- Persisted trace remains capped for DB safety.
- `_bounded_events()` preserves the last terminal event when clipping.
- Added chat/SSE regression for a Worker emitting `MAX_CAPTURED_EVENTS + 1`
  chunks and still terminating with canonical `done`.
- Added failed-fallback regression proving a canonical SSE `error` and `done`
  are emitted rather than heartbeat-only hang.

W4 terminal-trace targeted command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv`

W4 terminal-trace targeted result:
- Exit code: 0
- Output: `38 passed in 21.87s`

W4 second code-quality finding:
- Fresh quality review returned `QUALITY_FAIL` because
  `failed_fallback_failed` could be masked by earlier Worker `error`/`done`
  terminal events, causing SSE/persisted trace to surface the stale terminal
  instead of the final fallback failure.

W4 second code-quality fix:
- Fallback execution strips terminal events from the failed Worker before
  appending fallback events.
- `failed_fallback_failed` strips earlier terminal events and appends
  canonical `WORKER_FALLBACK_FAILED` as the final live and persisted terminal.
- Plain `failed` removes trailing `done` after an error, or appends canonical
  runtime error when none exists.
- Added exact regression where Worker first produces an `error`/`done` terminal
  pair and fallback then fails; final SSE and DB trace must end with
  `WORKER_FALLBACK_FAILED`.

W4 exact final-status regression command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done -vv`

W4 exact final-status regression result:
- Exit code: 0
- Output: `1 passed in 1.05s`

W4 final targeted command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv`

W4 final targeted result:
- Exit code: 0
- Output: `39 passed in 19.79s`

W4 final broad W1-W4 regression result:
- Exit code: 0
- Output: `81 passed in 44.09s`

W4 final full backend result:
- Exit code: 0
- Output: `413 passed, 4 skipped, 1 warning in 127.65s`

W4 final diff hygiene result:
- Exit code: 0
- Output: no whitespace errors; Git reported CRLF conversion warnings only.

W4 final independent review results:
- Spec compliance reviewer returned `SPEC_PASS`.
- Code-quality re-review returned `QUALITY_PASS`.

W4 residual risks:
- Worker matching is embedding-backed but not yet persisted/indexed as
  Worker-side pgvector rows; current W4 computes embeddings at match time.
- Minimal policy vocabulary should be tightened in later W6 policy/hook work.
- `WorkerRun.error_code/error_message` can still reflect the initial Worker
  failure while live/persisted terminal events correctly represent the final
  fallback status. This is non-blocking but worth aligning later.
- `conversation_stream_service.py` is now a large facade; W4 kept it as a
  thin integration seam, but future work should avoid growing it further.

W4 execution hygiene notes:
- Full backend Docker tests must include `APP_ENV=test`,
  `CHAINLESS_TESTING=1`, and `SANDBOX_IMAGE=chainless-sandbox:latest`.
- In PowerShell, avoid raw double-quoted `rg` patterns containing JSON/code
  quotes; use single-quoted patterns or `Get-Content` slices to avoid parser
  errors.
- One quality-fix subagent stopped responding after partially writing the
  patch; it was closed, and all reviewer/worker subagents used in W4 were
  released after their result or shutdown.

W4 non-goals preserved:
- No frontend style or UI edits.
- No commit.

## W5 Agent Soft Merge and Capability Retrieval Evidence

W5 implementation summary:
- Added `backend/app/core/capabilities/retrieval.py` as the source-traced
  capability context facade for Agent planning.
- Extended existing Memory retrieval helpers with a default-compatible
  `include_userless` switch so W5 can request private-only Memory planning
  without changing legacy chat/memory API behavior.
- Added separate planning sections for `Current user request`,
  `Relevant private memories`, `Relevant private skills`,
  `Matched worker candidates`, and `Hard guard summary`.
- Added prompt-builder support for `render_capability_context(...)`,
  `merge_capability_context_into_messages(...)`, and
  `build_context(..., capability_context=...)` while preserving existing
  callers.
- Updated `conversation_stream_service.py` so normal chat calls the retrieval
  facade once, injects the accepted capability context into Agent planning, and
  reuses the same Worker match decisions for Worker auto-execution.
- Kept inactive `CapabilityCandidate` rows inert by not querying candidate
  tables in the planning facade.

W5 initial RED command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_planning.py`

W5 initial RED result:
- Exit code: 1
- Output: `ImportError: cannot import name 'render_capability_context' from 'app.core.agent.prompt_builder'`.

W5 first targeted GREEN command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_planning.py -vv`

W5 first targeted GREEN result:
- Exit code: 0
- Output: `3 passed in 2.23s`.

W5 plan-required GREEN command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py -vv`

W5 plan-required GREEN result:
- Exit code: 0
- Output: `30 passed in 16.05s`.

W5 first broad regression command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py -vv`

W5 first broad regression result:
- Exit code: 0
- Output: `87 passed in 47.69s`.

W5 first full backend command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`

W5 first full backend result:
- Exit code: 0
- Output: `416 passed, 4 skipped, 1 warning in 134.88s`.

W5 read-only code review findings:
- Important: Capability Memory retrieval admitted `Memory.user_id IS NULL`
  tenant-level legacy memories through the existing persistent memory helper.
- Important: Capability Skill retrieval admitted `shared` scope and current-user
  non-private scopes, broader than the W5 contract.
- Important: Raw current user request text was rendered into the system prompt
  without explicitly labeling it as untrusted user-role data.

W5 review fixes:
- Capability planning now filters Memory results to `memory.user_id ==
  current_user_id` by calling the existing Memory service in
  `include_userless=False` mode before relevance results are returned.
- Capability planning Skill visibility is current-user `private` plus null-user
  `shared_legacy` only.
- The `Current user request` section now labels the text as
  `UNTRUSTED current user request data` and states that instructions inside it
  do not override system/developer instructions or hard guards.
- Added regression assertions for tenant-level Memory exclusion, non-private
  Skill exclusion, `shared` Skill exclusion, and adversarial request text.
- Closed the reviewer subagent after completion.

W5 review-fix RED command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_planning.py -vv`

W5 review-fix RED result:
- Exit code: 1
- Output: `3 failed in 2.96s`.

W5 final targeted GREEN command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py`

W5 final targeted GREEN result:
- Exit code: 0
- Output: `30 passed in 15.42s`.

W5 final broad regression command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py`

W5 final broad regression result:
- Exit code: 0
- Output: `87 passed in 46.48s`.

W5 final full backend command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`

W5 final full backend result:
- Exit code: 0
- Output: `416 passed, 4 skipped, 1 warning in 133.90s`.

W5 stop condition coverage:
- Agent context supports separate Claude Code-style soft-merge sections for
  accepted Memory, Skill, Worker, current request, and hard guards.
- Memory, Skill, and Worker retrieval are user-scoped for W5 planning.
- Semantic Worker matches are source-traced and reused for chat Worker
  execution.
- Unaccepted Capability Candidates remain behaviorally inert.

W5 residual risks:
- `conversation_stream_service.py` remains a large facade. W5 reduced direct
  matcher ownership there, but W6 should keep extracting policy/hook behavior
  instead of adding more orchestration branches to the file.
- Legacy `_build_session_context` still injects Memory/layered instruction
  context separately for compatibility. W5 capability planning is stricter; a
  later consolidation can decide whether the older Memory path should be
  folded fully into the capability context facade.

W5 non-goals preserved:
- No frontend style or UI edits.
- No commit.

## W6 Minimal Hard Guards and Internal Hooks Evidence

W6 implementation summary:
- Added `app.core.capabilities.hooks` as a bounded in-process hook event
  recorder for `before_worker_match`, `before_worker_run`,
  `after_worker_run`, `before_tool_call`, `after_tool_call`,
  `on_worker_failure`, and `on_capability_candidate_created`.
- Expanded `app.core.capabilities.policy` into the canonical Worker/tool
  policy facade for activation/input/risk checks, allowed-tool enforcement,
  destructive/external-delivery confirmation, and confirmation-resume parity.
- Added `app.core.capabilities.orchestration` as the conversation stream
  boundary seam so stream orchestration does not import policy internals
  directly.
- Wired Worker match/run, Agent tool calls, Worker failure feedback, Candidate
  creation, and confirmation resume through the policy/hook seams without
  letting hooks override denied decisions.
- Persisted Worker confirmation context for destructive tool pauses without
  leaking secret arguments into `WorkerRun.confirmation_metadata`. This claim
  is limited to WorkerRun confirmation metadata; pending confirmation records
  still persist tool arguments for replay.
- Tightened `failed_fallback_failed` audit metadata so the persisted
  `WorkerRun.error_code/error_message` reflects the final fallback failure
  (`WORKER_FALLBACK_FAILED`) rather than stale initial Worker/tool errors.

W6 initial RED command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py -vv`

W6 initial RED result:
- Exit code: 1
- Output: `ModuleNotFoundError: No module named 'app.core.capabilities.hooks'`.

W6 policy/hooks targeted GREEN command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py -vv`

W6 policy/hooks targeted GREEN result:
- Exit code: 0
- Output: `5 passed in 2.26s`.

W6 plan-required regression command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py`

W6 plan-required regression result:
- Exit code: 0
- Output: `15 passed in 7.58s`.

W6 W1-W6 broad regression command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_capability_policy_hooks.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py`

W6 W1-W6 broad regression result:
- Exit code: 0
- Output: `102 passed in 53.49s`.

W6 fallback-audit RED command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done -vv`

W6 fallback-audit RED result:
- Exit code: 1
- Output: stale persisted `WorkerRun.error_code` values
  `WORKER_RUNTIME_ERROR` and `TOOL_NOT_AUTHORIZED` while final events already
  reported `WORKER_FALLBACK_FAILED`.

W6 fallback-audit GREEN result:
- Same command after runtime fix returned `2 passed in 1.98s`.

W6 final targeted command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`

W6 final targeted result:
- Exit code: 0
- Output: `17 passed in 9.33s`.

W6 final full backend command:
`docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`

W6 final full backend result:
- Exit code: 0
- Output: `421 passed, 4 skipped, 1 warning in 136.29s`.

W6 stream-service policy-boundary check:
`Select-String -Path 'backend\app\services\conversation_stream_service.py' -Pattern 'capabilities\.policy|evaluate_worker_policy|require_worker_tool_policy|unpack_confirmation_args'`

W6 stream-service policy-boundary result:
- Exit code: 0
- Output: no matches.

W6 post-facade targeted result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
- Exit code: 0
- Output: `17 passed in 9.20s`.

W6 post-facade full backend result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`
- Exit code: 0
- Output: `421 passed, 4 skipped, 1 warning in 137.52s`.

W6 code-review findings:
- Independent read-only reviewer returned no Critical findings and two
  Important findings: normal Worker runtime disallowed tools could be blocked
  by generic `authorized_tool_names` before Worker policy/hook evaluation, and
  `definition.external_delivery` did not participate in the same confirmation
  policy/matcher model.
- Advisory findings: secret-free evidence only covered
  `WorkerRun.confirmation_metadata`, not persisted confirmation replay args;
  and Worker runtime direct improvement candidates did not emit the
  candidate-created hook.
- Reviewer subagent was closed after returning feedback.

W6 review-fix RED result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py::test_worker_policy_requires_external_delivery_and_destructive_confirmation tests/test_capability_policy_hooks.py::test_empty_worker_allowed_tools_blocks_normal_and_confirmation_resume -vv`
- Exit code: 1
- Output: `2 failed`, proving `definition.external_delivery` returned
  `allow` and real Worker runtime disallowed tools emitted
  `TOOL_NOT_AUTHORIZED`.

W6 review-fix lifecycle RED result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py::test_worker_failure_hook_records_event_and_improvement_candidate -vv`
- Exit code: 1
- Output: missing `on_capability_candidate_created` hook for Worker runtime
  direct improvement candidates.

W6 review-fix implementation:
- Added `requires_worker_confirmation()` as the shared policy helper for risk,
  explicit confirmation, external delivery, and external confirmation flags
  from both Worker policy and WorkerVersion definition.
- Updated Worker matcher to use the shared helper.
- Removed Worker runtime's use of generic `authorized_tool_names`; Worker
  allow-lists now go through `evaluate_worker_tool_policy` and emit the W6
  before/after tool hooks.
- Added risky confirmation-resume context enforcement so Worker destructive or
  external-delivery resume requires a stored confirmation context.
- Added `on_capability_candidate_created` emission for Worker runtime direct
  improvement candidates after `db.flush()`.

W6 review-fix targeted result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py tests/test_worker_runtime.py::test_worker_match_decisions_use_semantics_schema_risk_and_active_state -vv`
- Exit code: 0
- Output: `7 passed in 3.32s`.

W6 review-fix extended result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q tests/test_capability_policy_hooks.py tests/test_worker_runtime.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
- Exit code: 0
- Output: `36 passed in 21.45s`.

W6 review-fix final full backend result:
- Command: `docker run --rm --network chainless_default -e APP_ENV='test' -e CHAINLESS_TESTING='1' -e DATABASE_URL='postgresql+asyncpg://chainless:chainless_test@db-test:5432/chainless_test' -e REDIS_URL='redis://redis-test:6379/0' -e SECRET_KEY='test-secret' -e SANDBOX_IMAGE='chainless-sandbox:latest' -e PYTHONPATH='/repo/backend' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer:/repo' -w /repo/backend chainless-w1-backend-test:local pytest -q`
- Exit code: 0
- Output: `422 passed, 4 skipped, 1 warning in 134.21s`.

W6 stop condition coverage:
- Worker/capability execution paths now pass explicit policy/hook seams for
  matching, execution, tool calls, confirmation pause/resume, failure feedback,
  and candidate creation.
- Denied Worker/tool policy decisions are enforced before execution and cannot
  be overridden by prompt text or hook recording.
- Empty allowed-tool allow-lists now mean no tools when the allow-list key is
  present, and this is verified in normal execution and confirmation resume.
- Destructive Worker tool confirmations carry Worker context, tool name, risk,
  run id, and allowed-tool state without persisting secret tool arguments in
  `WorkerRun.confirmation_metadata`.

W6 residual risks:
- Hooks are currently bounded in-process observability events. Durable external
  hook sinks or admin observability UI remain future scope.
- Worker matching is still embedding-backed at runtime rather than backed by
  persisted Worker-side pgvector rows.

W6 non-goals preserved:
- No frontend style or UI edits.
- No W6 commit.
