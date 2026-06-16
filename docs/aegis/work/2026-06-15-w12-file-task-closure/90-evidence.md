# W12 File Task Closure Evidence

Updated: 2026-06-15 Task 1 evidence

## EvidenceBundleDraft

## Task 1 Backend Artifact Download

RED:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary"
```

Result: failed as expected with `404 {"detail":"Not Found"}` for
`/api/v1/artifacts/{id}/download`.

GREEN:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary"
```

Result: `1 passed`.

Regression:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_artifacts.py tests/test_file_upload_security.py"
```

Result: `19 passed`.

Review finding repair:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_artifact_download_returns_bytes_headers_and_enforces_tenant_boundary tests/test_file_task_closure.py::test_artifact_download_uses_ascii_fallback_for_non_ascii_workspace_path"
```

Result: `2 passed`.

## Task 2 Message Attachment Metadata

RED:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_conversation_detail_returns_sent_attachment_metadata"
```

Result: failed as expected with `KeyError: 'attachments'`.

GREEN:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_conversation_detail_returns_sent_attachment_metadata"
```

Result: `1 passed`.

## Task 3 Run Workspace Materialization

RED:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_run_workspace_materializes_upload_and_file_tools_are_run_scoped tests/test_file_task_closure.py::test_file_list_does_not_expose_stale_global_workspace_files"
```

Result: failed as expected with missing `app.core.artifacts.workspace` and
global workspace listing `runs\nstale-w6-output.txt`.

GREEN:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_run_workspace_materializes_upload_and_file_tools_are_run_scoped tests/test_file_task_closure.py::test_file_list_does_not_expose_stale_global_workspace_files"
```

Result: `2 passed`.

Regression:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_artifacts.py"
```

Result: `3 passed`.

Planned evidence:
- Targeted backend W12 tests in Docker.
- Full backend tests in Docker.
- Frontend lint/build in Docker.
- Local Docker build/health.
- Windows Chrome browser QA suite `file-task-closure`.
- QA cleanup evidence.

## Task 4 Chat Runtime Integration

RED/GREEN:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_file_task_closure.py::test_chat_attachment_is_readable_through_file_read_tool tests/test_file_task_closure.py::test_attachment_materialization_failure_fails_closed_before_llm_call"
```

Result: `2 passed`.

Regression:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q tests/test_sse_contract.py tests/test_file_upload_security.py tests/test_artifacts.py"
```

Result: `31 passed`.

## Task 5 Frontend File State / Download / Settings Navigation

Frontend verification:

```text
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Result: lint passed and Next.js production build passed.

Additional runtime finding:

```text
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite file-task-closure -TimeoutMs 120000
```

First result: failed at `settings-sidebar-navigates-chat` because `/settings`
did not load the conversation list before rendering Sidebar.

Repair: `frontend/src/app/settings/page.tsx` now calls `loadConversations()`
when a token is present, using the existing chat-store owner.

## Task 6 Browser QA

Browser QA:

```text
powershell -ExecutionPolicy Bypass -File scripts\windows-browser-qa.ps1 -Url http://localhost -Browser chrome -Headless -Suite file-task-closure -TimeoutMs 120000
```

Result: `ok: true`.

Report:

```text
E:\Chainless\.gstack\qa-reports\local\file-task-closure-2026-06-15T08-20-20-357Z\report.json
```

Passed steps:

```text
auth-login
mock-provider-default
conversation-create
upload-state-available
sent-message-attachment-visible
file-read-tool-used
generated-artifact-visible
artifact-download-bytes-match
settings-sidebar-navigates-chat
mock-provider-observed-file-tool-loop
cleanup-conversations
cleanup-provider
```

Signals:

```text
consoleErrors: 0
pageErrors: 0
requestFailures: 0
responses429: 0
chatCalls: 3
```

Cleanup:

```text
conversation 623168fc-0913-4395-a093-bed927d807df deleted ok=true
provider w12-file-1781511620604-provider deleted ok=true
```

## Task 7 Final Verification

Full backend:

```text
docker-compose -f docker-compose.yml -f docker-compose.test.yml run --rm -e PYTHONPATH=/repo/backend backend-test sh -lc "cd /repo/backend && pytest -q"
```

Result: `346 passed, 4 skipped, 3 warnings`.

Frontend:

```text
docker-compose run --rm frontend sh -lc "npm run lint && npm run build"
```

Result: lint passed and Next.js production build passed.

Local Docker:

```text
docker-compose up -d --build
curl.exe -fsS http://127.0.0.1/api/v1/health
docker-compose ps --format json
```

Result: local Docker services rebuilt/recreated; backend health returned
`{"status":"ok"}`; `chainless-backend` and `chainless-sandbox-proxy` reported
healthy, and frontend/nginx/sandbox/worker were running.

Problem ledger:

```text
PROBLEM_TODO_LIST.md
```

Result: W12 file task closure findings recorded as resolved with evidence.
