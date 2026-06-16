# W12 File Task Closure Checkpoint

Updated: 2026-06-15 W12 implementation and verification complete

## TodoCheckpointDraft

Current todo:
- Ask user whether to create ADR/backfill for the artifact-source-of-truth and
  run-workspace boundary.
- Ask user whether to commit. No commit is created without explicit approval.

Completed todos:
- W12 spec written.
- W12 detailed execution plan written.
- Task 1 backend artifact download contract.
- Task 2 backend message attachment metadata contract.
- Task 3 run-scoped workspace materialization owner.
- Task 4 chat runtime integration and fail-closed attachment handling.
- Task 5 frontend file state, sent cards, download, and Settings navigation.
- Task 6 W12 browser QA suite and cleanup.
- Task 7 final W12 verification and problem ledger update.

Active slice:
- Completion candidate / user handoff.

Evidence refs:
- Task 1 RED: targeted download test failed with missing `/download` route.
- Task 1 GREEN: targeted download test returned `1 passed`.
- Task 1 regression: `tests/test_artifacts.py tests/test_file_upload_security.py`
  returned `19 passed`.
- Task 1 review finding: non-ASCII workspace filename header safety fixed;
  targeted download edge tests returned `2 passed`.
- Task 2 RED: conversation detail test failed with missing `attachments`.
- Task 2 GREEN: conversation detail test returned `1 passed`.
- Task 3 RED: materializer missing and stale global workspace exposed.
- Task 3 GREEN: materializer/file-list tests returned `2 passed`.
- Task 3 regression: `tests/test_artifacts.py` returned `3 passed`.
- Task 4 RED/GREEN: chat attachment file-read and materialization fail-closed
  tests returned `2 passed`.
- Task 4 regression: `tests/test_sse_contract.py tests/test_file_upload_security.py tests/test_artifacts.py`
  returned `31 passed`.
- Task 5 frontend lint/build returned success in Docker.
- Task 6 first browser QA found Settings sidebar conversation loading gap.
- Task 6 rerun browser QA `file-task-closure` returned `ok: true`, zero
  console/page/request/429 errors, real `file_read`, download bytes match, and
  cleanup provider/conversation `ok: true`.
- Task 7 full backend returned `346 passed, 4 skipped`.
- Task 7 frontend lint/build returned success in Docker.
- Local Docker health returned `{"status":"ok"}` before browser QA.

Blocked-on:
- User decision on ADR/backfill and commit.

Next step:
- Present W12 evidence and request ADR/commit direction.

## DriftCheckDraft

Scope: aligned with W12 spec and plan.

Compatibility:
- Current branch is `codex/v1-spec-completion`, not `main/master`.
- No additional worktree is opened because W12 spec/plan are uncommitted and
  the user has not requested a commit.
- Frontend style must not be redesigned.
- Local Docker Desktop remains runtime source of truth.

Retirement:
- Global `/workspace` fallback remains only as non-chat/test compatibility.
- Chat runtime must move to per-run workspace context before W12 closes.

Decision: completion-candidate.

## DriftCheckDraft - Task 1

Scope: artifact download endpoint only.

Compatibility:
- Existing artifact content/diff/list tests still pass.
- No frontend style touched.
- No commit created.

Retirement:
- No old download path existed.

Decision: continue.

## DriftCheckDraft - Tasks 2-3

Scope: backend message attachment metadata and run workspace materialization.

Compatibility:
- Existing prompt content injection remains.
- Existing artifact tests still pass.
- Global file tool fallback remains for non-chat/test compatibility.
- Chat runtime has not yet been switched to workspace context; Task 4 owns that.

Retirement:
- Static global `/workspace` is now bypassable via `context.workspace_base`;
  chat runtime retirement of global fallback is still pending.

Decision: continue.

## DriftCheckDraft - Tasks 4-7

Scope: W12 file task closure only.

Compatibility:
- Frontend style/theme/layout files were not changed.
- Existing attachment chip, Files panel, Sidebar, and zinc visual language are
  reused.
- Existing artifact metadata/content/diff endpoints remain compatible.
- Chat keeps historical attachment prompt content as compatibility context while
  adding the canonical tool-readable run workspace.
- QA-created conversation and provider were deleted by the browser suite.

Retirement:
- Chat runs no longer rely on global `/workspace` for attached file reads.
- The global workspace fallback remains for direct non-chat/test usage only.
- Chat-only memory of file-closure issues is retired into
  `PROBLEM_TODO_LIST.md`, this checkpoint, and the evidence file.

Decision: completion-candidate.
