# W12 File Task Closure Execution Plan

Status: Ready for user execution approval
Type: Workstream 12 Implementation Plan
Created: 2026-06-15
Approved Spec: `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`

## Goal

Close the file task loop for Chainless: upload -> explicit attachment state ->
sent-message attachment -> agent-readable clean run workspace -> generated
artifact -> preview and download -> fail-closed if the input file is not usable.

This plan selects the W12 spec recommendation: artifact storage is the canonical
file source of truth, and `/workspace` is a derived per-run execution view.

## Architecture

```text
User file upload
  |
  v
Artifact row + managed artifact bytes
  |
  | message attachment IDs
  v
Conversation message metadata
  |
  | before agent run
  v
Run workspace materializer
  |
  v
/workspace/runs/<run_id>/input/<artifact_id>/<safe_name>
/workspace/runs/<run_id>/output/...
  |
  | context.workspace_base passed to file tools
  v
file_read / file_list / file_write
  |
  v
Captured output artifact rows
  |
  v
Files panel preview + download
```

Owner boundaries:

- Durable artifacts: `backend/app/core/artifacts/service.py`
- Run workspace materialization: new `backend/app/core/artifacts/workspace.py`
- Artifact API and download authorization: `backend/app/api/v1/artifacts.py`
- Chat attachment validation and message serialization:
  `backend/app/api/v1/conversations.py`
- Agent stream workspace context propagation:
  `backend/app/services/conversation_stream_service.py`
  and `backend/app/core/agent/engine.py`
- File tool workspace scoping:
  `backend/app/core/tools/builtin/file_ops.py`
- Frontend attachment state and sent-message rendering:
  `frontend/src/components/chat/file-attachment.tsx`,
  `frontend/src/components/chat/input-area.tsx`,
  `frontend/src/components/chat/message-bubble.tsx`,
  `frontend/src/stores/chat-store.ts`
- Files panel download:
  `frontend/src/components/chat/file-artifact-list.tsx`,
  `frontend/src/stores/artifact-store.ts`,
  `frontend/src/lib/api.ts`
- Settings sidebar navigation:
  `frontend/src/components/layout/sidebar.tsx`

## Tech Stack

- Backend: FastAPI, SQLAlchemy async, PostgreSQL, local Docker test profile
- Frontend: Next.js, React, Zustand, current Tailwind/zinc visual system
- Runtime: Docker Compose on local Docker Desktop only
- QA: Windows browser QA via `scripts/windows-browser-qa.ps1`

## Baseline / Authority Refs

- `docs/aegis/specs/2026-06-15-file-task-closure-brief.md`
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `PROBLEM_TODO_LIST.md`
- `AGENTS.md`

## Compatibility Boundary

- Do not redesign frontend style, spacing, colors, scroll behavior, or chat
  visual language.
- Reuse existing attachment chip, message bubble, Files panel, and sidebar
  visual patterns.
- Preserve artifact list, content, and diff endpoint behavior.
- Preserve tenant, conversation, quota, retention, preview-security, and upload
  content policy constraints.
- Use local Docker Desktop for application runtime and backend tests.
- Use Windows only as browser automation/control plane.
- Do not use host Python or host Node as the application runtime.
- Do not commit unless the user explicitly asks for a commit.
- QA-created conversations, providers, and artifacts must be removed by the QA
  suite after verification.

## Verification

Targeted backend:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py tests/test_file_upload_security.py tests/test_artifacts.py"
```

Full backend:

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
```

Frontend:

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Local runtime:

```powershell
docker-compose up -d --build
curl.exe -fsS http://127.0.0.1/api/v1/health
docker-compose ps
```

Browser QA:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost `
  -Browser chrome -Headless `
  -Suite file-task-closure `
  -TimeoutMs 120000
```

Expected browser QA result: JSON report with `ok: true`, zero uncaught page
errors, zero console errors, zero request failures except ignored RSC/favicon
aborts, and cleanup evidence for every created conversation/provider.

## Plan Basis

### Facts

- Uploads already persist text files as artifact rows under the managed artifact
  volume.
- `Message.meta_data.attachment_artifact_ids` stores selected upload artifact
  IDs.
- Conversation history currently injects attachment content into the LLM prompt,
  but it does not materialize the same file into a tool-readable workspace path.
- Builtin file tools currently resolve paths against global
  `FILE_TOOLS_BASE_DIR`, which is `/workspace` in Compose.
- `/workspace` is a shared Docker volume for backend/worker and can contain old
  QA files such as W6 artifact test output.
- Artifact preview and diff endpoints exist; a download endpoint does not.
- Frontend `Message` does not carry attachment metadata, so sent messages cannot
  render attachment cards after send/reload.
- Sidebar conversation click selects store state but does not route from
  `/settings` to `/chat`.

### Assumptions

- W12 does not require a database migration; new file metadata can live in
  artifact `metadata` and message `metadata`.
- The public path shown for file_write artifacts remains the path requested by
  the agent relative to the current run workspace, not the physical
  `/workspace/runs/<run_id>/...` path.
- The file tool root can be made context-specific without changing public tool
  schemas.
- Browser QA can use disposable OpenAI-compatible mock providers like the W6/W7
  suites.

### Unknowns To Resolve During Execution

- Whether `docker-compose run --rm frontend` is fast enough on this machine for
  every checkpoint. If not, use targeted lint/build once before final QA, but do
  not skip final frontend verification.
- Whether a typed fail-closed attachment error is better surfaced as an SSE
  `error` event or an immediate HTTP API error. The plan chooses SSE `error` for
  stream consistency when the request reaches chat streaming, and HTTP errors
  for validation failures before a stream is opened.

## Ripple Signal Triage

Public API signal:

- Add `GET /api/v1/artifacts/{artifact_id}/download`.
- Extend conversation message response with `attachments`.

Runtime owner signal:

- Add run workspace materialization owner.
- Pass `workspace_base` through stream service and agent tool context.

Security signal:

- Download must enforce tenant/conversation/user ownership and safe storage path.
- File tools must reject traversal outside the current run workspace.

Frontend signal:

- Message type expands to include attachments.
- Existing visual system must remain unchanged except for state/action content.

QA signal:

- Add a new browser suite and register it in both the JS registry flow and the
  PowerShell `ValidateSet`.

## Architecture Integrity Lens

Invariant: a user-visible file has one durable identity and may have temporary
runtime paths, but runtime paths never become the source of truth.

Canonical owner / contract:

- Artifact service owns durable metadata and bytes.
- Workspace materializer owns derived run directories and input path mapping.
- File tools consume `workspace_base` and do not decide what files are attached.

Responsibility overlap:

- Current upload path hints look like workspace paths but are not readable by
  file tools.
- Current prompt injection lets the model see file text while tools cannot read
  the file object.

Higher-level simplification:

- Use artifact ID as durable identity.
- Use run-scoped workspace paths as disposable runtime aliases.

Retirement / falsifier:

- Retire reliance on global `/workspace` for normal chat file tools.
- Any `file_list(".")` result that includes old W6/QA files from outside the
  current run fails W12.

Verdict: proceed with Option B from the W12 spec.

## Plan Pressure Test

Owner / contract / retirement:

- New owner is justified because neither `conversations.py` nor `file_ops.py`
  should own artifact-to-workspace materialization.
- Global `/workspace` remains a fallback only when no run workspace is provided
  for non-chat direct tests; chat execution must provide `workspace_base`.

Architecture integrity / higher-level path:

- Source of truth stays artifact storage.
- Workspace stays derived and disposable.

Verification scope:

- Backend tests cover download, attachments, materialization, stale isolation,
  fail-closed behavior, and tenant boundaries.
- Browser QA covers upload state, sent card, real file_read, output download,
  Settings navigation, and cleanup.

Task executability:

- Tasks are separable by backend contract, runtime materialization, frontend
  state, QA harness, and final verification.

Pressure result: proceed.

## Plan-Time Complexity Check

Target files:

- `backend/app/api/v1/conversations.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/tools/builtin/file_ops.py`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/components/chat/message-bubble.tsx`
- `frontend/src/components/chat/input-area.tsx`

Existing size / shape signals:

- `conversations.py` already mixes CRUD, chat setup, attachment validation, and
  message serialization.
- `chat-store.ts` already owns streaming, tool events, confirmations, and
  conversation state.
- `file_ops.py` is compact but currently treats the environment workspace root
  as static global configuration.

Owner fit:

- Add `backend/app/core/artifacts/workspace.py` for materialization and cleanup.
- Add small serialization helpers in `conversations.py`, but do not move full
  chat orchestration there.
- Keep frontend changes at component/store seams and reuse existing classes.

Add-in-place risk:

- Adding run materialization directly to `conversations.py` would increase an
  already high-pressure API route.
- Adding attachment state ownership directly to `InputArea` only would lose
  sent/reload behavior.

Better file boundary:

- New backend workspace materialization owner.
- Existing artifact API owner for download.
- Existing message bubble/attachment component owner for display.

Recommendation: add owner file, edit in place only at contract seams.

## Files

Create:

- `backend/app/core/artifacts/workspace.py`
- `backend/tests/test_file_task_closure.py`
- `scripts/qa/file-task-closure-suite.cjs`

Modify:

- `backend/app/core/artifacts/__init__.py`
- `backend/app/core/artifacts/service.py`
- `backend/app/api/v1/artifacts.py`
- `backend/app/api/v1/conversations.py`
- `backend/app/services/conversation_stream_service.py`
- `backend/app/core/agent/engine.py`
- `backend/app/core/tools/builtin/file_ops.py`
- `backend/tests/test_artifacts.py`
- `backend/tests/test_file_upload_security.py`
- `frontend/src/lib/api.ts`
- `frontend/src/stores/artifact-store.ts`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/components/chat/file-attachment.tsx`
- `frontend/src/components/chat/input-area.tsx`
- `frontend/src/components/chat/message-bubble.tsx`
- `frontend/src/components/chat/file-artifact-list.tsx`
- `frontend/src/components/layout/sidebar.tsx`
- `scripts/windows-browser-qa.ps1`
- `scripts/windows-browser-qa.cjs`
- `PROBLEM_TODO_LIST.md`
- `docs/aegis/plans/2026-06-15-w12-file-task-closure-execution-plan.md`

Do not modify style theme files or broad layout files.

## Task 1: Backend Artifact Download Contract

### Files

- Create/modify: `backend/tests/test_file_task_closure.py`
- Modify: `backend/app/core/artifacts/service.py`
- Modify: `backend/app/core/artifacts/__init__.py`
- Modify: `backend/app/api/v1/artifacts.py`

### Why

Generated files are not useful if the user can preview them but cannot retrieve
the bytes. Download is part of file task closure.

### Impact / Compatibility

- Adds a new endpoint without changing existing metadata/content/diff endpoints.
- Reuses artifact authorization and storage path safety.
- Does not expose artifact storage paths.

### Repair Track

Root cause: artifact API supports preview but not delivery.

Canonical owner: `backend/app/api/v1/artifacts.py` authorizes requests;
`backend/app/core/artifacts/service.py` safely resolves stored bytes.

Minimal stable repair:

- Add `read_artifact_bytes(artifact, content_kind="content") -> bytes`.
- Add `artifact_download_filename(artifact) -> str`.
- Add `GET /api/v1/artifacts/{artifact_id}/download`.
- Return `FileResponse` or `Response` with safe headers.

### Retirement Track

Old owner/fallback: none.

Deletion trigger: no deletion needed.

### Verification

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary"
```

Expected output includes `1 passed`.

### Steps

- [x] Write RED test `test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary` in `backend/tests/test_file_task_closure.py`. The test must upload `w12-download.txt` with bytes `download me\n`, call `/api/v1/artifacts/{id}/download`, assert status `200`, body bytes match, `content-disposition` contains `attachment`, `content-type` starts with `text/plain`, and tenant B gets `404 ARTIFACT_NOT_FOUND`.
- [x] Verify RED with the targeted pytest command above and confirm failure is a missing route or missing helper, not fixture setup.
- [x] Implement minimal backend code. Export read/download helpers from artifact service, use `_get_owned_artifact`, reject non-available artifacts with `409 ARTIFACT_NOT_DOWNLOADABLE`, and never return absolute filesystem paths.
- [x] Verify GREEN with the targeted pytest command and then run `tests/test_artifacts.py tests/test_file_upload_security.py` to catch preview/upload regressions.
- [x] Checkpoint diff and evidence. Do not commit unless the user explicitly asks.

Task 1 evidence:

- RED: targeted W12 download test failed with `404 {"detail":"Not Found"}`.
- GREEN: targeted W12 download test returned `1 passed`.
- Regression: `tests/test_artifacts.py tests/test_file_upload_security.py` returned
  `19 passed`.
- Review finding closed: generated artifact names with non-ASCII workspace paths
  now use an ASCII-only `filename=` fallback and UTF-8 percent-encoded
  `filename*=`. Targeted edge test returned `2 passed` with the original
  download test.

## Task 2: Message Attachment Metadata Contract

### Files

- Modify: `backend/tests/test_file_task_closure.py`
- Modify: `backend/app/api/v1/conversations.py`
- Modify: `frontend/src/stores/chat-store.ts`
- Modify: `frontend/src/components/chat/message-bubble.tsx`
- Modify: `frontend/src/components/chat/file-attachment.tsx`

### Why

The product must show that a file was sent with a message after send and after
reload. Input-only attachment chips are not enough.

### Impact / Compatibility

- Extends message JSON with `attachments`.
- Keeps `content`, `role`, `id`, and `created_at` stable.
- Reuses existing attachment visual style; no redesign.

### Repair Track

Root cause: attachments are persisted in `Message.meta_data` but not serialized
back to the frontend message model.

Canonical owner: backend message serializer provides attachment metadata;
frontend message bubble renders it.

Minimal stable repair:

- Add `_serialize_message(message, current_user, attachments_by_message=None)`.
- Add `_serialize_message_attachments(...)`.
- Include `attachments` for user messages with valid attachment IDs.
- Add `Message.attachments?: StreamArtifact[]` in the frontend store.
- Render attachments below user message content using `AttachmentChip` or a
  style-preserving read-only variant.

### Retirement Track

Old owner/fallback: optimistic user messages without attachments.

Keep reason: optimistic message stays for latency, but must include selected
attachment metadata available client-side.

### Verification

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_conversation_detail_returns_sent_attachment_metadata"
```

Expected output includes `1 passed`.

### Steps

- [x] Write RED test `test_conversation_detail_returns_sent_attachment_metadata`. It must upload a file, send a chat message with that artifact ID using a mock gateway that returns text only, then `GET /api/v1/conversations/{id}` and assert the user message has `attachments[0].id`, `path`, `state`, `operation == "upload"`, and `download_url`.
- [x] Verify RED and confirm conversation detail lacks `attachments`.
- [x] Implement backend message serialization and add `download_url` to serialized artifact metadata or attachment metadata. Do not remove existing content injection yet.
- [x] Implement frontend type/render changes. Optimistic user messages must include selected attachment metadata by resolving IDs from `artifact-store`; reloaded messages must render backend attachments. Add a read-only attachment chip state `sent`.
- [x] Verify GREEN with the backend test, then run frontend lint/build after Task 5 when all frontend W12 changes are in place.

Task 2 backend evidence:

- RED: targeted conversation detail test failed with `KeyError: 'attachments'`.
- GREEN: targeted conversation detail test returned `1 passed`.
- Frontend portion is implemented under Task 5 by the frontend worker and will
  be reverified in Task 5/final verification.

## Task 3: Run-Scoped Workspace Materialization Owner

### Files

- Create: `backend/app/core/artifacts/workspace.py`
- Modify: `backend/app/core/artifacts/__init__.py`
- Modify: `backend/app/core/tools/builtin/file_ops.py`
- Modify: `backend/tests/test_file_task_closure.py`

### Why

Uploaded files live in artifact storage while file tools read `/workspace`.
The agent needs a clean, deterministic per-run view of selected artifacts.

### Impact / Compatibility

- Public tool schemas stay unchanged.
- Non-chat test usage can still fall back to `FILE_TOOLS_BASE_DIR`.
- Chat execution must pass `workspace_base`.
- No global `/workspace` deletion is required.

### Repair Track

Root cause: file tools use a global workspace root that is not tied to the
current message attachments.

Canonical owner: `backend/app/core/artifacts/workspace.py`.

Minimal stable repair:

- Add `RunWorkspace` dataclass with `run_id`, `base_path`, `input_paths`, and
  `summary_for_prompt`.
- Add `prepare_run_workspace(run_id, artifacts, root=None)`.
- Copy available artifact content into
  `/workspace/runs/<run_id>/input/<artifact_id>/<safe_name>`.
- Add `cleanup_run_workspace(run_id, root=None)` for bounded cleanup of this
  run path only.
- Update `file_ops.py` to resolve base from `context["workspace_base"]` when
  present; otherwise use environment fallback.

### Retirement Track

Old owner/fallback: static `_ALLOWED_BASE = /workspace`.

Keep reason: safe fallback for direct unit tests and non-chat tooling.

Retirement condition: once all callers pass `workspace_base`, fallback can be
restricted to test utilities.

### Verification

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_run_workspace_materializes_upload_and_file_tools_are_run_scoped tests/test_file_task_closure.py::test_file_list_does_not_expose_stale_global_workspace_files"
```

Expected output includes `2 passed`.

### Steps

- [x] Write RED tests. One test must create an uploaded artifact, call the materializer with a fixed run ID, then call `file_read` using context `workspace_base` and assert uploaded bytes are read from the generated input path. The stale test must create a file under the global workspace root outside the run directory, call `file_list "."` with `workspace_base` set to the run directory, and assert the stale filename is absent.
- [x] Verify RED and confirm missing materializer/context root behavior.
- [x] Implement `workspace.py` and context-aware base resolution in `file_ops.py`. Ensure traversal rejection compares against the resolved per-run base, not global `/workspace`.
- [x] Verify GREEN with the targeted tests, then run existing `tests/test_artifacts.py` because `file_write` artifact capture uses relative paths.
- [x] Checkpoint diff and evidence. Do not commit unless the user explicitly asks.

Task 3 evidence:

- RED: targeted materializer/file-list tests failed with missing
  `app.core.artifacts.workspace` and stale global workspace exposure.
- GREEN: targeted materializer/file-list tests returned `2 passed`.
- Regression: `tests/test_artifacts.py` returned `3 passed`.

## Task 4: Chat Runtime Integration and Fail-Closed Attachment Handling

### Files

- Modify: `backend/tests/test_file_task_closure.py`
- Modify: `backend/app/api/v1/conversations.py`
- Modify: `backend/app/services/conversation_stream_service.py`
- Modify: `backend/app/core/agent/engine.py`
- Modify: `backend/app/core/tools/builtin/file_ops.py`

### Why

The agent must actually use the uploaded file through tools, and must stop when
attachments are unavailable instead of improvising.

### Impact / Compatibility

- Normal chat streaming remains SSE.
- Tool events remain canonical.
- Attachment validation before stream remains HTTP `409` for unavailable IDs.
- Materialization failures inside stream become SSE `error` with code
  `ATTACHMENT_MATERIALIZATION_FAILED`.

### Repair Track

Root cause: chat validates attachments and prompt-injects content, but does not
connect attachment IDs to the tool runtime.

Canonical owner: conversation route validates message intent; stream service
owns run setup; agent engine passes `workspace_base` to tools.

Minimal stable repair:

- Pass validated attachments or attachment IDs from `chat()` into
  `build_chat_stream_response`.
- Create the `run_id` before materialization.
- Prepare run workspace before starting `run_agent_stream`.
- Add a system/context message listing exact readable file paths.
- Pass `workspace_base` into `run_agent_stream`, `run_agent`, and every
  `execute_tool` context.
- On materialization failure, emit SSE error and do not call the LLM.

### Retirement Track

Old owner/fallback: `_message_content_with_attachments` embeds attachment
content directly into prompt history.

Keep reason: it helps context and preserves previous behavior.

Retirement condition: after file-read path is proven robust, direct content
injection may be reduced to a manifest-only prompt if token pressure becomes an
issue. W12 does not remove it.

### Verification

```powershell
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_chat_attachment_is_readable_through_file_read_tool tests/test_file_task_closure.py::test_attachment_materialization_failure_fails_closed_before_llm_call"
```

Expected output includes `2 passed`.

### Steps

- [x] Write RED test `test_chat_attachment_is_readable_through_file_read_tool`. The mock gateway must inspect the first LLM call, find the manifest path, request `file_read` for that path, then on the second call answer with a phrase from the tool result. Assert SSE contains `tool_call file_read`, `tool_result` with uploaded bytes, and final text.
- [x] Write RED test `test_attachment_materialization_failure_fails_closed_before_llm_call`. Force the artifact content path missing or monkeypatch materializer to raise. Assert SSE error code `ATTACHMENT_MATERIALIZATION_FAILED` and assert mock gateway call count is zero.
- [x] Verify RED with the targeted command.
- [x] Implement stream integration and context propagation. Do not let `file_list` or `file_read` run against global `/workspace` during chat.
- [x] Verify GREEN with targeted tests, then run `tests/test_sse_contract.py tests/test_file_upload_security.py tests/test_artifacts.py` to catch stream and upload regressions.
- [x] Checkpoint diff and evidence. Do not commit unless the user explicitly asks.

## Task 5: Frontend File State, Sent Cards, Download, and Settings Navigation

### Files

- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/stores/artifact-store.ts`
- Modify: `frontend/src/stores/chat-store.ts`
- Modify: `frontend/src/components/chat/file-attachment.tsx`
- Modify: `frontend/src/components/chat/input-area.tsx`
- Modify: `frontend/src/components/chat/message-bubble.tsx`
- Modify: `frontend/src/components/chat/file-artifact-list.tsx`
- Modify: `frontend/src/components/layout/sidebar.tsx`

### Why

The UI must make file lifecycle visible, let users download outputs, and route
conversation clicks from Settings back to Chat.

### Impact / Compatibility

- Preserve current zinc/dark visual style.
- Preserve sidebar rename/archive controls.
- Preserve chat scroll and virtualization behavior.
- Do not introduce new layout theme or design language.

### Repair Track

Root causes:

- Input attachments only appear after upload success.
- Sent messages lack attachment metadata.
- Files panel lacks download action.
- Sidebar selection does not navigate from Settings.

Canonical owners:

- `InputArea` owns pending upload state.
- `MessageBubble` owns sent message attachment display.
- `FileArtifactList` owns file panel actions.
- `Sidebar` owns navigation on conversation click.

Minimal stable repair:

- Track pending attachments as `uploading`, `available`, and `failed`.
- Prevent send while any attachment is `uploading` or `failed`.
- Preserve sent attachments in optimistic user messages and reloaded messages.
- Add `api.downloadArtifactUrl(id)` or `api.downloadArtifact(id)` with token-safe
  fetch/blob download behavior.
- Add a download button/link in the existing Files panel row/detail area.
- Change sidebar conversation click to select conversation and push `/chat`
  when `pathname !== "/chat"`.

### Retirement Track

Old owner/fallback: user can infer upload completion from chip existence.

Deletion trigger: replace inference with explicit state text.

### Verification

```powershell
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Expected output includes successful lint and production build.

### Steps

- [x] Add type support for `Message.attachments` and `StreamArtifact.download_url`. Add API helper for artifact download. Do not change base URL logic.
- [x] Update `InputArea` state transitions so chips appear immediately as `uploading`, become `available` on success, become `failed` on error, and prevent send until all selected files are available.
- [x] Update `sendMessage` optimistic message creation to attach selected artifact metadata from `artifact-store`; after send, state renders as `sent`.
- [x] Update `MessageBubble` to render sent attachments below user content using existing `AttachmentChip` classes or a read-only variant. No new theme or layout redesign.
- [x] Update `FileArtifactList` to expose a download action for available artifacts using existing button/link styling.
- [x] Update `Sidebar` conversation click to `await selectConversation(conv.id)` and navigate to `/chat` if currently outside `/chat`.
- [x] Run frontend lint/build. If it fails, fix only W12-related TypeScript/lint errors and rerun.
- [x] Checkpoint diff and evidence. Do not commit unless the user explicitly asks.

## Task 6: W12 Browser QA Suite and Cleanup

### Files

- Create: `scripts/qa/file-task-closure-suite.cjs`
- Modify: `scripts/windows-browser-qa.cjs`
- Modify: `scripts/windows-browser-qa.ps1`

### Why

W12 must be proven through the real Windows browser path, not only backend unit
tests.

### Impact / Compatibility

- Adds a new suite name `file-task-closure`.
- Leaves existing suites unchanged.
- Cleans every QA-created conversation/provider in `finally`.

### Repair Track

Root cause: no browser QA currently verifies upload -> tool read -> output
download -> Settings navigation as one product loop.

Canonical owner: `scripts/qa/file-task-closure-suite.cjs` owns W12 browser
scenario; `windows-browser-qa.cjs` only registers and dispatches it.

Minimal stable repair:

- Create a mock OpenAI-compatible provider.
- Upload a local text file through the browser.
- Assert visible attachment states.
- Send a message that makes the mock model call `file_read` using the manifest
  path, then `file_write` an output file.
- Open Files panel and download the output artifact.
- Visit Settings, click a conversation, assert URL is `/chat`.
- Clean all created conversations and provider records.

### Retirement Track

Old owner/fallback: W6 artifacts suite and W7 rich input suite each cover part
of the flow.

Keep reason: they remain narrower regression suites.

### Verification

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 `
  -Url http://localhost `
  -Browser chrome -Headless `
  -Suite file-task-closure `
  -TimeoutMs 120000
```

Expected report includes steps:

- `auth-login`
- `mock-provider-default`
- `conversation-create`
- `upload-state-available`
- `sent-message-attachment-visible`
- `file-read-tool-used`
- `generated-artifact-visible`
- `artifact-download-bytes-match`
- `settings-sidebar-navigates-chat`
- `cleanup-conversations`
- `cleanup-provider`

### Steps

- [x] Add the suite file using the W6/W7 mock provider and cleanup patterns.
- [x] Register `file-task-closure` in `windows-browser-qa.cjs` with `registerSuite(...)` and add it to the PowerShell `ValidateSet`. Do not modify `scripts/qa/suite-registry.cjs`; it already accepts arbitrary registered suite names.
- [x] Run the suite against local Docker after Tasks 1-5 are green.
- [x] If the suite leaves data behind, fix cleanup before considering W12 complete.
- [x] Checkpoint report directory path and evidence. Do not commit unless the user explicitly asks.

## Task 7: Final W12 Verification, Problem Ledger, and ADR Signal

### Files

- Modify: `PROBLEM_TODO_LIST.md`
- Modify: `docs/aegis/plans/2026-06-15-w12-file-task-closure-execution-plan.md`
- Create or modify ADR only if user approves ADR backfill after implementation

### Why

W12 must close without tail items. Findings discovered inside W12 must be
recorded, fixed, and reverified.

### Impact / Compatibility

- Keeps project state auditable.
- Does not claim weather/search/booking production completion.
- Does not commit without explicit user request.

### Repair Track

Root cause: previous workstreams marked artifact/file features complete while a
cross-layer file task closure gap remained.

Canonical owner: W12 plan and problem ledger record evidence and remaining
boundaries.

Minimal stable repair:

- Update `PROBLEM_TODO_LIST.md` with W12 findings and mark each resolved with
  evidence.
- Add execution evidence to this plan after implementation.
- Preserve ADR signal: artifact source of truth and derived run workspace.

### Retirement Track

Old owner/fallback: informal memory of W12 issues in chat.

Deletion trigger: once ledger and plan evidence are updated, chat-only state is
not needed as authority.

### Verification

Run all commands from the Verification section. Expected:

- Targeted backend W12 tests pass.
- Full backend tests pass.
- Frontend lint/build pass.
- Local Docker health is `{"status":"ok"}`.
- Browser QA `file-task-closure` returns `ok: true`.
- QA cleanup evidence shows no W12 conversation/provider residue.

### Steps

- [x] Run targeted backend W12 tests.
- [x] Run full backend tests.
- [x] Run frontend lint/build.
- [x] Rebuild local Docker and verify health.
- [x] Run W12 browser QA.
- [x] Update `PROBLEM_TODO_LIST.md` with every W12 issue found and resolved.
- [x] Update this plan with evidence paths and explicit W12 closed status only when all stop conditions pass.
- [x] Ask the user whether to create the ADR/backfill and whether to commit. Do not commit without explicit approval.

## Stop Condition

Execution status: implementation stop condition satisfied on 2026-06-15.

Evidence:

- Targeted W12 backend tests: `tests/test_file_task_closure.py` returned
  `7 passed`.
- Related backend target gate:
  `tests/test_file_task_closure.py tests/test_file_upload_security.py tests/test_artifacts.py`
  returned `26 passed`.
- Full backend: `pytest -q` returned `346 passed, 4 skipped`.
- Frontend: `npm run lint && npm run build` passed in Docker.
- Local runtime: `docker-compose up -d --build` completed; backend health
  returned `{"status":"ok"}`.
- Browser QA:
  `.gstack/qa-reports/local/file-task-closure-2026-06-15T08-20-20-357Z/report.json`
  returned `ok: true`, zero console/page/request/429 errors, real `file_read`,
  download byte match, Settings navigation, and cleanup evidence.
- Problem ledger: `PROBLEM_TODO_LIST.md` records W12 findings and resolutions.

ADR/commit boundary:

- W12 introduces an ADR signal: artifact storage is the canonical file source
  of truth, and run workspace is a derived disposable execution view.
- ADR/backfill and commit remain user-authorized actions; no commit is created
  by this plan update.

W12 is complete only when all of these are true:

- Artifact download works and is tenant/conversation/user authorized.
- Sent message attachments render after send and reload.
- Uploaded files are materialized into a clean run workspace.
- `file_read` can read the uploaded file through the runtime file tool path.
- `file_list` cannot see stale global workspace or prior-run files.
- Missing/pending/unreadable attachments fail closed before LLM reasoning.
- Generated artifacts are visible, previewable, and downloadable.
- Settings sidebar conversation click navigates to `/chat`.
- Backend targeted tests pass.
- Full backend tests pass.
- Frontend lint/build pass.
- Windows browser QA `file-task-closure` passes.
- QA-created conversations/providers/artifacts are cleaned.
- `PROBLEM_TODO_LIST.md` reflects resolved W12 findings.
- No frontend style redesign was introduced.

## Risks

- Chat stream setup may need to prepare the workspace before returning
  `StreamingResponse`; if this blocks too long, move preparation into the
  generator but emit an SSE error before starting LLM calls on failure.
- Frontend optimistic messages may briefly duplicate attachments after reload if
  IDs are merged incorrectly; compare by artifact ID.
- File output paths may collide inside a run. Resolve by using run-scoped base
  and preserving requested relative paths only within that run.
- `Content-Disposition` filename handling can be unsafe if it uses raw user
  input. Use normalized artifact path basename and quote safely.
- Browser download verification can be brittle. Prefer Playwright download
  event and byte comparison against the expected generated content.

## Rollback Surface

- Remove the new download endpoint if it fails authorization review.
- Disable browser suite registration if it blocks unrelated QA, while keeping
  backend tests as evidence during debugging.
- Revert frontend download button only if the backend endpoint is withheld.
- Keep message attachment serialization backward compatible by making
  `attachments` optional.
- Keep file tool environment fallback so older tests do not break while chat
  runtime moves to per-run workspace context.

## Execution Choice

Recommended execution mode: Subagent-Driven.

Reason: W12 has independent backend contract, runtime workspace, frontend UI,
and browser QA slices. Use one fresh subagent per slice, review and release it
after each slice, then run final verification in the main agent.

Inline execution is acceptable if subagent capacity is unavailable, but the
same stop condition applies: no tail items, no style drift, no commits without
explicit user approval.
