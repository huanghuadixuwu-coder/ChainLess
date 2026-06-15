# Chainless V1 Spec Completion Checkpoint

## Current Todo

- [x] Workstream 1: authority and current-truth sync
- [x] Workstream 2: canonical API contracts and automated contract tests
- [x] Workstream 3: canonical SSE and conversation owner extraction
- [x] Workstream 10: production gateway, network, sandbox, and audit hardening
- [x] Workstream 4: dynamic runtime sub-agents
- [x] Workstream 5: platform settings and administration surface
- [x] Workstream 6: real artifacts, files, and diff flow
- [x] Workstream 7: rich input and keyboard shortcuts
- [x] Workstream 8: proactive safety, Feishu, eval, and hallucination guard
- [x] Workstream 9: three-tenant concurrency and isolation
- [x] Workstream 11: final spec-complete QA and evidence

## Active Slice

No active implementation slice. Workstream 11 implementation and runtime QA are
complete in local Docker; final state is waiting only for diff/review closeout
and no commit is authorized.

### Slice Card

- Goal: close W11 with final spec-complete QA, cleanup, and evidence.
- Parent plan/spec:
  `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
  Workstream 11.
- Boundary: preserve closed W1-W8/W10 behavior and do not change frontend
  style.
- Verification: local Docker full backend/frontend tests, API probe, browser
  QA, eval, backup/restore, performance probes, cleanup audit, and matrix/ledger
  updates.
- Stop: Workstream 11 acceptance is evidenced; live GLM and real Feishu receipt
  remain explicit external-credential proof boundaries, not hidden tails.

## Completed Todos

- Execution branch created: `codex/v1-spec-completion`.
- Approved plan reviewed using `aegis:executing-plans`.
- Runtime source of truth moved permanently to local Docker Desktop; remote
  server operations are forbidden.
- Workstream 1 authority/current-truth synchronization completed.
- W1 spec-compliance review approved before quality review.
- W1 quality review findings were fixed: completion ambiguity, W3 backend-test
  command, assertion-style verification, API error/pagination owner split,
  evidence citations, and malformed authority text.
- W1 final re-review by sub-agent was attempted but blocked by platform usage
  limit; the controller fallback ran the full W1 assertion gate successfully
  without claiming sub-agent approval.
- Workstream 2 completed by local evidence-gated fallback while sub-agent quota
  remained blocked.
- W2 added canonical API error helpers, pagination helper usage, isolated
  backend-test/backend-test-server/frontend-test services, pinned backend
  requirements, remote contract probe, and tenant-isolation coverage for the
  persisted V1 resource families.
- W2 explicitly treats built-in tools, channel definitions, and MCP manager
  state as runtime-ephemeral API surfaces; W8 remains the owner for MCP
  transport lifecycle hardening, not persistence ownership.
- Workstream 3 completed by local evidence-gated fallback while sub-agent quota
  remained blocked.
- W3 added canonical SSE helpers, extracted conversation stream orchestration
  into `backend/app/services/conversation_stream_service.py`, updated
  Code-as-Action to emit sandbox events, updated the frontend API parser without
  changing styles, and verified disconnects do not persist partial assistant
  messages.
- Workstream 10 completed with Compose-managed Nginx as the only public
  production entrypoint, private data/sandbox networks, bounded backend/worker
  egress, fail-closed production secrets, secure bootstrap admin rotation,
  durable tenant-scoped audit, hardened/self-healing sandbox pool, optional TLS,
  clean startup verification, and public-port browser QA.
- W4 slice 1 completed with the canonical backend lifecycle owner, fixed
  15-second timeout, process-global parallelism 5, shared budget accounting,
  authoritative cancellation, safe atomic run-scoped artifacts, and
  deterministic local-Docker tests.
- W4 slice 1 spec-compliance and code-quality reviews both approved.
- W4 slice 1 fresh local-Docker evidence: `50 passed` in
  `tests/test_subagents.py`.
- W4 slice 2 completed with backend-owned run-scoped capabilities, strict UDS
  RPC allowlisting, shared-GID least privilege, disposable parent sandboxes,
  fail-closed cleanup, bounded connections/handlers/containers/output, and
  Docker cancellation cleanup.
- W4 slice 2 spec-compliance and code-quality reviews both approved.
- W4 slice 2 fresh local-Docker evidence: deterministic gate passed twice at
  `88 passed`, live cross-container UDS/disposable cleanup `1 passed`, and no
  disposable/control-socket residue.
- W4 slice 3 completed with genuine UDS-to-`run_agent` child execution,
  independent child-owned sandboxes, trusted tenant scope, a shared parent/child
  budget ledger, canonical success/error/timeout/cancel lifecycle events, and
  authoritative cancellation/cleanup across API, backend, proxy, Docker, and
  control-socket boundaries.
- W4 slice 3 spec-compliance and code-quality reviews both approved after all
  concrete findings were fixed and re-reviewed.
- W4 slice 3 fresh local-Docker evidence: W4 gate `180 passed, 3 skipped`, full
  backend `199 passed, 3 skipped`, live cross-container Docker `3 passed`,
  empty-database migration `0001 -> 0002 -> 0003` plus idempotent seed/login
  probe, and zero disposable/test-run/control-socket residue.
- W4 final slice implemented the backend-owned result artifact lifecycle,
  deterministic two-child parallel `spec_complete` runtime eval, and live
  local-Docker log/artifact/cleanup proof without changing frontend files.
- W4 final-slice fresh local-Docker evidence: W4 gate `169 passed, 3 skipped`,
  full backend `205 passed, 4 skipped`, live proof `1 passed`, `spec_complete`
  eval `1 / 1` at `100%`, clean-start probe `ok: true`, and zero
  disposable/test-run/control-socket/run-artifact residue.
- Workstream 4 final independent review approved with no reproducible spec or
  code-quality blocker. The reviewer independently reran full backend
  `205 passed, 4 skipped`, focused regression `121 passed, 4 skipped`, live
  proof `1 passed`, and `spec_complete` `1 / 1` at `100%`, with zero relevant
  residue.
- W5 slice 1 completed the admin-only, audited, tenant-scoped provider/channel
  settings security foundation without touching frontend files or styles.
- W5 slice 1 made PostgreSQL the sole provider/channel configuration owner,
  added authenticated secret encryption and stable masked metadata, connected
  tenant default selection to chat/memory/worker/eval runtime, and retained
  only the published Feishu routes as stateless compatibility adapters.
- W5 slice 1 retired the provider API/gateway `_providers` dictionaries,
  `register()` runtime path, `GLM_API_KEY/default_llm_*` Compose/config
  duplicate owner, and raw provider/channel exception output.
- W5 slice 1 fresh local-Docker evidence: settings/security gate `25 passed`,
  full backend `211 passed, 4 skipped`, clean migration `0001 -> 0002 -> 0003
  -> 0004`, idempotent seed/login-ready probe, Compose and `git diff --check`
  passed, and zero test-run/disposable residue.
- W5 slice 1 hardening follow-up closed the provider-test audit secret/name
  leak, production/test sandbox-proxy owner isolation, and sandbox-proxy
  `/health` stale in-memory pool reporting.
- W5 slice 1 follow-up evidence: focused sandbox/settings/security gates
  passed, full backend `247 passed, 4 skipped`, `spec_complete` eval `1 / 1`
  at `100%`, production boundary probe returned sandbox output `42`, clean
  startup probe returned `ok: true`, production proactive Redis inspection
  found zero tasks/runs/unsafe records, and final container inspection found
  no disposable containers with exactly two `chainless-production` managed pool
  containers.
- W5 slice 1 sub-agent spec review approved the settings/security foundation
  after the follow-up fixes; the health repair worker was closed after its
  target tests were rerun by the controller.
- W5 slice 2 backend contract foundation added admin-only tenant-scoped passive
  skill metadata CRUD/list/match and admin-only eval suite/status/run
  contracts without touching frontend files.
- W5 slice 2 evidence: target backend tests `16 passed`, full backend
  `250 passed, 4 skipped`, clean-start probe `ok: true`, production smoke
  created/matched/deleted a temporary skill through `/skills` and validated
  `/eval` dry-run, then deleted the exact temporary tenant; `spec_complete`
  remained `1 / 1`, `100%`.
- W5 slice 3 added the admin-only `/settings` frontend shell for Provider,
  Channel, Skills, Eval, and System while preserving the existing sidebar/chat
  visual language.
- W5 slice 3 fixed form button mis-submit behavior, production auth hydration
  mismatch (`React #418`), and Docker frontend build instability from Google
  font fetches by using the bundled local Geist font files.
- W5 slice 3 evidence: frontend-test build passed, frontend lint passed with
  zero warnings/errors, production frontend build passed, `frontend nginx` was
  restarted, admin API smoke returned health `ok`, and local Chrome browser
  smoke opened every Settings tab with zero console errors or failed requests.
- W5 slice 3 cleanup deleted all temporary `w5-browser-*` tenants created for
  browser QA.
- W5 slice 4a completed backend administration contract hardening for Agents,
  Tools/MCP, and Proactive.
- W5 slice 4a evidence: non-admin settings route coverage plus promoted-admin
  success coverage for Agent CRUD, Tools/MCP list/register/test/delete, and
  Proactive list/create/delete/runs; MCP failure messages no longer return raw
  exception text; focused backend tests returned `47 passed`; spec and
  code-quality sub-agent reviews passed.
- W5 slice 4b completed the frontend administration panels for Agents,
  Tools/MCP, Memories, and Proactive without changing the established frontend
  visual language.
- W5 slice 4b found and fixed a real Settings runtime defect: full settings
  reloads after every mutation caused normal admin UI flows to exceed the
  production rate limit. Authenticated rate-limit keys are now tenant/user
  scoped, anonymous IP fallback prefers trusted `X-Real-IP`, and Settings
  mutations refresh only their owning section data instead of reloading the
  full platform state.
- W5 slice 4b evidence: backend focused gate `20 passed`, frontend lint
  passed, `frontend-test` build passed, production backend/frontend were
  rebuilt and restarted, health returned `status: ok`, and local Windows
  Chrome browser smoke opened all nine Settings tabs and completed Agent
  create/delete, Tools risk metadata visibility, Memory create/search/delete,
  and Proactive create/delete with zero console errors, page errors, failed
  requests, or `429` responses.
- W5 slice 4b spec-compliance review passed; code-quality review found two
  blockers, spoofable anonymous IP rate-limit identity and incomplete
  local-refresh coverage, both fixed and re-verified.
- W5 slice 4b cleanup deleted all `w5-ui-*` temporary tenants and confirmed
  proactive Redis tasks/runs/unsafe records were all zero.
- W5 final completed the remaining user-operable administration surface:
  provider default selection, real provider-switch chat proof, active-agent
  semantics, tool enable/risk override administration, Feishu channel secret
  surface, passive skill matching, eval dry-run, system health, dark-mode
  toggle, context banner, and every-section browser QA.
- W5 final repaired two runtime blockers found by verification: Settings admin
  flows needed a higher production-safe default rate-limit budget, and
  sandbox-proxy health/recycle could leave the managed idle pool above
  `POOL_MIN`.
- W5 final code-quality review initially failed on two admin-boundary gaps:
  tenant-wide memory mutation was member-accessible and detailed system
  health/metrics were public. Both were fixed by making Memory Settings
  CRUD/search/merge and detailed system health/metrics admin-only, while
  adding public `/api/v1/health` for liveness probes.
- W5 final fresh local-Docker evidence: sandbox lifecycle regression
  `13 passed`, admin/auth regression `43 passed`, full backend `266 passed,
  4 skipped`, frontend lint/build passed, clean-start probe returned
  `ok: true`, final warmed-pool `spec_complete` eval passed `1 / 1`, public
  liveness returned `{"status":"ok"}`, admin detailed health returned
  `status: ok` with sandbox pool `2`, and direct sandbox-proxy health returned
  `pool_size: 2`, `total_containers: 2`.
- W5 final Windows Chrome settings QA passed with report
  `.gstack/qa-reports/local/settings-2026-06-14T12-12-55-633Z/report.json`:
  all nine Settings sections opened, all required UI actions passed, the real
  chat used the newly selected mock provider once (`mockCalls: 1`), and
  console/page/request/429 errors were all zero.
- W5 final cleanup deleted the temporary tenant
  `w5-final-qa-1781439166`; Redis `*w5*`, `/run/chainless-control`, and the
  W5 database residual scan all returned zero.
- W5 final code-quality re-review by sub-agent Newton returned
  `CODE_QUALITY_REVIEW: PASS` with no Critical or Important findings after the
  memory/system admin-boundary and Provider/Feishu failure-retention fixes.
- W5 final evidence reproducibility follow-up enhanced
  `backend/scripts/production_boundary_probe.py` so the probe itself now
  verifies public liveness `200`, no-auth detailed health/metrics `401`,
  member detailed health/metrics/memory mutation `403`, admin detailed
  health/metrics `200`, real sandbox output `42`, and exact cleanup of its
  temporary tenant.
- W5 follow-up evidence: production config/admin target tests returned
  `17 passed`; full backend returned `266 passed, 4 skipped`; enhanced live
  production boundary probe returned `ok: true` with the complete
  `auth_boundary` matrix and `cleanup: conversation-and-temp-tenant-deleted`;
  DB/Redis/control-socket residue checks returned zero.
- W6 completed the real artifact/files/diff flow: tenant/conversation/run scoped
  artifact metadata, bounded managed content/diff storage, retention/quota and
  orphan cleanup, file-write before/after capture inside `/workspace`, real
  unified diff generation, artifact list/content/diff endpoints, and canonical
  artifact references on tool results.
- W6 frontend work preserved the existing right-panel visual language while
  making Files and Diff render persisted artifacts, keeping empty content/diff
  states truthful, and enforcing the backend preview contract for code/text,
  iframe allowlists, blocked URLs, oversized/binary/missing/deleted states, and
  reload persistence.
- W6 review found and closed five concrete defects: confirmation replay dropped
  artifact references, failed artifact commits could leave orphan files,
  preview allowlisting was not enforced by the content endpoint, empty cached
  content/diffs looked unloaded, and byte truncation could split UTF-8.
- W6 runtime fixes found by verification: Windows browser QA now reads seeded
  admin credentials from `.env` instead of assuming `admin123`, streamed
  LiteLLM tool-call chunks tolerate missing `name`/`arguments`, and artifact
  browser assertions are scoped to the Files panel to avoid strict locator
  ambiguity.
- W6 fresh local-Docker evidence: target backend artifact/security/SSE/LLM tests
  returned `24 passed`; full backend returned `282 passed, 4 skipped`;
  frontend lint passed; frontend production build passed; production
  `backend`, `worker`, `frontend`, and `nginx` images rebuilt and recreated.
- W6 production probes passed after the rebuild: clean-start returned
  `{"ok": true, "migrations": "head", "seed": "idempotent", "login_ready": true}`
  and `production_boundary_probe.py --base-url http://nginx` returned
  `ok: true`, sandbox output `42`, sandbox pool `2/2`, and exact temporary
  cleanup.
- W6 Windows Chrome artifact QA passed at
  `.gstack/qa-reports/local/artifacts-2026-06-14T14-43-26-195Z/report.json`:
  login, mock provider selection, conversation creation, real file-write tool
  loop, Files artifact row, real unified Diff, reload persistence, observed
  two-call tool loop, and conversation cleanup all passed with zero console,
  page, non-ignored request, or 429 errors.
- W6 complexity follow-up moved the artifact browser suite into
  `scripts/qa/artifacts-suite.cjs`, reducing the main Windows QA launcher from
  1239 to 1005 lines and preventing the W6 artifact flow from remaining inside
  the launcher owner.
- W6 cleanup proof returned zero W6 providers, conversations, and artifacts in
  PostgreSQL, no matching `/data/artifacts` files, and no remaining
  `/workspace/w6/w6-artifacts-*.py` browser-QA files after exact-pattern
  cleanup.
- W7 completed the spec-required rich input and keyboard workflow without
  changing the established frontend visual language.
- W7 added `Ctrl+N`, `Ctrl+K`, preserved `Ctrl+Enter`, and verified unsafe
  editable contexts prevent native shortcut side effects while suppressing app
  actions.
- W7 added live tools-API-backed `@tool` picking, real upload-backed `+file`
  attachments, drag/drop upload, attachment injection into chat context, and
  backend security tests for traversal, unsafe filenames, oversized content,
  binary-disallowed content, foreign artifact ids, and deleted historical
  attachment replay.
- W7 replaced the false virtual-scroll marker with real dynamic-height DOM
  windowing and preserved the chat scroll behavior.
- W7 review found and closed five concrete issues: historical uploaded
  attachment replay after deletion, unsafe shortcut `preventDefault` ordering,
  incomplete `@tool` keyboard semantics, false-positive virtual scrolling, and
  multi-file upload partial-success handling. A final ARIA minor was also
  repaired by moving `aria-activedescendant` onto the focused textarea.
- W7 fresh local-Docker evidence: focused backend/artifact/security/SSE tests
  returned `38 passed, 1 warning`; full backend returned `297 passed,
  4 skipped, 1 warning`; frontend lint passed; frontend-test and production
  frontend no-cache builds passed; production frontend and Nginx were recreated;
  public liveness returned `{"status":"ok"}`.
- W7 Windows Chrome rich-input QA passed at
  `.gstack/qa-reports/local/rich-input-2026-06-14T16-29-55-332Z/report.json`:
  auth, mock provider default, shortcut flows, command-palette new
  conversation, keyboard `@tool` selection, file picker upload, drag/drop
  upload, chat with attachment injection, markdown code fold/copy, real virtual
  scrolling, and conversation cleanup all passed with zero console, page,
  request, ignored request, or 429 errors.
- W7 cleanup proof returned zero W7 providers, conversations, and artifacts in
  PostgreSQL, and zero matching `/data/artifacts` files.
- W7 final independent review returned `REVIEW: PASS` with no Critical,
  Important, or Minor findings blocking W7 closure.
- W8 completed proactive pre-authorization, blocked-tool logging, event and
  delayed proactive triggers, real Feishu-compatible delivery proof, eval
  deterministic fallback and CI gate, hallucination/citation/tool evidence
  checks, agent route/budget/circuit-breaker contracts, memory source/index and
  exact five-memory pgvector gate, Redis short-term context, safe instruction
  reload, MCP stdio/HTTP/SSE lifecycle/risk behavior, OpenAI tool-schema
  validation, real filesystem MCP discovery/invocation, risky/destructive
  cancellation evidence, and secret-free metrics.
- W8 found and fixed five runtime/spec gaps during verification: eval failed
  when the default tenant had no configured LLM provider, `run_agent` default
  constants were bound too early for monkeypatched budget tests, sandbox-proxy
  health reported expired idle containers as healthy until first allocation,
  fixed zero-value W8 metrics were upgraded to real runtime/file-backed
  summaries, and an old W5 proactive test task remained in Redis.
- W8 fresh local-Docker evidence: W8 target gate returned `40 passed`; full
  backend returned `325 passed, 4 skipped, 1 warning`; clean-start returned
  `ok: true`; `basic` eval passed `10 / 10`; `spec_complete` eval passed
  `4 / 4`; deliberate impossible threshold `--min-pass-rate 1.1` exited `1`;
  authenticated `/system/metrics` reported eval outcomes as `pass=14`,
  `fail=0`, `error=0`; W8 Feishu/proactive live probe returned `ok: true`;
  proactive Redis inspection returned zero tasks, zero runs, and zero unsafe
  records.
- W8 scope restraint: no frontend file, style, layout, spacing, color, or
  visual-language change was made.
- W9 completed the original three-tenant concurrency/isolation success
  criterion in an isolated local-Docker test environment with fail-closed
  environment guards, exact-prefix tenant creation, at least five concurrent
  chat/tool/memory/provider/channel/proactive operations per tenant,
  cross-tenant denial checks for conversation, artifact, provider, agent,
  memory, skill, proactive task, and MCP/tool scope, and secret-free
  metrics/error checks.
- W9 fixed three runtime/test-boundary defects found by verification: MCP
  manager state was globally visible across tenants, detailed health could
  exceed p95 because sandbox proxy checks reused slow/unresolvable test
  proxy configuration, and DB health used a widening asyncpg pool that could
  create connection storms under concurrent health probes.
- W9 post-review repair removed MCP Tools API `TypeError` fallbacks that could
  retry without tenant owner scope, and expanded the isolation matrix to deny
  cross-tenant provider, agent, and skill mutations plus prove source-resource
  survival.
- W9 fresh local-Docker evidence: exact pytest gate returned `1 passed`;
  final Docker HTTP probe returned `ok: true`, `check_count: 42`,
  `p95_ms: 393.4`, `failures: []`, and `mock_calls: 10`; focused post-review
  gate returned `7 passed`; related regression returned `52 passed`.
- W9 final read-only review found no Critical or Important findings remaining;
  its only Minor test cleanup note was fixed by owner-scoping the API contract
  test's MCP unregister cleanup.
- W9 test-runtime boundary: non-live `backend-test` and `backend-test-server`
  now use a loopback sandbox proxy URL for fast degraded health when the
  live-docker proxy profile is not started; `backend-test-live` explicitly
  keeps `http://sandbox-proxy-test:9001`.
- W9 scope restraint: no frontend file, style, layout, spacing, color, or
  visual-language change was made. `scripts/windows-browser-qa.cjs` was not
  modified because W9 has no browser interaction surface; the standalone
  Docker QA entrypoint is `scripts/qa/multitenant.cjs`.

## Workstream 11 Checkpoint

- W11 completed the final spec-complete QA and evidence bundle in local Docker
  Desktop only. The retired remote server was not used.
- Fresh production compose gate:
  `docker-compose up -d --build` exited `0`; `docker-compose ps` showed
  `chainless-nginx`, db, redis, backend, frontend, worker, sandbox-proxy, and
  sandbox up/healthy where health checks apply.
- Nginx stale upstream repair is verified: after backend rebuild, Nginx stayed
  running and both public health plus in-container Nginx-to-backend health
  returned `{"status":"ok"}`.
- API/runtime probes:
  `clean_start_probe.py` returned migrations `head`, seed `idempotent`, and
  login-ready default admin; `production_boundary_probe.py` returned
  `ok: true`, admin/member/no-auth boundary status codes, body-free audit, and
  sandbox output `42`; `spec_complete_probe.py` returned `ok: true` and
  residue zero.
- Test gates:
  full backend returned `339 passed, 4 skipped, 3 warnings`; frontend lint
  exited `0`; frontend production build exited `0`; W11 probe/sandbox policy
  focused tests returned `13 passed`.
- Browser gate:
  Windows Chrome `spec-complete` through `http://localhost` returned
  `ok: true`, zero console/page/request/429 errors, and cleanup verification.
  Report:
  `.gstack/qa-reports/local/spec-complete-2026-06-15T06-13-38-067Z`.
- Eval gates:
  `basic` passed `10 / 10`; `spec_complete` passed `4 / 4` and logged two
  real parallel `spawn_sub_agent` artifacts from Code-as-Action.
- Backup/restore:
  backup produced `/backups/chainless-20260615-061030.sql` (212K);
  `restore_drill.py` restored into `chainless_restore_drill_989008f95c3b`,
  verified default seed plus fixture records, then dropped the restore DB and
  removed the dump/source fixture.
- Performance:
  Fibonacci Code-as-Action returned exact stdout `55`; HackerNews top-10
  Code-as-Action ran one warmup plus five measured runs with max `757.6ms` and
  p50 `707.61ms`, each below `5000ms` with sandbox
  `allocated/completed/deleted` evidence.
- Cleanup:
  Postgres QA-prefix residue counts returned zero across tenant, user,
  provider, agent, conversation, message, memory, skill, artifact, tool config,
  channel config, and confirmation tables. Redis scan showed no QA-prefix keys.
- External proof boundaries:
  current local Docker has `GLM_API_KEY_SET|False`, `default_providers|0`, and
  `all_providers|0`, so W11 verifies the configurable OpenAI-compatible
  provider runtime with disposable mock providers and does not claim a live GLM
  API call. Real Feishu group receipt remains credential-dependent by the
  approved reconciliation.
- Scope restraint:
  W11 did not modify frontend styles, visual language, layout intent, scroll
  behavior, or user-facing design. Browser script changes are QA logic only.
- W11 stop condition:
  all implementation/testable local-Docker spec-complete gates are evidenced,
  no QA data remains, and the remaining non-claims are explicit
  external-credential proof boundaries rather than hidden work items.

## Evidence Refs

- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `docs/aegis/specs/2026-06-04-chainless-v1-complete-spec-reconciliation.md`
- `docs/aegis/plans/2026-06-03-spec-runtime-gap-matrix.md`
- `docs/aegis/plans/2026-06-03-spec-gap-closure-checklist.md`
- `PROBLEM_TODO_LIST.md`
- `docs/aegis/work/2026-06-05-v1-spec-completion/90-evidence.md`

## Blocked On

None.

## Runtime Boundary

- Use only local Docker Desktop and local Docker Compose.
- Do not connect to or retry the retired remote server.
- Do not run project Python or Node directly on the Windows host.
- Local Windows browser automation remains permitted for later QA.

## Next Step

Run final diff/review closeout and do not commit or push unless the user
explicitly asks.

## Resume State Hint

Resume by reading this checkpoint, the W11 section of the parent execution
plan, `90-evidence.md`, and `original-gate-ledger.md`. W1, W2, W3, W4, W5,
W6, W7, W8, W9, W10, and W11 are closed by local-Docker evidence, except that
live GLM and real Feishu group receipt remain external-credential proof
boundaries.

## Drift Check

- Original intent served: yes
- Mandatory order preserved: yes
- Compatibility boundary preserved: yes
- New owner/fallback introduced: W8 intentionally adds
  `backend/app/core/memory/short_term.py`,
  `backend/app/core/observability/runtime_metrics.py`,
  `backend/app/core/tools/schema.py`,
  `backend/scripts/w8_feishu_proactive_probe.py`, and
  `.github/workflows/eval.yml` as focused owners for short-term Redis context,
  tool-schema validation, live W8 Feishu/proactive proof, and eval CI. W8 also
  adds `backend/scripts/mcp_filesystem_server.py` as the real filesystem MCP
  verification fixture for the original `mcp__fs__list_directory` gate.
  Runtime metrics are intentionally in-process plus file-backed for eval
  results, and do not store prompts, responses, webhook URLs, or secrets. The
  deterministic eval gateway is retained only as a no-secret eval fallback when
  a default provider is absent; real chat runtime still uses configured DB
  providers. W9 intentionally adds `backend/scripts/assert_test_environment.py`,
  `backend/scripts/multitenant_probe.py`, `backend/tests/test_multitenant_concurrency.py`,
  and `scripts/qa/multitenant.cjs` as isolated test/probe owners. W9 also
  adds tenant-aware MCP manager scoping and bounded realtime health probes; the
  old global MCP manager visibility is retired for tenant-authenticated paths.
- Retirement track explicit: yes
- Evidence sufficient for next action: yes
- Decision: Workstream 11 implementation/QA closed; continue to final review
  and handoff without committing.
