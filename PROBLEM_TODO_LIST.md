# Problem Todo List

Last updated: 2026-06-17

Purpose: track confirmed issues, suspected issues, and spec/plan verification gaps before and during QA.

## W1 capability layer closure findings (2026-06-17)

- [x] MCP stdio registration could return an empty response body despite a
  `201` JSON response contract.
  Scope:
  This is a W1-discovered regression-fix slice, not part of the Capability
  Candidate/Worker skeleton and not an Agent semantics change.
  Root cause:
  `MCPToolClient` kept a long-lived `stdio_client` context opened inside a
  request task. Its AnyIO task group/cancel scope could later be finalized from
  a different task, corrupting the Starlette response stream.
  Resolution:
  stdio discovery and tool calls now open short-lived stdio contexts and
  sessions in the same task that closes them; HTTP/SSE transports remain
  persistent.
  Evidence:
  `tests/test_api_contracts.py::test_tools_admin_can_register_test_and_delete_mcp_server`
  passed, and `tests/test_mcp_transports.py` passed.

- [x] Worker rollback could bypass the normal activation request/token gate.
  Resolution:
  rollback now requires a prior activation request and matching activation
  token, then records confirmation evidence, confirming user, timestamp, and
  rollback reason before switching the active version.
  Evidence:
  W1 targeted tests assert rollback without evidence, without a request token,
  and with a wrong token are rejected; rollback with the requested token passes.

- [x] Worker activation tokens were not bound to the requested WorkerVersion.
  Resolution:
  Workers now persist `activation_requested_version_id` alongside the token.
  Normal activation and rollback require both token match and requested version
  match, then clear both fields after success.
  Evidence:
  W1 targeted tests assert a token issued for v1 cannot activate v2 and cannot
  rollback to v2.

- [x] App JSON bounds could pass while PostgreSQL `jsonb::text` checks failed.
  Resolution:
  app validation now uses a conservative byte limit below the DB check, and
  Worker public write paths translate residual bounds/status check failures to
  `422 VALIDATION_ERROR`.
  Evidence:
  W1 targeted tests cover a many-key public Worker create payload that now
  returns 422 before persistence instead of a 500.

- [x] Capability-layer downgrade could fail late after scoped Skill duplicates.
  Resolution:
  migration `0008` now preflights duplicate `(tenant_id, name)` Skill rows and
  raises a clear `RuntimeError` before dropping `scope`/`user_id` or restoring
  `uq_skills_tenant_name`.
  Evidence:
  W1 targeted tests assert the migration contains the duplicate Skill-name
  preflight and explicit rollback failure message.

- [x] Capability-layer JSON/error metadata lacked explicit bounds.
  Resolution:
  write paths now validate JSON byte size/depth through a small shared helper,
  analysis-job error messages are truncated to the bounded durable size, and
  database checks bound JSON/error text storage.
  Evidence:
  W1 targeted tests cover oversized candidate evidence, deeply nested analysis
  job payloads, deeply nested Worker trigger metadata, and truncated analysis
  job error messages.

- [x] Capability and Worker durable status/type fields were unconstrained.
  Resolution:
  model `CheckConstraint`s and migration `0009` now constrain Candidate type,
  Candidate status, analysis job status, Worker status, WorkerVersion status,
  and WorkerRun status.
  Evidence:
  W1 targeted tests assert invalid durable Candidate/Job/Worker/Version/Run
  states are rejected by PostgreSQL.

- [x] Candidate retrieval helper exposed unaccepted candidates.
  Resolution:
  `ACTIVE_RETRIEVAL_STATUSES` is now limited to `accepted` and
  `edited_accepted`.
  Evidence:
  W1 targeted tests assert `new`, `seen`, `snoozed`, `dismissed`, `merged`,
  `archived`, and `muted_pattern` candidates are not returned, while accepted
  states are returned only for the same tenant/user.

- [x] Capability analysis outbox enqueue/claim was not atomic enough for
  PostgreSQL concurrency.
  Resolution:
  enqueue now uses a single PostgreSQL upsert returning the durable row id,
  claim uses `FOR UPDATE SKIP LOCKED`, and `skipped_duplicate` has an explicit
  lifecycle helper.
  Evidence:
  W1 targeted tests now include concurrent enqueue/claim and skipped-duplicate
  coverage; `tests/test_capability_candidates.py tests/test_worker_runtime.py`
  passed.

- [x] Private Skill direct get/update/delete could leak across same-tenant
  users by id.
  Resolution:
  direct Skill lookup now scopes to the current user's private rows plus
  shared/legacy rows only.
  Evidence:
  W1 targeted tests assert same-tenant users cannot get, update, or delete
  another user's private Skill by id.

- [x] Worker rollback could reactivate a prior version without confirmation
  evidence.
  Resolution:
  rollback now requires confirmation evidence and records the confirming user,
  timestamp, evidence, and reason while reactivating the verified prior version.
  Evidence:
  W1 targeted tests assert rollback without evidence is rejected and rollback
  with evidence records the audit fields.

## V2 W2 capability generation closure findings (2026-06-17)

- [x] Useful chat runs needed a noise-controlled candidate generation path.
  Resolution:
  added a deterministic rule gate for remember/next-time/always text, tool-chain,
  artifact, user-correction, and fallback useful-run signals before any analyzer
  spend. Pure greeting chat remains below the analysis threshold.
  Evidence:
  W2 rule tests are included in `tests/test_capability_candidates.py`.

- [x] Analyzer output needed strict parsing before durable candidate writes.
  Resolution:
  added strict JSON-only analyzer parsing for inactive Memory, Skill, and Worker
  candidates, with allowed candidate types, confidence clamping, bounded source
  evidence, and invalid-output fallback to no candidates.
  Evidence:
  fake-gateway analyzer tests cover all three candidate types plus invalid JSON.

- [x] Eligible stream-tail analysis could be lost on timeout.
  Resolution:
  eligible runs are durably enqueued before best-effort stream-tail analysis;
  timeout increments a bounded runtime metric and leaves the job pending for the
  ARQ-compatible processor. Analyzer failures persist bounded error metadata.
  Evidence:
  W2 tests cover timeout, pending background completion, idempotent duplicate
  processing, and failure metrics.

- [x] Candidate generation needed to avoid inbox spam and accidental activation.
  Resolution:
  candidate persistence dedupes by tenant/user/type/dedupe key, updates active
  inbox candidates instead of creating duplicates, suppresses dismissed/muted
  repeats, and emits only a lightweight `capability_candidate` SSE hint with
  `active: false`.
  Evidence:
  Docker verification passed:
  `pytest -q tests/test_capability_candidates.py tests/test_sse_contract.py`
  returned `37 passed in 15.33s`.

- [x] W2 spec review found `capability_candidate` was emitted outside the
  canonical SSE event-name contract.
  Resolution:
  added `capability_candidate` to `SSEEventName` and a focused SSE helper
  assertion for the inactive candidate hint frame.
  Evidence:
  W2 review-fix Docker verification returned `38 passed in 16.37s`; broad
  regression returned `43 passed in 30.03s`.

- [x] W2 muted-pattern suppression only checked exact dedupe matches.
  Resolution:
  before creating or hinting a new analyzed candidate, the capability service
  now scans same tenant/user/type `muted_pattern` rows and applies the stored
  pattern against the new dedupe key/title. Exact dismissed dedupe matches
  still suppress exact repeats.
  Evidence:
  `test_broad_muted_pattern_suppresses_new_matching_candidate_and_hint` proves
  a broad mute pattern suppresses a new matching candidate and emits no hint.

- [x] W2 background analysis jobs could remain `running` forever.
  Resolution:
  pending analysis claim now also reclaims stale `running` jobs whose claim
  lease has expired, and background analyzer execution is bounded by
  `asyncio.wait_for`; hung background analyzers mark the job failed with
  bounded `ANALYZER_TIMEOUT` metadata and metrics.
  Evidence:
  `test_stale_running_analysis_job_is_reclaimed` and
  `test_background_hung_analyzer_times_out_and_marks_job_failed` cover lease
  reclaim and bounded hung-gateway behavior.

- [x] W2 future-snoozed candidates could be updated and hinted early.
  Resolution:
  candidate persistence now suppresses exact dedupe repeats while
  `snoozed_until` is still in the future, and only reopens an expired snooze
  back to `new` when updating.
  Evidence:
  `test_future_snoozed_candidate_suppresses_update_and_hint` proves the
  candidate body/title stay unchanged and no hint is emitted before expiry.

- [x] W2 dedupe lookup could select a latest merged row and create spam.
  Resolution:
  exact dedupe lookup now follows `merge_target_candidate_id` and otherwise
  resolves by status priority so existing inbox/accepted/suppressed rows are
  handled before creating a new candidate.
  Evidence:
  `test_merged_latest_dedupe_repeat_updates_merge_target_without_spam` proves a
  repeat updates the merge target and does not create a third duplicate row.

## V2 W3 capability acceptance closure findings (2026-06-17)

- [x] Capability Candidate acceptance only changed candidate status instead of
  creating real reusable capability objects.
  Resolution:
  `/api/v1/capability-candidates/{id}/accept` now creates private Memory rows,
  private passive Skill rows, or inactive Worker draft/version rows. Worker
  improvement candidates create a new draft version instead of overwriting an
  existing version.
  Evidence:
  `tests/test_capability_acceptance.py` covers Memory, Skill, Worker draft,
  Worker improvement, edited proposals, owner-only candidate access, and
  inactive-candidate rejection.

- [x] Accepted private Memory and Skill needed explicit same-tenant user
  isolation.
  Resolution:
  Memory list/search/merge and chat session context now retrieve current-user
  private Memory plus tenant-level shared rows only. Skill list/match/direct
  access now returns current-user private Skills plus explicit `shared` or
  `shared_legacy` rows.
  Evidence:
  W3 targeted tests cover accepted private Memory list/search/merge isolation,
  accepted private Skill match isolation, and explicit legacy Skill visibility.

- [x] Accepted private Memory could still leak into another same-tenant user's
  chat context.
  Evidence:
  spec review found `conversations.py` built session context with only
  `tenant_id`, so `get_memories_for_session()` could read another user's
  private accepted Memory.
  Resolution:
  chat context now passes `current_user["user_id"]` through
  `_build_session_context()` into persistent memory retrieval.
  Verification:
  `tests/test_conversation_memory_context.py` exercises the real
  `/conversations/{id}/chat` SSE path and proves the other user's private
  accepted Memory is not injected.

- [x] Concurrent candidate acceptance could create duplicate target resources.
  Evidence:
  code-quality review found target Memory/Skill/Worker creation happened before
  the candidate status transition without a row lock or conditional update.
  Resolution:
  candidate acceptance now loads the scoped candidate row with
  `SELECT ... FOR UPDATE` before checking status and creating target resources.
  The losing concurrent accept sees the updated status and returns
  `409 CAPABILITY_CANDIDATE_NOT_ACCEPTABLE`.
  Verification:
  `test_concurrent_memory_candidate_acceptance_is_exactly_once` proves one
  success, one conflict, and exactly one target Memory row.

- [x] Memory acceptance side effects could be enqueued before the outer
  acceptance transaction committed.
  Resolution:
  `create_memory(commit=False, write_source=False)` no longer enqueues an
  embedding job before the acceptance transaction commits; acceptance enqueues
  embedding and writes the memory source after the DB commit.
  Evidence:
  W3 quality re-review returned `QUALITY_PASS`.

- [ ] Accepted Memory source-file write is post-commit and synchronous.
  Risk:
  if the filesystem write fails after DB acceptance is durable, the request can
  surface an error even though acceptance succeeded in the database.
  Recommended future fix:
  move source-file write into a retryable/logged outbox path or catch/log with
  a repair task.
  Status:
  non-blocking W3 residual risk; DB acceptance correctness is preserved.

- [ ] Memory acceptance can hold the candidate row lock while inline embedding
  runs.
  Risk:
  slow embedding can extend lock wait time during concurrent accepts.
  Recommended future fix:
  prefer async embedding after commit for acceptance-created Memory.
  Status:
  non-blocking W3 residual risk; exactly-once correctness is preserved.

## Workstream 12 file task closure findings (2026-06-15)

- [x] Uploaded files were visible in artifact storage but not reliably readable
  by the agent's file tools.
  Resolution:
  artifacts remain the durable source of truth, and chat runs now materialize
  sent attachments into a clean per-run workspace before agent execution.
  `file_read`, `file_write`, and `file_list` receive that run workspace as
  their tool root, so stale global `/workspace` files are not visible in chat
  runs.
  Evidence:
  `tests/test_file_task_closure.py` covers uploaded-file materialization,
  `file_read` through the tool loop, stale workspace isolation, and
  fail-closed materialization errors; full backend returned
  `346 passed, 4 skipped`.

- [x] Sent attachments were not explicit durable UI/message objects.
  Resolution:
  conversation messages now serialize `attachments`, optimistic user messages
  retain selected attachment metadata, and sent message bubbles render existing
  attachment chips in a read-only `sent` state without changing the visual
  style.
  Evidence:
  W12 browser QA `file-task-closure` passed
  `upload-state-available` and `sent-message-attachment-visible`.

- [x] Generated artifacts could be previewed but not downloaded.
  Resolution:
  added `GET /api/v1/artifacts/{artifact_id}/download`, token-safe frontend
  download handling, and a Files panel download action using the existing
  button style.
  Evidence:
  W12 browser QA passed `artifact-download-bytes-match`; backend download tests
  prove tenant isolation and safe ASCII/UTF-8 `Content-Disposition` handling.

- [x] Agent could continue normal reasoning when a required attachment failed
  to materialize.
  Resolution:
  chat streaming now emits a typed `ATTACHMENT_MATERIALIZATION_FAILED` SSE
  error before calling the LLM, asking the user to retry/re-upload/wait instead
  of falling back to stale files or model inference.
  Evidence:
  `test_attachment_materialization_failure_fails_closed_before_llm_call`
  passed and asserts the mock gateway call count stays zero.

- [x] Settings page sidebar could show no conversations when opened directly,
  so clicking an existing conversation from `/settings` was not a reliable
  route back to `/chat`.
  Resolution:
  `/settings` now loads conversations through the same chat-store owner used by
  `/chat`, and Sidebar selection still performs the existing logic-only push to
  `/chat`.
  Evidence:
  first W12 browser QA failed at `settings-sidebar-navigates-chat`; after the
  fix the rerun returned `ok: true` with that step passing.

## Workstream 11 final spec-complete QA findings (2026-06-15)

- [x] Nginx could keep a stale backend upstream IP after backend rebuild and return `502`.
  Resolution:
  [nginx/conf.d/chainless.conf](E:/Chainless/nginx/conf.d/chainless.conf)
  now uses Docker DNS resolver variables for frontend/backend upstreams, so a
  backend recreate no longer requires an Nginx restart to route `/api/v1/*`.
  Evidence:
  after fresh `docker-compose up -d --build`, Nginx was left running, then
  `curl.exe -fsS http://127.0.0.1/api/v1/health` and
  `docker-compose exec -T nginx wget -qO- http://backend:8000/api/v1/health`
  both returned `{"status":"ok"}`.

- [x] Final spec-complete browser QA needed a real provider path without
  leaving QA providers behind.
  Resolution:
  `scripts/qa/spec-complete.cjs` and `scripts/windows-browser-qa.cjs` create
  disposable OpenAI-compatible mock providers through the same UI/API provider
  path, make them default only for the test, then delete them in `finally`.
  Evidence:
  Windows Chrome `spec-complete` at
  `.gstack/qa-reports/local/spec-complete-2026-06-15T06-13-38-067Z`
  returned `ok: true`, zero console/page/request/429 errors, and
  cleanup-verification `ok: true`.

- [x] HackerNews performance probe initially risked parsing stale HN markup.
  Resolution:
  `backend/scripts/performance_probe.py` parses current HN `athing submission`
  rows and keeps the sandbox network-none boundary by fetching HN in the
  backend, then parsing the captured top-10 payload in the sandbox.
  Evidence:
  W11 HN probe ran one warmup and five measured Code-as-Action executions; max
  observed latency was `757.6ms`, p50 was `707.61ms`, every run returned
  `count: 10`, and every run had sandbox `allocated/completed/deleted`
  evidence.

- [x] Original Fibonacci Code-as-Action gate was not satisfied by prior `42`
  demos.
  Resolution:
  W11 added `backend/scripts/performance_probe.py --scenario fibonacci`.
  Evidence:
  the final W11 run returned exact stdout `55` with sandbox phases
  `allocated`, `completed`, and `deleted`.

- [x] Backup/restore proof was only partial before W11.
  Resolution:
  W11 added `backend/scripts/restore_drill.py`, guarded to the isolated test
  database.
  Evidence:
  backup produced `/backups/chainless-20260615-061030.sql` (212K);
  restore drill restored into `chainless_restore_drill_989008f95c3b`, verified
  default tenant/admin/agent and fixture rows, then dropped the temporary
  database and removed the dump/source fixture.

- [x] Live GLM-4.5 Air proof cannot be claimed in the current local Docker
  environment.
  Evidence:
  `GLM_API_KEY_SET|False`, `default_providers|0`, and `all_providers|0`.
  Resolution:
  W11 verifies the configurable OpenAI-compatible provider runtime path with
  disposable mock providers and records live GLM as an external-credential proof
  boundary instead of falsely claiming a real GLM API call.

- [x] W11 cleanup must prove no QA data remains.
  Evidence:
  Postgres QA-prefix residue counts returned zero for tenant, user, provider,
  agent, conversation, message, memory, skill, artifact, tool configuration,
  channel configuration, and confirmation tables. Redis scan showed no
  `ws10`, `w5-final`, `w6-artifacts`, `w7-rich`, or `w11-spec` QA-prefix keys.

## Workstream 1 authority findings captured (2026-06-05)

These checked items record individual W1 authority tasks. Workstream closure
remains controlled by the active execution-plan checkpoint, evidence, and
two-stage review.

- [x] Reconciled the current-truth matrix with verified historical Workstreams
  8-10 evidence.
- [x] Made
  `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
  the only active remaining-work tracker.
- [x] Recorded compose-managed Nginx, dynamic `spawn_sub_agent`,
  settings/administration, real artifact/diff flow, and passive skill
  metadata/trigger matching as V1 `ship` work.
- [x] Preserved MinIO and Skill Precipitation as V2 and accepted the current
  Next.js 16 / React 19 / PostgreSQL 16 runtime without downgrade.
- [x] Captured floating unresolved V1 claims in the runtime gap matrix and
  mapped each to W2-W11.
- [x] Added explicit W8 owners for complexity routing, short-term conversation
  context, and MCP idle/reconnect/failure/risk-default behavior.
- [x] Added the original context-banner requirement to W5 instead of silently
  dropping the optional product-visible context summary.
- [x] Expanded the authority sweep to cover sandbox pool lifecycle, main-agent
  budget/circuit breaker, eval CI, proactive event triggers, instruction
  hot-reload, and full Preview/Terminal security/rendering behavior.
- [x] Expanded the authority sweep to cover persistent-memory file/index
  contracts, MCP HTTP/SSE, tool cancellation/rejection alternatives, delayed
  proactive tasks, full frontend interactions, AppArmor/network whitelist, and
  explicit health/rate-limit baselines.
- [x] Preserved the original exact verification gates for GLM-4.5 Air,
  Fibonacci `55`, filesystem MCP, five-type memory/cosine distance, OpenAI tool
  schemas, and happy/error/edge tests.
- [x] Assigned every remaining original P1-P6 verification gate and explicit
  `Verify:` step to a final W11 one-to-one evidence ledger.
- [x] Closed W1 by local assertion gate after sub-agent re-review was blocked
  by platform usage limits; no sub-agent approval is claimed for this fallback.

## User-reported issues

- [x] Public deployment hangs on `Loading`, while opening the app on `localhost` works.
  Evidence:
  `frontend/src/lib/api.ts` falls back to `http://localhost:8000` when `NEXT_PUBLIC_API_URL` is empty.
  `docker-compose.yml` on the server currently sets `NEXT_PUBLIC_API_URL: ""`.
  Likely effect:
  when a public user opens the frontend, their browser calls its own `localhost:8000`, not the server backend.
  Resolution:
  frontend API base URL now derives from the active browser host for public access, and the remote frontend now runs a production `next build` + `next start` image instead of dev mode.

- [x] Agent capability does not yet match the "general agent" claim.
  Example:
  asking for today's weather in Wuxi fails instead of using a robust weather-capable tool path.
  Likely causes:
  weather is not backed by a dedicated provider, web fetch/search strategy is weak, and some sites require JS or valid API keys.
  Resolution:
  a dedicated builtin `weather_get` tool now queries `wttr.in` and the live browser regression for `帮我查一下今天无锡的天气` now returns a concrete weather answer.

- [x] Frontend likely has additional usability and integration defects.
  Resolution:
  the public frontend now passes the main smoke and interaction regressions listed below: root redirect, login submit, unauthenticated `/chat` redirect, conversation creation, and first-message send/response.

## Confirmed issues found during investigation

- [x] Public homepage/root route is stuck on `Loading...`.
  Evidence:
  local browser QA run `2026-06-03T08-16-01-152Z` against `http://118.196.142.31:3000/` stayed on a black screen with `Loading...` still visible after 12 seconds.
  Artifacts:
  `.gstack/qa-reports/local/2026-06-03T08-16-01-152Z/page.png`
  `.gstack/qa-reports/local/2026-06-03T08-16-01-152Z/report.json`
  `.gstack/qa-reports/local/2026-06-03T08-16-01-152Z/report.md`
  Resolution:
  smoke run `2026-06-03T08-43-07-141Z` now redirects `/` to `/login` with `Loading` disappearing successfully.

- [x] Public frontend is serving dev-mode HMR websocket errors in the browser.
  Evidence:
  smoke runs for `/`, `/login`, and `/chat` all show `_next/webpack-hmr` websocket handshake failures in console on the public deployment.
  Likely cause:
  the public frontend is running `next dev` or otherwise exposing dev HMR behavior instead of a production build.
  Resolution:
  `frontend/Dockerfile` now builds production assets and serves them with `npm run start`; follow-up smoke runs no longer report HMR console errors.

- [x] Login form submit does not perform an auth API request and leaves the user on `/login?`.
  Evidence:
  browser-driven login test filled `default / admin / admin123`, clicked `Sign In`, and remained on `http://118.196.142.31:3000/login?`.
  Captured network result:
  no `/api/v1/auth/login` request was emitted from the browser, and no token was stored in `localStorage`.
  Artifact:
  `.gstack/qa-reports/local/login-after.png`
  Resolution:
  live regression now shows `/api/v1/auth/login` firing, token persistence succeeding, and browser navigation landing on `/chat`.
  Root cause:
  the shared `Button` and `Input` primitives looked correct visually but did not reliably preserve submit/value behavior in the deployed app. They now use native `<button>` / `<input>` elements with the same existing classes, so the style stays intact while the form behavior is reliable.

- [x] Unauthenticated users can open the `/chat` UI directly.
  Evidence:
  browser smoke run against `http://118.196.142.31:3000/chat` showed the full chat shell, `New Chat`, composer area, and `Logout` control without a valid login flow completing first.
  Artifact:
  `.gstack/qa-reports/local/2026-06-03T08-16-01-220Z/page.png`
  Resolution:
  smoke run `2026-06-03T08-43-07-156Z` now redirects unauthenticated `/chat` access to `/login`.

- [x] Chat UI actions do not create a conversation or send a message in the tested public flow.
  Evidence:
  unauthenticated browser interaction could click `New Chat`, type into the composer, and click/send attempts produced no `/api/v1/conversations` or chat API requests.
  The screen remained on `No conversation selected`.
  Artifact:
  `.gstack/qa-reports/local/chat-unauth-flow.png`
  Resolution:
  authenticated browser regression now creates a conversation, sends the first message, and receives an assistant response over SSE.

- [x] Frontend/backend conversation API contract mismatch.
  Evidence:
  `frontend/src/stores/chat-store.ts` expects `data.conversations` and `data.conversation`, and fetches `/api/v1/conversations/{id}/messages`.
  `backend/app/api/v1/conversations.py` returns paginated `items` and does not provide a `/messages` endpoint.
  Likely effect:
  conversation list and message history loading are inconsistent or broken.
  Resolution:
  frontend store now uses the paginated `items` shape, reads conversation details from `GET /api/v1/conversations/{id}`, and the backend exposes that endpoint.

- [x] Public frontend API base URL is misconfigured for deployment.
  Evidence:
  `frontend/src/lib/api.ts` uses `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"`.
  Remote `docker-compose.yml` sets `NEXT_PUBLIC_API_URL: ""`.
  Likely effect:
  browser requests point to the viewer's own machine in public access scenarios.
  Resolution:
  frontend now derives `http(s)://<current-host>:8000` automatically for public access and the production deployment is built with an empty `NEXT_PUBLIC_API_URL`.

- [x] Default GLM model can stream only reasoning and leave visible assistant output empty for too long.
  Evidence:
  direct provider tests showed `glm-4.5-air` consuming completion tokens on `reasoning_content` while returning empty `content`.
  Resolution:
  backend default LLM model now uses `glm-4-flash`, and the login/chat browser regression now receives a visible assistant response within the test window.

- [x] Weather queries do not use a dedicated data path.
  Evidence:
  browser regression for `帮我查一下今天无锡的天气` returned only a vague suggestion instead of concrete weather data.
  Resolution:
  backend now exposes a builtin `weather_get` tool backed by `wttr.in`, and the live browser regression returns temperature, conditions, and rain chance for Wuxi.

- [x] Memory embedding path is not aligned with the configured LLM provider.
  Evidence:
  backend logs show embedding requests fail with `400` and `模型不存在，请检查模型代码。`
  Current default `embedding_model` is `text-embedding-3-small` while the provider base is GLM-compatible.
  Likely effect:
  semantic memory recall from the spec is not actually working.
  Resolution:
  default embedding config now uses `embedding-3`, and the backend falls back to local deterministic embeddings whenever provider embeddings are unavailable or out of quota.
  Verification:
  live checks covered `/api/v1/memories/`, `/api/v1/memories/search`, `/api/v1/memories/merge`, direct database inspection of non-null `embedding`, and a browser chat where the assistant recalled the stored functional-programming preference.

- [x] Frontend right-side panel was only a toggle button, not a real preview surface.
  Resolution:
  the chat page now mounts a real owner-aligned right panel with `Preview`, `Terminal`, and `Files` tabs, plus inline tool activity cards and destructive confirmation cards, without changing the established frontend style.
  Verification:
  browser artifacts:
  `.gstack/qa-reports/local/workstream45-2026-06-03T14-14-04-815Z/02-weather-complete.png`
  `.gstack/qa-reports/local/workstream45-confirm-final-2026-06-03T14-23-53-293Z/04-approved.png`
  Follow-up resolution:
  Workstream 6 retired the placeholder-only `Diff` behavior. Files and Diff now
  render persisted real artifacts and unified diffs, and the final artifact
  browser QA passed at
  `.gstack/qa-reports/local/artifacts-2026-06-14T14-43-26-195Z/report.json`.

- [x] Destructive confirmation approve flow was broken.
  Evidence:
  browser verification initially showed `Approve` returning `Error: name 'execute_code_as_action' is not defined`, and `shell_exec` was being executed as Python instead of as a shell command.
  Resolution:
  `backend/app/api/v1/conversations.py`, `backend/app/core/tools/builtin/sandbox.py`, and `backend/app/core/agent/engine.py` were updated so:
  - approval executes the correct tool path
  - resumed context includes the original `assistant.tool_calls` frame
  - `shell_exec` runs through a sandboxed subprocess wrapper
  - tool events carry stable ids for proper row updates
  Verification:
  browser artifact:
  `.gstack/qa-reports/local/workstream45-confirm-final-2026-06-03T14-23-53-293Z/04-approved.png`
  Quick regression:
  one final browser probe now shows `countRunning = 0`, `countCompleted = 1`, and a real `date` output after approval.

- [x] QA readiness on this local Codex session needed a Windows-compatible browser path.
  Evidence:
  local machine has Chrome, Edge, and Node.
  However, this session does not currently expose a callable browser QA tool, and the bundled `gstack` `chrome-cdp` helper is macOS-specific.
  Resolution:
  a Windows-local Playwright path now drives Chrome/Edge through the bundled Codex Node runtime.
  Boundary:
  this is a repo-local QA gate, not the exact upstream `gstack /qa` daemon path.

- [x] A Windows-local browser execution path now exists in-repo.
  Files:
  `scripts/windows-browser-qa.ps1`
  `scripts/windows-browser-qa.cjs`
  `docs/windows-local-browser-qa.md`
  Status:
  this enables local Chrome/Edge driven smoke checks and Workstream 10 regression checks with screenshot and console/network error capture using the Codex bundled Node + Playwright runtime.
  Verification:
  Workstream 10 browser gate passed against the remote Docker deployment:
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/report.json`
  Covered:
  auth login, conversation create/rename/archive, chat SSE, tool cards, right panel Files tab, `code_as_action`, destructive confirmation deny, and test conversation cleanup.

## Resolved during investigation

- [x] `sandbox-proxy` orchestration state was split between an exited compose-managed container and a manually started container.
  Fix:
  rebuilt `sandbox-proxy` under `docker-compose` control on the remote server.

- [x] Backend health endpoint reported stale sandbox pool state.
  Fix:
  `backend/app/main.py` and `backend/app/core/sandbox/manager.py` were updated so `/api/v1/system/health` reads live `sandbox-proxy` state.

- [x] Remote `docker-compose` backend rebuilds can land in an exited anonymous container instead of the canonical `chainless-backend`.
  Evidence:
  `docker-compose up -d --build backend` on the remote host repeatedly produced containers like `f86339da6ec0_chainless-backend` or `4e9e4db78d4f_chainless-backend` in `Exit 0`, while the expected `chainless-backend` was not running.
  Fix:
  after rebuild, run `docker-compose rm -f backend` and then `docker-compose up -d backend` to restore the canonical compose-managed container.

## Spec / implementation verification backlog

### Phase 1: Foundation

- [x] Verify auth flow end-to-end from the real frontend UI.
- [x] Verify conversation CRUD against the actual frontend state model.
  Verification:
  local browser regression covered login, create chat, rename chat, archive chat, create another chat, and send the first message on the public deployment.
  Artifacts:
  `.gstack/qa-reports/local/manual-conversation-crud/report.json`
  `.gstack/qa-reports/local/manual-conversation-crud/final.png`
- [x] Verify SSE chat stream behavior in the browser, including error events and completion.

### Phase 2: Agent engine + sandbox

- [x] Verify backend can execute code through `SandboxManager -> sandbox-proxy -> sandbox`.
- [x] Verify chat-triggered `code_as_action` works end-to-end from the UI.
  Verification:
  browser run:
  `.gstack/qa-reports/local/workstream5-final-2026-06-03T14-48-37-456Z/02-code.png`
  shows `code_as_action` completing with visible `42` output in chat and the right-side terminal panel path.
- [x] Verify destructive tool confirmation flow works in the UI.
  Verification:
  browser runs covered:
  - confirmation card render
  - deny path
  - approve path with real `shell_exec` output
  - timeout path with automatic rejection after 30 seconds
  Additional evidence:
  `.gstack/qa-reports/local/workstream5-timeout-2026-06-03T14-50-03-949Z/03-timeout.png`
  API history verification confirmed:
  - `pending` tool message is stored before confirmation
  - `approved` stores tool output + assistant summary
  - `timeout` stores a clean timeout tool message without executing the tool

### Phase 3: Tool ecosystem

- [x] Verify builtin tools actually cover core "general agent" tasks.
  Resolution:
  `/api/v1/tools` exposes all 8 v1 builtin tools with risk metadata: `file_read`, `file_write`, `file_list`, `web_search`, `web_fetch`, `weather_get`, `shell_exec`, and `code_as_action`.
  `file_ops` now targets the explicit Docker `/workspace` volume and blocks path traversal outside it.
  `web_search` now returns structured JSON results with `title`, `url`, `snippet`, and `source`.
  Verification:
  remote backend Agent-loop verification covered file tools, web tools, weather, `code_as_action`, and destructive `shell_exec` confirmation routing.
  Browser evidence covered weather, file/search, and fetch tool cards:
  `.gstack/qa-reports/local/workstream6-browser-2026-06-04T02-34-24-773Z/`
  `.gstack/qa-reports/local/workstream6-browser-file-web-2026-06-04T02-36-38-220Z/`
  `.gstack/qa-reports/local/workstream6-browser-web-fetch-2026-06-04T02-41-13-925Z/`
- [x] Verify MCP registration, discovery, invocation, and failure recovery.
  Verification:
  live remote API registered `backend/scripts/mcp_echo_server.py`, discovered `mcp__echo__echo`, called it through `POST /api/v1/tools/echo/test`, listed `mcp_count=1`, and confirmed missing-server failure returns `TOOL_NOT_FOUND`.
- [x] Verify risk classification is visible in tool UI flows.
  Resolution:
  `tool_call_start` now carries `risk`, the frontend stores it on `ToolEvent`, and the existing tool activity row displays it in the status line as `Completed / safe` or `Completed / risky`.
  Browser evidence:
  `.gstack/qa-reports/local/workstream6-2026-06-04T01-50-19-991Z/`
- [x] Verify a weather/task-oriented tool path exists for common assistant questions.

### Phase 4: Memory system

- [x] Verify tag-based memory recall.
  Resolution:
  `get_memories_for_session` now extracts explicit `#tag` and keyword-matched tags, ranks tag matches first, then fills remaining context budget with semantic results.
  Verification:
  remote API proof showed a `#ws7tagonly` task returned `WS7 Tag Memory` first and still included semantic fill.
- [x] Fix and verify semantic embedding recall.
- [x] Verify memory injection behavior does not break chat responses.
  Additional Workstream 7 verification:
  browser chat proved injected memory and layered instructions affected the live assistant response with required citations.
  Browser evidence:
  `.gstack/qa-reports/local/workstream7-browser-memory-2026-06-04T05-05-33-747Z/`

### Phase 5: Eval + channel + scheduler

- [x] Verify `run-eval.py` against the real environment.
  Resolution:
  `backend/scripts/run-eval.py` now supports `--json`, exposes `code_as_action` to the eval agent, records `confirmation_required` safety events, and uses a pass-rate threshold.
  Verification:
  remote Docker command `python scripts/run-eval.py --suite basic --json --min-pass-rate 1.0` passed `10 / 10` with `Error: 0 / 10`.
- [x] Verify proactive task scheduling.
  Resolution:
  `docker-compose.yml` now includes `chainless-worker`, and `backend/app/core/proactive/scheduler.py` now uses a real ARQ worker startup path, minute cron checks, Redis enqueueing, and bounded execution records.
  Verification:
  remote `docker-compose ps` shows `chainless-worker` up, worker logs show `cron:check_scheduled_tasks`, and a `* * * * *` task executed at `2026-06-04T06:06:04Z`.
- [x] Verify Feishu channel delivery.
  Resolution:
  `FeishuChannel` now retries delivery and returns structured delivery evidence; `/channels/feishu/test` remains backward compatible despite the generic `/channels/{channel_id}/test` route.
  Verification:
  remote runtime sent both a Feishu-format test payload and a scheduled proactive payload to a live HTTP webhook receiver, with `delivery.ok=true`, `attempts=1`, and `status_code=200`.
  Note:
  the remote environment did not provide a real Feishu webhook secret, so the runtime path was verified against a live local webhook receiver that captured the exact Feishu interactive-card payload.

### Phase 6: Production polish

- [x] Verify public deployment routing and API base URL behavior.
- [x] Verify loading/error states in the frontend.
  Resolution:
  chat state now exposes `isLoadingConversations` and `error`, sidebar/chat panel render existing-style loading/empty/error states, and the chat page shows a dismissible error strip using the current zinc/red visual language.
- [x] Verify right-panel preview/terminal/files features covered by the current Workstream 10 gate.
  Current status:
  preview, terminal, and files are now live and browser-verified; `Diff` remains an empty-state surface because no verified diff-producing tool flow exists yet.
- [x] Verify rate limiting, health reporting, backup/restore, and operational readiness.
  Current status:
  Workstream 9 backend operational readiness is verified: health covers DB/Redis/worker/sandbox, metrics expose Prometheus-style gauges, rate limiting returns 429 under probe, backup creates a real SQL dump in `/backups`, restore script is present and validates input, and `docker-compose up -d` converges on the remote runtime.
- [x] Verify repeatable Workstream 10 browser regression path.
  Verification:
  `powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://118.196.142.31:3000 -Browser chrome -Headless -Suite workstream10 -TimeoutMs 60000`
  passed with `ok: true` and screenshots saved under:
  `.gstack/qa-reports/local/workstream10-2026-06-04T07-43-11-624Z/`

## Newly confirmed remaining issues

- [x] Workstream 8 originally had no deployable ARQ worker service.
  Evidence:
  remote `docker-compose ps` initially listed only db, redis, backend, frontend, sandbox-proxy, and sandbox.
  Resolution:
  added `chainless-worker` service and verified it starts as `arq app.core.proactive.scheduler.WorkerSettings`.

- [x] Proactive scheduler was scaffold-like and not worker-safe.
  Evidence:
  scheduler depended on FastAPI `app_state`, used non-working ARQ job creation, and lacked execution records.
  Resolution:
  worker startup initializes LLM and sandbox dependencies, cron uses `arq.cron`, due tasks are enqueued through Redis, and recent run records are exposed through `/api/v1/proactive-tasks/runs`.

- [x] Eval suite did not correctly represent current runtime safety/tool behavior.
  Evidence:
  `--json` was unsupported, `code_as_action` was not exposed to the eval agent, the Chinese greeting expected mojibake text, and destructive `shell_exec` confirmation events were counted as failures.
  Resolution:
  eval now records confirmation events, the basic suite expects `weather_get`, `code_as_action`, proper `你好`, and destructive confirmation behavior.

- [x] Feishu compatibility test route was shadowed by the generic dynamic route.
  Evidence:
  `/api/v1/channels/feishu/test` returned `422` because `/{channel_id}/test` matched first.
  Resolution:
  static Feishu compatibility routes are registered before the generic dynamic route.

- [x] Stale proactive test task remained in Redis with no Feishu webhook.
  Evidence:
  Redis key `chainless:proactive:tasks` contained `Summarize today conversations` with empty `channel_config`.
  Resolution:
  removed only that invalid stale task; Redis proactive task registry is now `{}` after Workstream 8 cleanup.

- [x] Deleted proactive tasks could keep running inside an already-started worker.
  Evidence:
  after deleting the Workstream 8 test task, Redis showed `{}`, but worker logs still executed the same task at `06:07` and `06:08`.
  Root cause:
  scheduler used `_tasks.update(await _load_tasks_from_redis())`, so Redis deletions never removed entries from the in-process worker cache.
  Resolution:
  Redis is now treated as the source of truth; scheduler refresh replaces the in-process cache instead of merging it.
  Verification:
  after worker restart, logs at `06:09` and `06:10` showed only `cron:check_scheduled_tasks` and no further execution for the deleted task.

- [x] Backup script failed in the real backend container.
  Evidence:
  remote command `BACKUP_DIR=/tmp/chainless-backup-test ./scripts/backup.sh` failed with `pg_dump: command not found`.
  Root cause:
  backend image did not install PostgreSQL client tools.
  Resolution:
  backend Dockerfile now installs `postgresql-client` using the Tsinghua Debian mirror, and `backup.sh` explicitly checks for `pg_dump`.
  Verification:
  remote `./scripts/backup.sh` produced `/backups/chainless-20260604-064743.sql` and `pg_dump --version` reports PostgreSQL `17.10`.

- [x] Backup script used the wrong DB password in production runtime.
  Evidence:
  remote `.env` has `DB_PASSWORD=change-me`, but backend container originally did not receive `DB_PASSWORD`, so `backup.sh` fell back to `chainless_dev` and failed authentication.
  Resolution:
  `docker-compose.yml` now passes `DB_USER`, `DB_HOST`, `DB_NAME`, and `DB_PASSWORD` into backend and worker.

- [x] Health reporting only covered sandbox state.
  Resolution:
  `GET /api/v1/system/health` now reports DB, Redis, worker heartbeat, and sandbox state with an aggregate `status`.
  Verification:
  remote health returned `status: ok`, `db: connected`, `redis: connected`, `worker: ok`, and sandbox `status: ok`.

- [x] Metrics did not expose full operational status.
  Resolution:
  `/api/v1/system/metrics` now includes `chainless_db_up`, `chainless_redis_up`, `chainless_worker_up`, and existing sandbox/rate-limit gauges.
  Verification:
  remote metrics probe confirmed all four up gauges were present.

- [x] Rate limiting existed but had not been proven in the live runtime.
  Verification:
  after clearing Redis `ratelimit:*` keys, 70 requests to `/api/v1/system/metrics` returned 429s inside the one-minute window.

- [x] Restore procedure was undocumented and not represented by a script.
  Resolution:
  added `backend/scripts/restore.sh` and `docs/operations-production.md`.
  Verification:
  remote `./scripts/restore.sh` without args returns usage and exit code `2`, and `psql --version` is available in the backend container.

- [x] Conversation loading state could remain stuck after restoring or clearing active conversation state.
  Evidence:
  an early Workstream 10 browser run reached `/chat` but stayed on `Loading conversations...`, blocking the chat SSE step.
  Root cause:
  `loadConversations()` had early returns after no restored conversation or already-loaded restored messages without resetting `isLoadingConversations`.
  Resolution:
  those early returns now set `isLoadingConversations: false`, and the final Workstream 10 browser gate passed.

- [x] Reloading `/chat` does not restore the active conversation selection.
  Evidence:
  after a successful `code_as_action` run, browser verification showed the conversation list still loading correctly from the backend, but the page body returned to `No conversation selected` after refresh instead of reopening the active conversation.
  API proof:
  direct backend reads still returned the active conversation in the paginated list before and after reload.
  Resolution:
  `frontend/src/stores/chat-store.ts` now persists `currentConversationId` to `localStorage` on selection/creation and restores it during `loadConversations`, including reloading the matching conversation detail payload.
  Verification:
  browser artifact directory:
  `.gstack/qa-reports/local/refresh-restore-2026-06-03T15-38-58-438Z/`
  confirmed:
  - `activeConversationId` is populated before refresh
  - the same id remains after refresh
  - `/chat` no longer falls back to `No conversation selected`

## Working assessment

- [x] Product-readiness gaps are no longer floating.
  Foundational backend, sandbox, and historical W8-W10 runtime evidence are
  preserved as verified baselines. Every remaining production, frontend,
  security, contract, isolation, and final-QA gap is mapped to exactly one
  owner in `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md` and is
  executed only through
  `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`.

## Workstream 2 closure findings

- [x] API error envelopes were inconsistent and partly route-local.
  Resolution:
  added canonical contract helpers in `backend/app/api/contracts.py` and routed
  HTTP, validation, and unexpected errors through the shared envelope:
  `{"error":{"code":"...","message":"...","detail":...}}`.

- [x] List endpoints did not share one pagination contract.
  Resolution:
  route list responses now use the canonical `items/total/limit/offset/next`
  envelope, including `/api/v1/proactive-tasks/runs`.

- [x] Auth lifecycle did not prove disabled-user and refresh behavior.
  Resolution:
  backend contract tests now cover missing bearer token, login/refresh/me, and
  disabled users returning stable auth error envelopes.

- [x] Test execution could accidentally depend on live database/runtime.
  Resolution:
  `docker-compose.test.yml` now owns isolated `db-test`, `redis-test`,
  `backend-test`, `backend-test-server`, and `frontend-test` services, and the
  pytest fixture fails closed unless the database URL contains `db-test` and
  `chainless_test`.

- [x] Test server service initially reported healthy before migrations existed.
  Evidence:
  the first `backend-test-server` probe failed registration with a 500.
  Resolution:
  `backend-test-server` now uses `./scripts/startup.sh`, so migrations and seed
  run against the test database before the API becomes usable.

- [x] Browser QA launcher was becoming one large owner.
  Resolution:
  split reusable QA concerns into `scripts/qa/api-client.cjs`,
  `scripts/qa/cleanup-registry.cjs`, and `scripts/qa/suite-registry.cjs`.

- [x] W2 verification initially used an old backend-test image.
  Evidence:
  pytest collected 14 tests until the `backend-test` image was rebuilt.
  Resolution:
  rebuilt the test image before final W2 verification; final result was
  `15 passed`.

## Workstream 3 closure findings

- [x] Public SSE stream still exposed legacy event names.
  Evidence:
  `conversations.py` emitted `tool_call_start` and `tool_error` directly.
  Resolution:
  public SSE now emits canonical `tool_call` and `tool_result`; internal
  `tool_error` is represented as `tool_result` with `status: "error"`.

- [x] Conversation route file owned too much stream behavior.
  Evidence:
  `conversations.py` owned route logic, SSE formatting, heartbeat, agent event
  mapping, confirmation persistence, and assistant persistence.
  Resolution:
  added `backend/app/services/conversation_stream_service.py` and moved stream
  orchestration/persistence there; `conversations.py` now remains a route and
  CRUD owner.

- [x] SSE errors did not use the shared error envelope owner.
  Resolution:
  added `backend/app/api/sse.py`; stream errors now use the canonical
  `{"error":{"code","message","detail"}}` envelope.

- [x] Code-as-Action execution did not expose sandbox execution evidence in the
  public stream.
  Resolution:
  `stream_code_as_action` emits `sandbox` and `sandbox_output` events while
  preserving the old aggregate `execute_code_as_action` helper.

- [x] Dropped stream handling lacked explicit duplicate-persistence coverage.
  Resolution:
  added `test_disconnected_stream_does_not_persist_partial_assistant`, proving
  an already-disconnected request does not persist a partial assistant message.

- [x] Frontend stream parser depended on legacy event names.
  Resolution:
  `frontend/src/lib/api.ts` now consumes canonical `tool_call` and
  `tool_result` events. No frontend style, component layout, color, spacing, or
  visual behavior was changed.

## Workstream 10 closure findings

- [x] Public production access previously depended on direct frontend/backend
  ports and could leave the public page stuck.
  Resolution:
  Compose-managed Nginx is now the only published production entrypoint on
  port 80; frontend, API, SSE, docs, and metrics use one origin.

- [x] Initial private-network split accidentally removed backend/worker egress.
  Evidence:
  browser QA showed LiteLLM connection errors after the first W10 deployment.
  Resolution:
  added a non-published `egress` network only for backend and worker while DB,
  Redis, sandbox-proxy, frontend, and sandbox remain isolated.

- [x] Production still accepted placeholder secrets and the historical
  `admin/admin123` bootstrap credential.
  Resolution:
  production startup now fails closed for DB, JWT, encryption, proxy, and
  bootstrap-admin placeholders; the production switch script generates all
  required values and rotates the legacy default admin password once.

- [x] Sandbox-proxy build could hang on unpinned public pip resolution.
  Resolution:
  added pinned `sandbox-proxy/requirements.txt` and the verified package mirror.

- [x] Sandbox pool could fall below its configured minimum after container
  expiry.
  Resolution:
  health and allocation paths now compact stale queue entries and self-heal the
  bounded managed pool back to `POOL_MIN`.

- [x] Browser QA used public `:8000`, hard-coded insecure admin credentials,
  false-positive tool assertions, and left archived test conversations.
  Resolution:
  QA now uses same-origin API, a fixed non-admin QA tenant, exact tool/output
  assertions, and owner-scoped `?purge=true` cleanup.

## Workstream 4 final-slice closure findings

- [x] Per-run sub-agent result artifacts had no terminal cleanup owner.
  Resolution:
  `SubAgentRuntime.finalize_parent_artifacts()` now observes success, timeout,
  and error results and safely removes the run-scoped temporary artifacts at
  parent terminal.

- [x] A text-only eval could not prove Code-as-Action used real sub-agents.
  Resolution:
  `spec_complete` now requires a real disposable parent, two concurrent UDS
  `spawn_sub_agent` calls, measured overlap, aggregated child results,
  canonical lifecycle/artifact evidence, and verified cleanup.

- [x] The derived test workspace contained historical `sub_results` residue
  from runs before lifecycle cleanup existed.
  Resolution:
  removed the bounded `/workspace/runs` test-volume residue once; subsequent
  live proof and residue inspection confirm the new lifecycle leaves none.

## Workstream 5 runtime concerns

- [x] Production and test sandbox proxies do not have isolated managed-pool
  ownership.
  Evidence:
  a production `sandbox-proxy` recreation removed two containers still cached
  by `sandbox-proxy-test`; the next `spec_complete` run received two allocation
  `500` responses for stale container IDs. After the stale test pool was
  drained, the immediate rerun passed `1 / 1`.
  Required resolution:
  add an explicit proxy/pool owner label and make startup recovery, allocation,
  recycle, health, and cleanup operate only on that owner. Add a two-proxy
  restart regression proving neither proxy adopts or removes the other's
  managed containers.
  Runtime rule:
  read-only production probes must use `docker compose run --no-deps` so
  Compose cannot recreate dependencies because of configuration drift.
  Resolution:
  added `SANDBOX_PROXY_OWNER` with distinct production/test owners, applied the
  owner label to managed and disposable sandbox containers, scoped startup and
  cleanup queries by owner, and verified production/test pools no longer
  remove each other's containers.
  Additional repair:
  `/health` now reconciles proxy memory against Docker's live state before
  reporting, forgets externally removed containers, removes unpingable
  containers, and refills the pool to `POOL_MIN`.
  Verification:
  local Docker target tests passed at `49 passed`; full backend passed at
  `247 passed, 4 skipped`; `spec_complete` passed `1 / 1`, `100%`;
  production boundary probe returned sandbox output `42`; final residue check
  found no disposable containers and exactly two production-owned managed
  containers.

## Workstream 5 frontend/settings findings

- [x] Settings form action buttons could accidentally submit their parent forms.
  Evidence:
  controller review found provider `Test`, provider `Make default`, provider
  `Delete`, channel `Test Feishu`, and skill `Delete` buttons inside forms
  without explicit button type.
  Resolution:
  set non-submit actions to `type="button"` while preserving all existing
  styles.

- [x] Production browser emitted React hydration error `#418` after logging in
  and navigating to `/settings`.
  Evidence:
  local Chrome browser smoke reproduced a `pageerror` with React `#418` while
  token state was read directly from `localStorage` during render.
  Resolution:
  added `useTokenPresent()` backed by `useSyncExternalStore`, returning `null`
  during server/hydration and a stable client token snapshot after hydration.
  `chat/page.tsx` and `settings/page.tsx` now use that hook.

- [x] Docker frontend builds depended on live Google Fonts fetches.
  Evidence:
  repeated `next build` attempts failed while fetching Geist/Geist Mono from
  Google Fonts.
  Resolution:
  `layout.tsx` now uses Next's bundled local Geist/Geist Mono font files via
  `next/font/local`, preserving existing font variables while removing the
  external build-time dependency.

- [x] Settings admin flows could hit production rate limits during normal
  browser operation.
  Evidence:
  real Windows Chrome Settings QA repeatedly reached `429 Too Many Requests`
  while creating/searching/deleting memories; Redis showed the authenticated
  user had reached the `60/min` key, and the failing request was
  `/api/v1/eval/status?limit=100`.
  Root cause:
  every Agent/Tools/Memory/Proactive mutation called full `loadSettings()`,
  which fans out across all settings endpoints. Under Nginx/Docker, the
  original IP-only rate-limit key also caused false sharing for authenticated
  requests behind one upstream address.
  Resolution:
  authenticated requests now rate-limit by tenant/user identity while anonymous
  traffic still falls back to IP using trusted `X-Real-IP` before
  `X-Forwarded-For`, and all Settings mutations refresh only their owning
  section data instead of all settings data.
  Verification:
  focused backend tests returned `20 passed`, frontend lint/build passed, and
  final real Chrome Settings smoke completed Agent create/delete, Tools risk
  metadata visibility, Memory create/search/delete, and Proactive create/delete
  with `responses429: []`.

## Workstream 5 backend administration findings

- [x] Agent, Tools/MCP, and Proactive administration routes were not all
  admin-only.
  Resolution:
  added admin role guards to Agent CRUD/list/get, Tools list/register/test/delete,
  and Proactive task list/create/delete/run-history. Focused backend tests now
  prove non-admin `403` and promoted-admin success.

- [x] MCP failure responses could expose raw exception text.
  Resolution:
  MCP register/test now log raw exceptions server-side and return stable public
  messages. Tests cover secret-like MCP failure text not leaking to clients.

- [x] Agent administration route validation was weaker than other settings
  contracts.
  Resolution:
  agent list now uses bounded query validation and agent path ids are typed as
  `uuid.UUID`.

## Workstream 5 final closure findings

- [x] A text answer could fake provider-switch success unless the browser proof
  observed a real provider call.
  Evidence:
  a prompt like "output 42" or "say provider switch worked" can be satisfied by
  the LLM without proving the runtime used the configured provider.
  Resolution:
  the Windows browser settings suite now starts a temporary OpenAI-compatible
  mock provider, creates it through the Settings UI, makes it default, sends a
  real chat, waits for the context banner to name that provider, and asserts the
  mock provider saw exactly one `/chat/completions` call.
  Verification:
  `.gstack/qa-reports/local/settings-2026-06-14T11-47-08-833Z/report.json`
  recorded `mockCalls: 1` for provider
  `w5-final-1781437629115-provider`.

- [x] Production default rate-limit budget was too low for a complete Settings
  console flow.
  Evidence:
  full Settings browser QA can legitimately call many authenticated admin
  endpoints in one minute while opening all panels and creating/deleting
  resources. The previous `60/min` default left too little headroom even after
  section-local refreshes.
  Resolution:
  `RATE_LIMIT_PER_MINUTE` now defaults to `300`, with documentation and a
  regression test proving the default supports the full Settings console flow.
  Identity-based limiting by tenant/user remains the primary protection for
  authenticated traffic.
  Verification:
  final Windows Chrome Settings QA completed with `responses429: []`, and full
  backend tests returned `266 passed, 4 skipped`.

- [x] Next.js `_rsc` navigation aborts could create false browser-QA failures.
  Evidence:
  client navigation can abort stale `_rsc` requests with `net::ERR_ABORTED`
  while the app remains healthy.
  Resolution:
  the Windows browser QA harness records only `_rsc` plus `net::ERR_ABORTED` as
  `ignoredRequestFailures`; all other request failures still fail the report.
  Verification:
  final Settings QA had `requestFailures: []` and two separated ignored `_rsc`
  aborts.

- [x] `sandbox-proxy` health could report or retain an overgrown idle pool.
  Evidence:
  after eval/recycle paths, Docker showed four managed sandbox containers while
  the desired `POOL_MIN` was two.
  Resolution:
  `sandbox-proxy` now reconciles live Docker state during health, trims surplus
  idle containers to the configured target, and recycles clean containers only
  into the idle pool when capacity exists.
  Verification:
  `tests/test_sandbox_pool_lifecycle.py` returned `13 passed`; production
  health and direct sandbox-proxy health both reported `pool_size: 2` and
  `total_containers: 2` after rebuild/eval.

- [x] Backend clean-start probe requires the application path inside the
  container.
  Evidence:
  `docker compose exec -T backend python scripts/clean_start_probe.py` failed
  with `ModuleNotFoundError: No module named 'app'`.
  Resolution:
  run it as
  `docker compose exec -T backend sh -lc "PYTHONPATH=/app python scripts/clean_start_probe.py"`.
  Verification:
  the corrected command returned `{"ok": true, "migrations": "head",
  "seed": "idempotent", "login_ready": true}`.

- [x] PowerShell plus `psql -v` quoting is unreliable enough to waste time.
  Evidence:
  a temporary tenant admin-promotion command using `name=:'tenant'` reached
  PostgreSQL unexpanded and failed with a syntax error.
  Resolution:
  for generated safe test identifiers, use direct single-quoted SQL values in
  the `-c` string, then immediately verify the selected rows. Do not rely on
  psql variable substitution through nested PowerShell/docker quoting for QA
  cleanup or promotion commands.
  Verification:
  the corrected command updated two users to `role='admin'`, and deleting the
  exact temporary tenant removed all QA data.

- [x] Settings-backed memory APIs were member-accessible even though they mutate
  tenant-wide chat context.
  Evidence:
  code-quality review found `backend/app/api/v1/memories.py` used
  `get_current_user` for create/list/search/merge/update/delete, so any
  authenticated tenant user could alter context used by agents.
  Resolution:
  Memory Settings CRUD/search/merge now use `require_role("admin")`.
  Verification:
  focused admin/auth regression returned `43 passed`; production probe showed
  member memory mutation returns `403` while admin Settings browser QA still
  completes memory create/search/merge/delete.

- [x] Detailed system health and metrics leaked operational internals publicly.
  Evidence:
  code-quality review found `/api/v1/system/health` and
  `/api/v1/system/metrics` exposed DB/Redis/sandbox/rate-limit details without
  auth.
  Resolution:
  detailed system health/metrics now require admin role. Public liveness moved
  to `/api/v1/health` and `/health`, and Docker/backend-test healthchecks were
  updated to use public liveness.
  Verification:
  production probe showed public `/api/v1/health` returns `200`, no-auth
  detailed health/metrics return `401`, member detailed health returns `403`,
  and admin detailed health/metrics return `200`.

- [x] Provider and Feishu forms cleared secret inputs even when mutations
  failed.
  Evidence:
  code-quality review found the form submit handlers cleared inputs after
  store methods swallowed errors.
  Resolution:
  provider create/update and Feishu configure store methods now return a
  success boolean; forms clear values only when the mutation succeeds.
  Verification:
  frontend lint passed and final Windows Chrome Settings QA still passed all
  provider/channel steps with no console/page/request/429 errors.

- [x] PowerShell 5 does not support `Invoke-WebRequest -SkipHttpErrorCheck`.
  Evidence:
  the first production auth-boundary probe returned null status values because
  that PowerShell 7 parameter was unavailable.
  Resolution:
  use a `try/catch` helper that reads
  `$_.Exception.Response.StatusCode.value__` when probing expected 401/403
  responses from Windows PowerShell.
  Verification:
  the corrected probe captured 200/401/401/403/403/200/200 as expected.

- [x] `spec_complete` can fail once immediately after sandbox pool replacement
  because cold allocation consumes the 15s child deadline.
  Evidence:
  after production rebuild, the first eval showed both child artifacts had the
  correct outputs but `status: timeout`; sandbox-proxy logs showed old pool
  containers were removed and replaced during allocation, and the child
  execution intervals were only about 0.05s.
  Resolution:
  treat this as a warm-pool verification pitfall: call sandbox-proxy health to
  reconcile/warm the pool and rerun the eval before diagnosing runtime logic.
  Verification:
  the immediate warmed-pool rerun passed `spec_complete` at `1 / 1`, `100%`
  with both child artifacts `success`.

- [x] Runtime notes still contained old remote-server and public detailed
  health-check commands.
  Evidence:
  `docs/remote-windows-runtime-notes.md` still suggested
  `curl /api/v1/system/health` and `/metrics` as unauthenticated first-line
  checks, while the current W5 security fix makes detailed health and metrics
  admin-only. The Aegis intent also still named the retired remote Docker
  runtime as the source of truth.
  Resolution:
  updated the runtime notes, production operations doc, active execution-plan
  runtime amendment, and Aegis work intent to use local Docker Desktop,
  `http://localhost`, public `/api/v1/health`, and admin-token detailed
  health/metrics probes.
  Verification:
  documentation grep now keeps old remote commands only as historical evidence
  or explicitly marked archaeology, while active runtime-boundary text points
  to local Docker.

- [x] Production boundary probe did not directly reproduce the W5
  admin/member/no-auth boundary matrix.
  Evidence:
  independent code-quality re-review found
  `backend/scripts/production_boundary_probe.py` still proved public liveness,
  audit, and sandbox execution, but the full no-auth/member/admin
  health/metrics/memory boundary evidence was produced by an ad hoc
  PowerShell probe instead of the reusable production probe.
  Resolution:
  enhanced `production_boundary_probe.py` to create an exact-prefix temporary
  member tenant, prove public liveness `200`, no-auth detailed health/metrics
  `401`, member detailed health/metrics/memory mutation `403`, admin detailed
  health/metrics `200`, real sandbox output `42`, and finally delete both the
  probe conversation and temporary tenant.
  Verification:
  target tests returned `17 passed`; full backend returned `266 passed, 4
  skipped`; rebuilt/recreated backend, worker, and Nginx; enhanced live probe
  returned `ok: true` with the complete `auth_boundary` matrix and
  `cleanup: conversation-and-temp-tenant-deleted`; DB, Redis, and
  `/run/chainless-control` residue checks returned zero.

## Workstream 6 artifact/files/diff findings

- [x] Confirmed destructive/tool execution dropped artifact references.
  Evidence:
  independent review found the confirmation path unwrapped
  `ToolExecutionResult.content`, so confirmed file-write or sandbox tools could
  lose artifact refs before frontend rendering.
  Resolution:
  `execute_confirmed_tool` now preserves `ToolExecutionResult.artifacts` for
  the public `tool_result` while sending only text content back into the
  resumed LLM tool message.
  Verification:
  `tests/test_sse_contract.py` includes confirmation artifact preservation and
  the W6 target gate returned `24 passed`.

- [x] Artifact storage could leave orphan files after a failed database commit.
  Evidence:
  independent review found content/diff files were written before DB commit
  without a rollback cleanup path.
  Resolution:
  artifact capture now rolls back and deletes managed files on commit failure,
  and retention cleanup also removes orphan managed directories that have no
  database row.
  Verification:
  `tests/test_preview_security.py` covers orphan cleanup; final W6 residue
  checks found zero DB artifacts and no `w6-artifacts-*` files in
  `/data/artifacts`.

- [x] Artifact preview allowlisting was not enforced by the content endpoint.
  Evidence:
  independent review found the frontend could be shown a blocked preview while
  `/api/v1/artifacts/{id}/content` still returned the stored body.
  Resolution:
  the backend now exposes one preview contract and denies content reads for
  blocked, iframe-only, binary, oversized, or otherwise non-previewable
  artifacts. The frontend fetches content only for allowed code/text previews.
  Verification:
  `test_blocked_preview_url_cannot_read_content` passed in the W6 target gate.

- [x] Empty artifact content or empty unified diff looked like it was still
  loading.
  Evidence:
  review found frontend cache truthiness checks used the loaded value rather
  than key presence.
  Resolution:
  artifact content and diff caches now use `hasOwnProperty` so empty strings
  are valid loaded values.
  Verification:
  frontend lint and production build both passed after the fix.

- [x] Diff truncation could split UTF-8 bytes.
  Evidence:
  review found byte slicing could cut through a multibyte character before
  decoding.
  Resolution:
  diff truncation now preserves UTF-8 boundaries and appends a clear
  `[diff truncated]` marker.
  Verification:
  `test_diff_truncation_preserves_utf8_boundaries` passed in the W6 target
  gate.

- [x] Windows browser artifact QA assumed the legacy `admin123` password.
  Evidence:
  after W10/W5 production hardening, the seeded admin password is rotated from
  `.env`, so hard-coded `admin123` can make QA fail for the wrong reason.
  Resolution:
  `scripts/windows-browser-qa.cjs` reads `BOOTSTRAP_ADMIN_PASSWORD` or explicit
  QA credentials from `.env`/environment before falling back.
  Verification:
  final artifact browser QA logged in successfully through `http://localhost`
  and returned `ok: true`.

- [x] Streamed LiteLLM tool-call chunks could omit `name` or `arguments`.
  Evidence:
  W6 browser QA initially hit a streaming `TypeError` while assembling tool
  calls from partial chunks.
  Resolution:
  the LLM gateway and agent engine now normalize missing chunk fields to safe
  defaults while preserving streamed tool-call assembly.
  Verification:
  `backend/tests/test_llm_gateway_streaming.py` passed, full backend returned
  `282 passed, 4 skipped`, and the final browser artifact tool loop observed
  the expected two chat calls.

- [x] Browser artifact assertions were ambiguous when the same path appeared in
  chat text and the Files panel.
  Evidence:
  Playwright strict mode saw multiple matching nodes for the generated
  `w6-artifacts-*.py` path.
  Resolution:
  the artifacts QA suite scopes path assertions to
  `data-testid="artifact-file-list"` rows.
  Verification:
  final artifact browser QA completed Files and Diff assertions with
  `ok: true`.

- [x] Browser artifact QA created real workspace files that needed exact
  cleanup.
  Evidence:
  DB artifacts/conversations/providers were deleted, but the real file written
  by the test remained under `/workspace/w6/w6-artifacts-*.py`.
  Resolution:
  final W6 cleanup deletes only that exact test namespace and pattern, then
  rechecks for matches.
  Verification:
  final cleanup returned zero W6 DB providers/conversations/artifacts, no
  matching `/data/artifacts` files, and no remaining
  `/workspace/w6/w6-artifacts-*.py` files.

- [x] W6 artifact browser suite was making the Windows QA launcher larger.
  Evidence:
  `scripts/windows-browser-qa.cjs` reached 1239 lines after adding the artifact
  flow, while the active plan already identified the launcher as a
  high-pressure owner that should delegate suites/helpers.
  Resolution:
  moved the W6 artifact browser flow and mock provider into
  `scripts/qa/artifacts-suite.cjs`; the main launcher now only registers the
  suite through `createArtifactsSuite(...)`.
  Verification:
  bundled Node syntax checks passed for both JS files, and the final artifact
  browser QA still returned `ok: true`.

- [x] PowerShell command chaining with `&&` is a recurring local-runtime
  pitfall.
  Evidence:
  this Windows PowerShell environment rejected `&&` in earlier command attempts
  and wasted diagnosis time.
  Resolution:
  run dependent commands as separate PowerShell/tool calls, or use one shell
  end-to-end inside the Docker container with `sh -lc` when container shell
  semantics are required.
  Verification:
  final W6 verification used separate commands and completed without
  PowerShell parser failures.

- [x] Historical uploaded attachments could be replayed after deletion.
  Evidence:
  W7 review found that previous-message attachment metadata was trusted during
  later context assembly, so a deleted or unavailable upload artifact could be
  re-injected into a later LLM turn.
  Resolution:
  conversation context assembly now re-checks tenant, user, conversation,
  artifact state, operation, and attachment metadata before reading historical
  uploaded artifacts.
  Verification:
  `test_deleted_historical_attachment_is_not_reinjected_into_later_context`
  passed as part of the W7 backend gate; the full backend suite returned
  `297 passed, 4 skipped`.

- [x] `Ctrl+N` and `Ctrl+K` unsafe-context handling could leave native browser
  shortcuts active.
  Evidence:
  W7 review found the shortcut handler returned from input contexts before
  calling `preventDefault`, which could still allow native new-window/search
  behavior.
  Resolution:
  the chat shortcut owner now prevents default first for managed W7 shortcuts,
  then suppresses app actions when focus is inside unsafe editable contexts.
  Verification:
  final rich-input browser QA passed `ctrl-n-ignored-inside-input` and
  `ctrl-k-ignored-inside-input` and did not open extra pages or palette UI.

- [x] `@tool` picker was not a complete keyboard-only flow.
  Evidence:
  W7 review found the picker lacked a focused active option relationship and
  complete arrow/Enter/Tab selection semantics.
  Resolution:
  the picker now supports ArrowUp/ArrowDown/Home/End navigation, Enter/Tab
  selection, listbox/option semantics, `aria-selected`, and an
  `aria-activedescendant` relationship on the focused textarea.
  Verification:
  final rich-input browser QA passed `at-tool-picker-keyboard-selection` with
  `Use @code_as_action `; final sub-agent review found no remaining
  Critical, Important, or Minor blocker for W7 closure.

- [x] Long-conversation virtual scrolling was initially a false positive.
  Evidence:
  early W7 browser QA diagnostics showed `total=34`, `rendered=34`,
  `scrollHeight=3757`, and `clientHeight=3757`, proving the prior marker did
  not reduce DOM rows.
  Resolution:
  the chat panel now uses real dynamic-height DOM windowing and the scroll
  container has the required flex height boundary so only visible/overscan rows
  render.
  Verification:
  final rich-input browser QA passed with `total=34`, `rendered=12`,
  `rows=12`, `scrollHeight=3730`, and `clientHeight=795`.

- [x] Multi-file upload could hide successful attachments if a later upload
  failed.
  Evidence:
  W7 review found the previous `Promise.all` shape could leave successful
  uploads missing from the UI when a later file rejected.
  Resolution:
  uploads now run per file and preserve successful attachment chips while
  showing a scoped error for failed files.
  Verification:
  W7 frontend lint/build passed after the change, and final browser QA passed
  both file picker upload and drag/drop upload.

- [x] Host `node` is not a reliable command in the Windows local-runtime lane.
  Evidence:
  this machine does not provide project Node on the host, and the project rule
  is to avoid host project runtimes.
  Resolution:
  W7 syntax checks used the bundled Codex Node path, while project lint/build
  ran inside Docker images.
  Verification:
  bundled Node `--check scripts\qa\rich-input-suite.cjs` passed, and Docker
  frontend lint/build passed.

## Workstream 8 proactive/eval/runtime findings

- [x] W8 planned target tests were absent before this slice.
  Evidence:
  the W8 plan referenced proactive authorization, eval, observability, runtime
  limit, instruction reload, memory source, MCP transport, tool cancellation,
  event trigger, and delayed task tests that did not exist yet.
  Resolution:
  added the W8 contract test set and included sandbox pool lifecycle regression
  coverage after verification found a runtime pool bug.
  Verification:
  W8 target gate returned `40 passed`.

- [x] Eval failed when the default tenant had no configured LLM provider.
  Evidence:
  `run-eval.py --suite basic --json --min-pass-rate 1.0` initially failed with
  `Configured LLM provider was not found`; DB inspection showed the default
  tenant had no default provider row.
  Resolution:
  eval now uses a deterministic no-secret gateway fallback only when no default
  provider is configured, while runtime chat still uses the DB provider owner.
  Verification:
  final `basic` eval returned `10 / 10` and `spec_complete` returned `4 / 4`.

- [x] `run_agent` runtime-limit defaults were bound too early.
  Evidence:
  full backend initially failed
  `test_child_consumption_reduces_parent_turn_budget` because monkeypatched
  runtime constants did not affect defaults captured at function definition.
  Resolution:
  `run_agent` now resolves default budgets/circuit-breaker limits at call time.
  Verification:
  focused regression passed, and final full backend returned
  `325 passed, 4 skipped`.

- [x] Sandbox-proxy health could report expired idle containers as healthy.
  Evidence:
  `spec_complete` failed once with both child artifacts containing correct
  output but `status: timeout`; proxy logs showed `/health` had reported a
  healthy pool, then first allocation removed expired idle containers and cold
  created replacements inside the child deadline.
  Resolution:
  sandbox-proxy `/health` reconciliation now prunes expired containers before
  reporting and warms fresh replacements.
  Verification:
  `test_health_prunes_expired_idle_container_and_replenishes` passed,
  sandbox pool lifecycle returned `14 passed`, and final `spec_complete`
  passed `4 / 4` with both child artifacts `success`.

- [x] Proactive run history could leak prompt text or deliver after blocked
  tool attempts.
  Evidence:
  W8 proactive safety required pre-authorized tool enforcement and no prompt or
  secret leakage in logs/metrics.
  Resolution:
  proactive execution records prompt SHA-256 only, records blocked tools and
  blocked attempts, skips channel delivery when an unauthorized tool is
  attempted, and keeps delivery evidence bounded.
  Verification:
  W8 proactive authorization and observability tests passed, and
  `inspect_proactive_redis.py` reported zero unsafe records after cleanup.

- [x] MCP lifecycle and transport behavior was narrower than the spec.
  Evidence:
  previous evidence covered stdio echo registration/invocation but not HTTP,
  SSE-style transport, idle reconnect, unavailable server behavior, or default
  risk classification.
  Resolution:
  MCP clients now support stdio, HTTP, and SSE-style HTTP transports, reconnect
  after idle timeout, stable missing-server errors, and default `risky`
  classification. A safe filesystem MCP server fixture now registers
  `mcp__fs__list_directory` for the original discovery/invocation gate.
  Verification:
  `tests/test_mcp_transports.py` and `tests/test_eval_contract.py` returned
  `9 passed`; `spec_complete` includes both filesystem MCP default-risk and
  real filesystem MCP discovery/invocation probes.

- [x] W8 metrics originally exposed several fixed placeholder counters.
  Evidence:
  `/api/v1/system/metrics` included W8 metric names for sub-agent lifecycle,
  SSE disconnect/errors, artifact failures/quota, and eval outcomes, but the
  initial implementation returned fixed zero values for those non-proactive
  counters.
  Resolution:
  added a focused runtime metrics owner for secret-free in-process counters and
  file-backed eval result summaries; SSE, artifact, and sub-agent lifecycle
  owners now increment their counters, and eval outcomes are summarized from
  `tests/eval/results/*_results.json`.
  Verification:
  observability/upload/eval/streaming tests returned `23 passed`; final
  authenticated metrics returned `chainless_eval_outcomes_total{status="pass"} 14`,
  `fail=0`, and `error=0`, with the runtime counters present.

- [x] Exact memory gate was initially weaker than the reconciled spec.
  Evidence:
  the first W8 memory test only inspected that source code used
  `cosine_distance`, but the matrix required at least five memories across
  different types and a real cosine-distance query.
  Resolution:
  added a real test DB gate that inserts five typed memories with
  1536-dimensional pgvector embeddings and proves `search_memories()` returns
  the nearest row through actual `cosine_distance` ordering.
  Verification:
  `tests/test_memory_source_contract.py` returned `5 passed`.

- [x] A stale W5 proactive QA task remained in Redis.
  Evidence:
  W8 live probe cleanup left `task_count: 1`; read-only inspection showed the
  remaining task prompt was `w5-final-*`, not a user task.
  Resolution:
  deleted the exact task id
  `ab9ffb17-187c-49a3-aed7-0c83984e1822` for tenant
  `2ded9ecf-0475-4a7d-a8d1-8ddfcd21dfc2`.
  Verification:
  final proactive Redis inspection returned `task_count: 0`, `run_count: 0`,
  and zero unsafe records.

## Workstream 9 multi-tenant concurrency/isolation findings

- [x] MCP registrations were globally visible across tenants.
  Evidence:
  W9 resource-family review found `mcp_manager` was a process-global singleton
  keyed only by server name. Tenant-authenticated tool routes and runtime
  execution did not pass tenant ownership into list/register/test/delete or
  execution paths.
  Resolution:
  MCP manager registrations now carry an optional owner key. Tools API,
  conversation tool discovery, and agent tool execution pass `tenant_id`, while
  `owner=None` remains the global/backward-compatible path.
  Verification:
  final W9 pytest and Docker HTTP probe proved tenant B cannot list, test, or
  delete tenant A's MCP registration; the full W9 probe returned `ok: true`.

- [x] MCP Tools API error compatibility fallbacks could retry without tenant
  owner scope.
  Evidence:
  independent W9 review found `TypeError` fallback paths around MCP test/delete
  could reopen the old global-manager behavior after tenant-scoped calls
  failed.
  Resolution:
  the compatibility fallbacks were removed from the Tools API, so test and
  unregister paths now fail closed through the tenant-scoped MCP manager
  contract.
  Verification:
  post-review focused gate returned `7 passed`, and `rg` confirmed the Tools
  API no longer contains those `TypeError` MCP fallback paths.

- [x] Cross-tenant mutation coverage was incomplete for provider, agent, and
  skill resources.
  Evidence:
  independent W9 review found the isolation matrix covered some denied reads
  but did not prove provider update/default/delete, agent update/delete, and
  skill update/delete could not mutate another tenant's resources.
  Resolution:
  W9 pytest and Docker HTTP probe now exercise those denied mutations and
  verify the source tenant's provider, agent, and skill still exist afterward.
  Verification:
  exact W9 pytest returned `1 passed`, and the final Docker HTTP probe returned
  `ok: true`, `check_count: 42`, `p95_ms: 393.4`, and `failures: []`.

- [x] Detailed health p95 could exceed the W9 budget when sandbox proxy was
  unavailable in the non-live test stack.
  Evidence:
  the first Docker HTTP probe had `p95_ms: 7052.11`, then `3959.31`, with
  `system/health` as the slowest path. Direct diagnosis showed the non-live
  compose stack configured `SANDBOX_PROXY_URL=http://sandbox-proxy-test:9001`
  even though the `sandbox-proxy-test` service only starts under the
  `live-docker` profile.
  Resolution:
  `SandboxManager.get_proxy_health()` uses a bounded realtime health timeout,
  `collect_operational_health()` bounds sandbox checks, and non-live
  `backend-test`/`backend-test-server` now use
  `http://127.0.0.1:9001` so the absent proxy degrades fast. The live-docker
  test service explicitly keeps `http://sandbox-proxy-test:9001`.
  Verification:
  three concurrent admin health calls returned about `84ms` each with sandbox
  degraded by `ConnectError`, and the final W9 probe returned
  `p95_ms: 393.4`.

- [x] DB health used a widening asyncpg pool that could create connection
  storms during concurrent health probes.
  Evidence:
  focused diagnosis of three concurrent `/api/v1/system/health` calls showed
  DB checks timing out after about `3s` with `Database health check failed
  (TimeoutError)`.
  Resolution:
  DB health now uses a single small asyncpg health connection with explicit
  short acquire/query budgets instead of a multi-connection health pool.
  Verification:
  focused health tests passed, DB stayed `connected` in concurrent health
  checks, and the W9 related regression returned `52 passed`.

- [x] The W9 isolated test stack could accidentally point health at a
  live-docker-only service name.
  Evidence:
  `docker-compose.test.yml` had `backend-test` and `backend-test-server`
  configured to resolve `sandbox-proxy-test` without starting the profile that
  provides that service.
  Resolution:
  production config tests now assert non-live test services use loopback
  sandbox proxy URLs and `backend-test-live` is the only test service wired to
  the live sandbox proxy dependency.
  Verification:
  `test_live_docker_tests_are_isolated_behind_a_healthy_proxy_dependency`
  passed as part of the W9 focused gate.

## V2 W4 Worker runtime closure findings

- [x] Active Workers were not actually callable from normal chat.
  Evidence:
  the first W4 spec review found `get_agent_tools()` exposed only built-in,
  MCP, and code tools, while `run_agent_stream()` called `run_agent()`
  directly and `execute_worker_run()` had no production app call site.
  Resolution:
  normal chat now runs semantic Worker matching before the ordinary Agent path.
  `auto_notice` Workers execute through `execute_worker_run`, while medium and
  confirmation-required matches keep the normal Agent path.
  Verification:
  W4 spec re-review returned `SPEC_PASS`, and SSE contract tests prove
  auto-execute, medium non-execute, and confirmation notice behavior.

- [x] Worker fallback was not transparent enough for users or stream clients.
  Evidence:
  first W4 spec review found fallback status could be stored without a visible
  Worker failure/fallback notice.
  Resolution:
  fallback now emits `worker_notice` before fallback events and records
  `failed_fallback_succeeded` or `failed_fallback_failed`.
  Verification:
  W4 targeted tests include fallback notice and status assertions.

- [x] Worker live streaming reused bounded persisted trace and could drop
  terminal events.
  Evidence:
  first W4 quality review found `execute_worker_run()` returned
  `output_payload["events"]`, but persisted events are capped at
  `MAX_CAPTURED_EVENTS`, so long Worker streams could lose final `done` and
  leave SSE waiting on heartbeats.
  Resolution:
  runtime now separates live stream events from DB-bounded trace, keeps
  persisted events capped, and preserves terminal events when clipping.
  Verification:
  regression `test_chat_runtime_long_worker_stream_terminates_after_persisted_trace_cap`
  passes and proves `MAX_CAPTURED_EVENTS + 1` chunks still terminate.

- [x] `failed_fallback_failed` could be masked by an earlier Worker
  `error`/`done` terminal pair.
  Evidence:
  second W4 quality review found final-status semantics could be lost if the
  failed Worker already emitted terminal events before fallback failed.
  Resolution:
  fallback execution strips terminal events from the failed Worker before
  appending fallback events, and `failed_fallback_failed` appends canonical
  `WORKER_FALLBACK_FAILED` as final live and persisted terminal event.
  Verification:
  exact regression `test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
  passed, final targeted W4 suite returned `39 passed`, and full backend
  returned `413 passed, 4 skipped`.

- [x] Full backend Docker test command was missing required isolated-test
  environment variables.
  Evidence:
  first full backend run failed because `APP_ENV` was not `test`,
  `CHAINLESS_TESTING` was not `1`, and sandbox-proxy tests import
  `SANDBOX_IMAGE` at module load.
  Resolution:
  use full backend Docker tests with `APP_ENV=test`,
  `CHAINLESS_TESTING=1`, and `SANDBOX_IMAGE=chainless-sandbox:latest`.
  Verification:
  corrected full backend command returned `410 passed`, later `412 passed`,
  and final `413 passed`.

- [x] Full backend Docker tests can fail before collection when isolated test
  containers are stopped.
  Evidence:
  `pytest -q` in the backend test image failed during Alembic startup with
  `socket.gaierror: [Errno -2] Name or service not known` for `db-test`.
  Root cause:
  stopped containers `chainless-db-test` and `chainless-redis-test` still held
  the expected `db-test` / `redis-test` aliases on `chainless_default`, but
  they were not running.
  Resolution:
  run `docker start chainless-db-test chainless-redis-test`, wait until both
  are healthy, then rerun the Docker pytest command on `chainless_default`.
  Verification:
  after restart, full backend Docker verification returned
  `422 passed, 4 skipped`.

- [x] PowerShell raw double-quoted `rg` patterns can break when the pattern
  itself contains JSON/code quotes.
  Evidence:
  a W4 inspection command failed with `The string is missing the terminator:
  "`.
  Resolution:
  use single-quoted `rg` patterns, or use `Get-Content` slices for code
  inspection when matching quote-heavy snippets.
  Verification:
  later inspections used quoted paths and `Get-Content` without repeating the
  parser failure.

- [ ] Worker matching is not yet backed by persisted Worker embedding/index
  rows.
  Evidence:
  W4 spec reviewer marked this as non-blocking: semantic matching is
  embedding-backed, but worker-side embeddings are computed at match time
  rather than stored/indexed as pgvector rows.
  Required follow-up:
  later workstream should persist Worker match embeddings or otherwise bound
  matching cost before large-scale production use.

- [x] Minimal Worker policy vocabulary needed tightening in later policy/hook
  work.
  Evidence:
  W4 policy is intentionally minimal. Non-empty allowed-tool lists are enforced
  in normal execution and confirmation resume, but empty allow-list semantics
  are still ambiguous between "no tools" and "unrestricted" across helpers.
  Resolution:
  W6 made allow-list semantics explicit in the Worker tool policy facade: when
  `allowed_tool_names` or `allowed_tools` is present, an empty list means no
  tools; absent Worker context preserves normal Agent behavior. W6 review fixes
  removed Worker runtime's use of generic `authorized_tool_names` for Worker
  allow-list enforcement, so real Worker execution now reaches
  `evaluate_worker_tool_policy` and emits the W6 policy/hook path.
  Verification:
  `test_empty_worker_allowed_tools_blocks_normal_and_confirmation_resume`
  proves real Worker runtime execution and confirmation resume are blocked by
  an empty Worker allow-list. W6 review-fix extended regression returned
  `36 passed`, and full backend returned `422 passed, 4 skipped`.

- [x] `WorkerRun.error_code/error_message` final-status metadata could be less
  precise than live/persisted terminal events.
  Evidence:
  final quality re-review passed but noted secondary run metadata may still
  reflect the initial Worker failure while terminal events correctly represent
  final fallback failure.
  Resolution:
  W6 now writes `WORKER_FALLBACK_FAILED` and the fallback failure message into
  `WorkerRun.error_code/error_message` when fallback execution also fails.
  Verification:
  `test_chat_runtime_failed_worker_and_failed_fallback_emit_terminal_error`
  and `test_chat_runtime_fallback_failure_overrides_prior_worker_error_done`
  now assert persisted `WorkerRun` metadata aligns with final fallback failure.
  W6 review-fix extended regression returned `36 passed`, and full backend
  returned `422 passed, 4 skipped`.

- [ ] `conversation_stream_service.py` is a large facade after W4.
  Evidence:
  W4 added chat/Worker orchestration to an already central stream service. The
  implementation still calls matcher/runtime/policy seams rather than owning
  internals, but file size is now a maintainability pressure.
  W6 update:
  direct `app.core.capabilities.policy` imports were removed from
  `conversation_stream_service.py` and replaced with the thin
  `app.core.capabilities.orchestration` seam. The file remains large, so this
  item stays open as a future maintainability/refactor issue rather than a W6
  correctness blocker.
  Required follow-up:
  avoid growing the stream service further; extract Worker stream orchestration
  into a dedicated runtime coordinator if later workstreams add more chat
  runtime logic.

## V2 W5 capability planning closure findings

- [x] Capability planning Memory retrieval admitted tenant-level legacy
  `Memory.user_id IS NULL` records.
  Evidence:
  W5 read-only review found `retrieval.py` delegated to
  `get_memories_for_session`, whose legacy visibility helper includes
  tenant-level null-user memories.
  Resolution:
  Memory retrieval helpers now keep legacy behavior by default but support
  `include_userless=False`; W5 capability retrieval uses that private-only
  mode so null-user memories cannot enter planning or consume retrieval budget.
  Verification:
  `tests/test_capability_planning.py` now seeds a null-user legacy Memory and
  proves it does not enter the rendered planning context. Final W5 targeted
  gate returned `30 passed`, broad regression returned `87 passed`, and full
  backend returned `416 passed, 4 skipped`.

- [x] Capability planning Skill retrieval admitted scopes broader than the W5
  contract.
  Evidence:
  W5 read-only review found `retrieval.py` allowed `shared` scope and any
  current-user scope instead of current-user `private` plus explicit
  `shared_legacy`.
  Resolution:
  W5 capability retrieval now allows only current-user `private` Skill rows and
  null-user `shared_legacy` Skill rows.
  Verification:
  `tests/test_capability_planning.py` now seeds current-user non-private Skill,
  null-user `shared` Skill, null-user `shared_legacy` Skill, and cross-user
  private Skill rows and verifies only the allowed rows enter planning.

- [x] Raw current user request text was rendered into the system prompt without
  explicit untrusted-data labeling.
  Evidence:
  W5 read-only review flagged prompt-injection risk because the `Current user
  request` section is appended to system instructions.
  Resolution:
  the prompt builder now labels the section as `UNTRUSTED current user request
  data` and states that instructions inside the quoted current request are
  user-role data that do not override system/developer instructions or hard
  guards.
  Verification:
  `tests/test_capability_planning.py` includes an adversarial request asking to
  ignore hard guards and asserts the untrusted-data warning and non-overridable
  hard guard summary are present.

## V2 W6 hard-guard and hook closure findings

- [x] Worker runtime disallowed tools could bypass the W6 Worker policy/hook
  path through generic runtime authorization.
  Evidence:
  W6 code review found `execute_worker_run()` passed Worker
  `allowed_tool_names` into `run_agent(... authorized_tool_names=...)`, so
  disallowed tools could emit generic `TOOL_NOT_AUTHORIZED` before
  `evaluate_worker_tool_policy()`.
  Resolution:
  Worker runtime no longer passes Worker allow-lists into generic
  `authorized_tool_names`; real Worker execution now reaches the Worker policy
  facade and emits `before_tool_call` / `after_tool_call` hooks.
  Verification:
  `test_empty_worker_allowed_tools_blocks_normal_and_confirmation_resume`
  fails before the fix with `TOOL_NOT_AUTHORIZED` and passes after the fix with
  `WORKER_TOOL_NOT_ALLOWED`. W6 review-fix extended regression returned
  `36 passed`, and full backend returned `422 passed, 4 skipped`.

- [x] `definition.external_delivery` did not require confirmation in policy
  and matcher.
  Evidence:
  W6 code review found `external_delivery` and
  `requires_external_confirmation` were checked only on `Worker.policy`, while
  WorkerVersion `definition` can also carry free-form runtime policy.
  Resolution:
  added shared `requires_worker_confirmation()` covering risk,
  `requires_confirmation`, `external_delivery`, and
  `requires_external_confirmation` from both Worker policy and WorkerVersion
  definition; matcher and policy now call this shared helper.
  Verification:
  `test_worker_policy_requires_external_delivery_and_destructive_confirmation`
  covers definition-level external delivery, and
  `test_worker_match_decisions_use_semantics_schema_risk_and_active_state`
  verifies matcher returns `needs_confirmation`.

- [x] Worker runtime direct improvement candidates did not emit candidate
  creation hooks.
  Evidence:
  W6 code review found `on_capability_candidate_created` fired through
  `create_candidate()` but not for Worker runtime failure candidates inserted
  directly in `runtime.py`.
  Resolution:
  runtime failure candidate creation now flushes the new candidate and emits
  `on_capability_candidate_created` with the same candidate/tenant/user/source
  shape.
  Verification:
  `test_worker_failure_hook_records_event_and_improvement_candidate` fails
  before the fix with no candidate-created hook and passes after the fix.

- [x] W6 secret-free evidence wording was too broad.
  Evidence:
  W6 code review noted tests proved only `WorkerRun.confirmation_metadata`
  excluded secret-like tool args; pending `ToolConfirmation.args` still stores
  replay arguments by design.
  Resolution:
  evidence now explicitly limits the no-secret claim to
  `WorkerRun.confirmation_metadata`.
  Verification:
  documentation evidence was updated; no runtime behavior was changed for
  confirmation replay persistence.
