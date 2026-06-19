# V2 Capability Operating Layer Checkpoint

## TodoCheckpointDraft

Current todo:
- W7 next

Completed todos:
- W1 RED tests added for Capability Candidate contract, analysis outbox, Skill personal scope, and Worker activation gates.
- W1 models/migration added for CapabilityCandidate, CapabilityAnalysisJob, Worker, WorkerVersion, WorkerRun, WorkerMatchFeedback, and Skill user_id/scope.
- W1 thin services/routers added for `/api/v1/capability-candidates` and `/api/v1/workers`.
- W1 spec-compliance fixes added for atomic analysis outbox enqueue/claim, `skipped_duplicate`, private Skill direct-id scoping, and rollback confirmation evidence.
- W1 review fixes added for rollback activation-token gating, bounded JSON/error metadata, durable status/type constraints, and accepted-only candidate retrieval.
- W1 code-quality fixes added for version-bound activation tokens, conservative app JSON bounds, Worker public bounds-error translation, and Skill downgrade duplicate preflight.
- W1 final quality fix aligned JSON bounds with PostgreSQL-like JSON text for array-heavy payloads and added residual Capability/Outbox bounds-error translation.
- MCP stdio transport regression fixed as a separate W1-discovered regression-fix slice by avoiding long-lived stdio contexts across request tasks.
- Targeted W1 Docker verification passed: `28 passed`.
- Broader API/tenant/MCP Docker verification passed: `32 passed`.
- Independent W1 spec review returned `SPEC_PASS`; independent W1 code-quality review returned `QUALITY_PASS`.
- W2 RED tests added for rule filtering, analyzer parsing, stream-tail candidate
  hinting, timeout preservation, background processing, idempotent dedupe, and
  failure metrics.
- W2 implementation added deterministic rules, strict analyzer parsing,
  durable enqueue/claim wrappers, deduped inactive candidate persistence,
  stream-tail facade integration, and an ARQ-compatible processor wrapper.
- W2 targeted Docker verification passed: `37 passed`.
- W2 spec-review fixes added canonical `capability_candidate` SSE contract
  coverage and broad `muted_pattern` suppression before new candidate
  creation/hint.
- W2 review-fix targeted Docker verification passed: `38 passed`.
- W2 review-fix broad Docker regression passed: `43 passed`.
- W2 code-quality fixes added stale running job reclaim, bounded background
  analyzer timeout failure, future-snooze suppression, and merge-target-aware
  dedupe resolution.
- W2 code-quality targeted Docker verification passed: `42 passed`.
- W2 code-quality broad Docker regression passed: `43 passed`.
- Independent W2 spec review returned `SPEC_PASS`; independent W2 code-quality review returned `QUALITY_PASS`.
- W3 implementation added Candidate acceptance routing into private Memory,
  private passive Skill, inactive Worker drafts, Worker draft improvements, and
  strict edited proposal handling.
- W3 privacy fixes scoped Memory list/search/merge/session-context and Skill
  list/match/direct access to current user plus explicit shared/legacy scope.
- W3 spec-review fix closed same-tenant private Memory leakage through chat
  session context by passing `user_id` into `_build_session_context` and memory
  retrieval.
- W3 code-quality fix made candidate acceptance exactly-once under concurrent
  double-submit by locking the scoped candidate row before target creation and
  adding a concurrent acceptance regression.
- W3 targeted Docker verification passed: `19 passed`.
- W3 broad Docker regression passed: `73 passed`.
- Independent W3 spec review returned `SPEC_PASS`; independent W3 code-quality
  review returned `QUALITY_PASS`.
- W4 implementation added semantic Worker matching, minimal executable Worker
  policy facade, Worker runtime execution through the existing Agent engine,
  recursion/depth guards, activation confirmation/audit gates, fallback status,
  runtime feedback, and normal chat/SSE Worker routing.
- W4 spec-review fix connected active Workers to the real chat streaming path:
  `auto_notice` Workers execute through `execute_worker_run`, high-risk or
  `needs_confirmation` Workers surface `worker_notice` and continue normal
  Agent flow, and medium matches do not execute.
- W4 code-quality fixes separated live Worker stream events from bounded
  persisted traces, preserved terminal events when trace clipping occurs, and
  made failed fallback paths terminate with canonical `WORKER_FALLBACK_FAILED`
  instead of stale worker terminal events.
- W4 targeted Docker verification passed: `39 passed`.
- W4 W1-W4 broad regression passed: `81 passed`.
- W4 full backend Docker verification passed: `413 passed, 4 skipped`.
- Independent W4 spec review returned `SPEC_PASS`; independent W4 code-quality
  re-review returned `QUALITY_PASS`.
- W5 implementation added `app.core.capabilities.retrieval` as the canonical
  Agent capability context facade, source-traced accepted Memory/Skill/Worker
  planning sections, prompt-builder soft merge support, and stream-service
  integration through the retrieval facade.
- W5 review fixes tightened Capability planning scope so Memory is current-user
  private only, Skill is current-user private plus explicit `shared_legacy`
  only, unaccepted candidates remain inert, and current user request text is
  rendered as untrusted user-role data inside the system prompt.
- W5 also added a default-compatible `include_userless` switch to existing
  Memory retrieval helpers so capability planning can be private-only without
  changing legacy chat/memory API behavior.
- W5 targeted Docker verification passed: `30 passed`.
- W5 W1-W5 broad Docker regression passed: `87 passed`.
- W5 full backend Docker verification passed: `416 passed, 4 skipped`.
- W5 read-only code review found three Important issues; all were fixed and
  reverified. The reviewer subagent was closed after completion.
- W5 was committed and pushed to `origin/codex/v2-capability-layer` as
  `24ad0ad feat: add capability planning retrieval`.
- W6 implementation added a bounded internal capability hook recorder,
  explicit Worker/tool policy decisions, hook emission for Worker match/run,
  tool call, Worker failure, and candidate creation seams, and confirmation
  context persistence for destructive Worker tool pauses.
- W6 added `app.core.capabilities.orchestration` so
  `conversation_stream_service.py` calls a capability orchestration seam
  instead of importing policy internals directly.
- W6 also tightened runtime audit metadata so `failed_fallback_failed`
  WorkerRuns persist final `WORKER_FALLBACK_FAILED` error metadata instead of
  stale initial Worker/tool errors.
- W6 code-review fixes made normal Worker runtime disallowed tools pass the
  same Worker policy/hook gate as confirmation resume, made
  `definition.external_delivery` require confirmation in both policy and
  matcher, and made Worker runtime improvement candidates emit
  `on_capability_candidate_created`.
- W6 targeted Docker verification passed: `36 passed`.
- W6 W1-W6 broad Docker regression passed: `102 passed`.
- W6 full backend Docker verification passed: `422 passed, 4 skipped`.

Active slice:
- W7 next.

Evidence refs:
- Worktree created at `C:/Users/11367/.config/aegis/worktrees/Chainless/codex-v2-capability-layer`
- Docker available: server `29.3.1`
- docker-compose available: `5.1.1`
- RED: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py` failed with `ModuleNotFoundError: No module named 'app.core.capabilities'`.
- GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py` passed with `16 passed in 11.21s`.
- Regression: `docker run ... pytest -q tests/test_tenant_isolation.py` passed with `5 passed in 3.84s`.
- Closure GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` passed with `19 passed in 14.08s`.
- MCP regression GREEN: `docker run ... pytest -q tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server -vv` passed with `1 passed in 2.28s`.
- Broader requested GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py` passed with `26 passed in 17.89s`.
- MCP transport GREEN: `docker run ... pytest -q tests/test_mcp_transports.py` passed with `6 passed in 3.38s`.
- Review-fix RED: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` failed with `6 failed, 18 passed in 18.37s`.
- Review-fix GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` passed with `24 passed in 17.93s`.
- Review-fix broader GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `32 passed in 20.91s`.
- Code-quality RED: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` failed with `4 failed, 24 passed, 1 warning in 21.04s`.
- Code-quality GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` passed with `28 passed in 20.26s`.
- Code-quality broader GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `32 passed in 21.00s`.
- Alembic state: `alembic current && alembic heads` returned `0010 (head)` / `0010 (head)`.
- Final JSON-bound GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_worker_runtime.py -vv` passed with `28 passed in 20.11s`.
- Final regression GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `32 passed in 21.21s`.
- Final diff hygiene: `git diff --check` returned no whitespace errors, only Git CRLF conversion warnings.
- Independent reviews: spec reviewer returned `SPEC_PASS`; code-quality reviewer returned `QUALITY_PASS`.
- W2 RED: `docker run ... pytest -q tests/test_capability_candidates.py` failed with `ModuleNotFoundError: No module named 'app.core.capabilities.analyzer'`.
- W2 GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py` passed with `37 passed in 15.33s`.
- W2 review-fix GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py` passed with `38 passed in 16.37s`.
- W2 review-fix regression GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `43 passed in 30.03s`.
- W2 code-quality GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py` passed with `42 passed in 18.38s`.
- W2 code-quality regression GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `43 passed in 31.22s`.
- W2 coordinator final GREEN: `docker run ... pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py` passed with `42 passed in 18.69s`.
- W2 coordinator final regression GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_api_contracts.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `43 passed in 30.33s`.
- W2 final review: spec reviewer returned `SPEC_PASS`; code-quality reviewer returned `QUALITY_PASS`.
- W3 first targeted GREEN: `docker run ... pytest -q tests/test_capability_acceptance.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv` passed with `17 passed in 9.42s`.
- W3 first broad GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_worker_runtime.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `73 passed in 44.49s`.
- W3 spec review initially returned `SPEC_FAIL` for same-tenant private Memory
  leakage through chat/session context.
- W3 privacy-fix targeted GREEN: `docker run ... pytest -q tests/test_conversation_memory_context.py tests/test_capability_acceptance.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv` passed with `18 passed in 10.86s`.
- W3 privacy-fix broad GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_worker_runtime.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `73 passed in 45.36s`.
- W3 spec re-review returned `SPEC_PASS`.
- W3 quality review initially returned `QUALITY_FAIL` for concurrent candidate
  acceptance not being exactly-once.
- W3 exactly-once targeted GREEN: `docker run ... pytest -q tests/test_capability_acceptance.py tests/test_conversation_memory_context.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py -vv` passed with `19 passed in 12.09s`.
- W3 exactly-once broad GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_worker_runtime.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `73 passed in 44.41s`.
- W3 final diff hygiene: `git diff --check` returned no whitespace errors,
  only Git CRLF conversion warnings.
- W3 final review: spec reviewer returned `SPEC_PASS`; code-quality reviewer
  returned `QUALITY_PASS`.
- W4 first targeted GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv` passed with `36 passed in 19.62s`.
- W4 broad W1-W4 regression GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_conversation_memory_context.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `81 passed in 47.62s`.
- W4 full backend verification requires `APP_ENV=test`, `CHAINLESS_TESTING=1`,
  and `SANDBOX_IMAGE=chainless-sandbox:latest`; without those env vars the
  full suite fails at the test-environment guard and sandbox-proxy import.
- W4 full backend GREEN after correct env: `docker run ... pytest -q` passed
  with `410 passed, 4 skipped, 1 warning in 136.12s`.
- W4 spec review initially returned `SPEC_FAIL` because Workers were not
  actually callable from normal chat and fallback was not event-transparent.
- W4 spec-fix reviewer returned `SPEC_PASS`.
- W4 first quality review returned `QUALITY_FAIL` because live Worker replay
  used the DB-bounded trace and could drop terminal events.
- W4 terminal-trace fix targeted GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv` passed with `38 passed in 21.87s`.
- W4 terminal-trace full backend GREEN: `docker run ... pytest -q` passed with
  `412 passed, 4 skipped, 1 warning in 138.74s`.
- W4 second quality review returned `QUALITY_FAIL` because
  `failed_fallback_failed` could be masked by an earlier Worker `error`/`done`
  terminal pair.
- W4 exact final-status regression GREEN: `docker run ... pytest -q tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done -vv` passed with `1 passed in 1.05s`.
- W4 final targeted GREEN: `docker run ... pytest -q tests/test_worker_runtime.py tests/test_sse_contract.py tests/test_agent_runtime_limits.py -vv` passed with `39 passed in 19.79s`.
- W4 final broad W1-W4 regression GREEN: `docker run ... pytest -q tests/test_api_contracts.py tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_conversation_memory_context.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_tenant_isolation.py tests/test_mcp_transports.py` passed with `81 passed in 44.09s`.
- W4 final full backend GREEN: `docker run ... pytest -q` passed with
  `413 passed, 4 skipped, 1 warning in 127.65s`.
- W4 final diff hygiene: `git diff --check` returned no whitespace errors,
  only Git CRLF conversion warnings.
- W4 final independent review results: spec reviewer returned `SPEC_PASS`;
  code-quality re-review returned `QUALITY_PASS`.
- W5 initial RED: `docker run ... pytest -q tests/test_capability_planning.py`
  failed with `ImportError: cannot import name 'render_capability_context'`.
- W5 first GREEN: `docker run ... pytest -q tests/test_capability_planning.py -vv`
  passed with `3 passed`.
- W5 first targeted regression GREEN:
  `docker run ... pytest -q tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py -vv`
  passed with `30 passed`.
- W5 first broad regression GREEN:
  `docker run ... pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py -vv`
  passed with `87 passed`.
- W5 first full backend GREEN: `docker run ... pytest -q` passed with
  `416 passed, 4 skipped, 1 warning`.
- W5 read-only review returned `Ready to merge: With fixes`; findings were
  tenant-level Memory entering planning, overly broad Skill visibility, and raw
  current request rendered into system prompt without explicit untrusted-data
  labeling.
- W5 review-fix RED:
  `docker run ... pytest -q tests/test_capability_planning.py -vv` failed with
  `3 failed` against the newly added reviewer-gap assertions.
- W5 review-fix targeted GREEN:
  `docker run ... pytest -q tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py`
  passed with `30 passed`.
- W5 review-fix broad GREEN:
  `docker run ... pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py`
  passed with `87 passed`.
- W5 final full backend GREEN: `docker run ... pytest -q` passed with
  `416 passed, 4 skipped, 1 warning`.
- W6 initial RED: `docker run ... pytest -q tests/test_capability_policy_hooks.py -vv`
  failed with `ModuleNotFoundError: No module named 'app.core.capabilities.hooks'`.
- W6 confirmation-context targeted GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py::test_worker_confirmation_context_records_risk_without_secrets -vv`
  passed with `1 passed`.
- W6 policy/hooks targeted GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py -vv` passed
  with `5 passed`.
- W6 plan-required GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py`
  passed with `15 passed`.
- W6 W1-W6 broad regression GREEN:
  `docker run ... pytest -q tests/test_capability_candidates.py tests/test_capability_acceptance.py tests/test_worker_runtime.py tests/test_capability_planning.py tests/test_capability_policy_hooks.py tests/test_memory_source_contract.py tests/test_skill_trigger_matching.py tests/test_sse_contract.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py`
  passed with `102 passed`.
- W6 fallback-audit RED:
  `docker run ... pytest -q tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done -vv`
  failed with stale `WorkerRun.error_code` values `WORKER_RUNTIME_ERROR` and
  `TOOL_NOT_AUTHORIZED`.
- W6 fallback-audit GREEN:
  `docker run ... pytest -q tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done -vv`
  passed with `2 passed`.
- W6 final targeted GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
  passed with `17 passed`.
- W6 final full backend GREEN: `docker run ... pytest -q` passed with
  `421 passed, 4 skipped, 1 warning`.
- W6 stream-service policy-boundary check:
  `Select-String -Path backend\app\services\conversation_stream_service.py -Pattern 'capabilities\.policy|evaluate_worker_policy|require_worker_tool_policy|unpack_confirmation_args'`
  returned no matches after adding `app.core.capabilities.orchestration`.
- W6 post-facade targeted GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
  passed with `17 passed`.
- W6 post-facade full backend GREEN: `docker run ... pytest -q` passed with
  `421 passed, 4 skipped, 1 warning`.
- W6 review-fix RED:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py::test_worker_policy_requires_external_delivery_and_destructive_confirmation tests/test_capability_policy_hooks.py::test_empty_worker_allowed_tools_blocks_normal_and_confirmation_resume -vv`
  failed because `definition.external_delivery` returned `allow` and normal
  Worker runtime disallowed tools returned generic `TOOL_NOT_AUTHORIZED`.
- W6 review-fix lifecycle RED:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py::test_worker_failure_hook_records_event_and_improvement_candidate -vv`
  failed because Worker runtime direct improvement candidates did not emit
  `on_capability_candidate_created`.
- W6 review-fix targeted GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py tests/test_worker_runtime.py::test_worker_match_decisions_use_semantics_schema_risk_and_active_state -vv`
  passed with `7 passed`.
- W6 review-fix extended GREEN:
  `docker run ... pytest -q tests/test_capability_policy_hooks.py tests/test_worker_runtime.py tests/test_audit.py tests/test_tool_cancellation.py tests/test_proactive_authorization.py tests/test_sse_contract.py::test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error tests/test_sse_contract.py::test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
  passed with `36 passed`.
- W6 review-fix final full backend GREEN: `docker run ... pytest -q` passed
  with `422 passed, 4 skipped, 1 warning`.
- W6 committed locally as `2ef7ef5 feat: add capability policy hooks`.
- W7 implementation added frontend API methods, a dedicated capability store,
  SSE parsing for `capability_candidate` / `worker_notice`, a right-panel
  Inbox tab, candidate/Worker cards, and Settings sections for Capabilities and
  Workers without changing global/sidebar/chat-scroll styling.
- W7 compose verification RED:
  `docker compose run --rm frontend sh -lc "npm run lint && npm run build"`
  failed before lint/build because the worktree compose project tried to create
  fixed-name containers such as `chainless-db` while the main local Docker
  stack was already running.
- W7 frontend Docker verification GREEN:
  `docker run --rm -e NEXT_PUBLIC_API_URL='' -v 'C:\Users\11367\.config\aegis\worktrees\Chainless\codex-v2-capability-layer\frontend\src:/app/src' chainless-frontend-test:latest sh -lc "npm run lint && npm run build"`
  passed; output included `eslint` success and Next `Compiled successfully`.

Blocked-on:
- none.

Next step:
- Complete W7 review/stop-condition check. Do not commit W7 unless the user
  explicitly asks.

## ResumeStateHint

Resume by reading this file, `10-intent.md`, and the V2 execution plan.
Current active workstream is W7 review/closure; W1, W2, W3, W4, W5, and W6 are
closed with fresh Docker evidence. W5 has been committed and pushed; W6 has
been committed locally but not pushed.

## DriftCheckDraft

- Scope: W7 aligned with the frontend capability-management packet; it exposes
  already-built backend contracts through thin client/store/UI seams without
  changing the Chainless visual system.
- Compatibility: chat streaming still flows through `chat-store`; capability
  management lives in `capability-store`, and chat only records/forwards SSE
  candidate and Worker notice events.
- New owners: W7 added `frontend/src/stores/capability-store.ts` as the
  frontend owner for candidates, Workers, Worker runs, versions, and feedback.
- Constraint track: no global CSS, sidebar, chat scroll, or existing layout
  feel was changed. Browser screenshot/DOM evidence is still required in the
  later QA workstream before claiming visual no-regression.
- Runtime track: worktree compose frontend verification conflicts with the
  already-running main local compose stack because services use fixed container
  names; use `docker run` with the frontend test image for worktree-only
  lint/build.
- Decision: W7 implementation is Docker lint/build verified and ready for
  review/closure, but W7 is not committed.
