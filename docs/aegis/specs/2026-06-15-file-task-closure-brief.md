# W12 File Task Closure Spec Brief

Status: Draft for user review
Type: Spec Brief / Contract Repair
Created: 2026-06-15
Parent refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- User-reported file task closure break on 2026-06-15

## TaskIntentDraft

Outcome: make user file tasks reliable end to end: upload -> explicit file state -> sent with message -> agent-readable run workspace -> generated artifact -> preview/download -> clean failure or cleanup.

Goal: a user can upload a text file, ask the agent to read or transform it, see what file state the product is in, and receive a downloadable output without the agent seeing stale workspace files or inventing around missing input.

Success evidence:
- Browser QA shows upload states, sent attachment cards, agent reading the uploaded content, output artifact preview, output artifact download, and Settings conversation navigation.
- Backend tests prove upload artifacts are tenant/conversation scoped, downloadable with correct headers, materialized into a clean run workspace, and blocked when missing, pending, foreign, deleted, or stale.
- File tools never expose historical QA files or prior-run files to the current agent run.
- If a required attachment is unavailable, the agent stops with a typed user-facing failure and asks the user to retry, re-upload, or wait. It must not silently fall back to web search, old workspace files, or model-only fabrication.

Stop condition: all W12 backend tests and Windows browser QA pass in local Docker, with zero stale workspace leakage and no frontend visual redesign.

Non-goals:
- Do not redesign the chat visual style, sidebar style, right panel style, or composer aesthetic.
- Do not solve the entire weather, search, ticket booking, or broad web-automation tool contract in W12.
- Do not add binary upload support.
- Do not replace durable artifact storage with workspace storage.
- Do not use host Python or host Node as the application runtime.

## BaselineReadSetHint

Authority and plan refs:
- `docs/aegis/specs/2026-06-02-chainless-agent-platform-design.md`
- `docs/aegis/plans/2026-06-05-chainless-v1-complete-spec-execution-plan.md`
- `AGENTS.md`

Current implementation refs:
- `backend/app/api/v1/uploads.py`
- `backend/app/api/v1/artifacts.py`
- `backend/app/api/v1/conversations.py`
- `backend/app/core/artifacts/service.py`
- `backend/app/core/tools/builtin/file_ops.py`
- `frontend/src/app/chat/page.tsx`
- `frontend/src/app/settings/page.tsx`
- `frontend/src/components/chat/file-attachment.tsx`
- `frontend/src/components/chat/file-artifact-list.tsx`
- `frontend/src/components/layout/sidebar.tsx`
- `frontend/src/stores/artifact-store.ts`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/lib/api.ts`

## ImpactStatementDraft

Affected layers:
- Product UX: attachment cards need explicit lifecycle states and sent-message visibility while preserving current style language.
- API contract: artifacts need a download endpoint and attachment validation must cover state, tenant, conversation, and ownership.
- Agent runtime: message attachments must become a run-scoped readable workspace view before tool execution starts.
- Tool runtime: `file_read`, `file_write`, and `file_list` must operate only on the current run workspace and current run outputs.
- Artifact runtime: durable artifact storage remains the source of truth; workspace files are disposable derived copies.
- Failure handling: missing or pending attachments are task-blocking errors, not hints for the model to improvise.
- Navigation: selecting a conversation from Settings must route the user back to `/chat`.

Compatibility boundaries:
- Existing `/api/v1/artifacts/{id}`, `/content`, and `/diff` behavior remains compatible.
- Existing text upload restrictions, tenant isolation, quota, preview security, and artifact retention remain enforced.
- Existing visual design is preserved; W12 may add state text/buttons inside existing components but must not restyle the product.

## Product Risk Lens

Value: file tasks are a core trust path for a general agent. If the agent cannot reliably consume uploaded files and return downloadable outputs, the product feels demo-only even when chat and tools work.

Non-goals: W12 does not claim general web automation is production-complete. It closes the file task loop first because it is a concrete, testable, high-frequency agent workflow.

Trade-offs: a quick copy-to-workspace bridge is faster, but it preserves duplicate file ownership and stale-file risk. A canonical artifact plus per-run materialization contract takes more implementation work, but it gives the product one traceable file object from upload through delivery.

Decision needed: approve canonical artifact source of truth plus run-scoped workspace materialization as the W12 implementation direction.

## Architecture Integrity Lens

Invariant: a user-visible file must be the same traceable object across UI state, message attachment metadata, agent runtime input, file tools, artifact preview, download, and cleanup.

Canonical owner and contract:
- `backend/app/core/artifacts/service.py` owns durable artifact metadata and stored content.
- A new backend owner should materialize selected artifacts into a run-scoped workspace before agent execution. Candidate module: `backend/app/core/artifacts/workspace.py`.
- `backend/app/api/v1/artifacts.py` owns artifact metadata, preview, diff, and download API authorization.
- Frontend artifact state remains owned by `frontend/src/stores/artifact-store.ts`; attachment rendering remains component-local and style-preserving.

Responsibility overlap today:
- Uploads store files in artifact storage with a `workspace_path` hint.
- File tools read and write `/workspace` directly.
- Conversation messages remember attachment artifact IDs but do not guarantee tool-readable materialization.
- Artifact preview exists, but artifact delivery/download is incomplete.

Higher-level simplification: artifact storage is the source of truth. Workspace is not a second source of truth; it is a clean, per-run view derived from selected artifacts and current run outputs.

Retirement/falsifier: any implementation that lets `file_list` reveal files from earlier runs, historical QA files, or global `/workspace` state fails this spec.

Verdict: Implementation Drift with architecture scope. The original spec required real file tools and artifacts; the implementation completed pieces but left the upload/artifact/workspace/download contract split.

## Baseline Role Alignment

Product / Requirement Baseline: a deployable general agent must handle user-provided files as first-class task inputs and return generated files in a way the user can retrieve.

Architecture / Runtime Boundary Baseline: sandbox/workspace execution remains isolated and disposable; artifacts remain durable, tenant-scoped, and conversation-scoped.

Result: Implementation Drift.

Scope: both requirements and architecture.

Next action: write an implementation plan that closes file state, artifact download, run workspace materialization, stale workspace isolation, fail-closed agent behavior, and Settings navigation.

## Options

### Option A: Minimal upload-to-workspace bridge

Copy uploaded artifacts into `/workspace/uploads` and add a download endpoint.

Pros:
- Fastest patch.
- Smallest immediate code diff.

Cons:
- Keeps artifact storage and workspace as duplicate sources.
- Does not naturally solve stale files or run isolation.
- Easy to regress into historical workspace leakage.

### Option B: Canonical artifact plus run-scoped materialization

Keep artifact storage as the source of truth. Before each agent run, materialize the message's validated attachments into a clean run workspace, expose only that run's input/output files to file tools, and capture outputs back into artifacts.

Pros:
- Matches original sandbox isolation model.
- Gives one traceable file object from upload to delivery.
- Prevents stale workspace contamination by design.
- Gives clean acceptance tests for tenant, conversation, run, and cleanup boundaries.

Cons:
- Requires a new small runtime owner and careful integration with chat execution.
- Needs tests across API, agent runtime, and browser QA.

Recommendation: choose Option B.

### Option C: Artifact-aware file tools without workspace materialization

Teach `file_read` and `file_list` to read artifact IDs or virtual artifact paths directly.

Pros:
- Avoids physical copies for uploads.
- Strong source-of-truth semantics.

Cons:
- Weakens the POSIX workspace model expected by Code-as-Action and sandbox execution.
- Creates a more custom tool contract for generated code.
- Still needs a separate output/download path.

## W12 Requirements

1. Attachment state UI:
- The composer and message area must expose clear file states: `uploading`, `available`, `failed`, `sent`, and `downloadable` where applicable.
- Upload failure must show a recoverable error with retry or remove behavior.
- Sending a message with attachments must preserve visible attachment cards in the sent message.
- UI changes must preserve the existing Chainless visual style and scroll behavior.

2. Unified file object contract:
- A file object must be traceable by artifact ID across upload, message attachment, run materialization, preview, download, and cleanup.
- Required fields: `id`, `tenant_id`, `conversation_id`, `source`, `original_name`, `safe_name`, `mime_type`, `size_bytes`, `state`, `storage_path`, `workspace_mount_path` when materialized, `created_by_message_id` when sent, `consumed_by_run_id` when used, and `download_url` when downloadable.
- The durable source is artifact storage under the configured artifact base path.

3. Message attachment contract:
- `attachment_artifact_ids` must validate tenant, conversation, user access, artifact state, and text/upload eligibility before the message is accepted.
- The persisted message must retain sent attachments so reloads and history reconstruction show what was sent.
- The agent prompt/context must identify available attachment paths explicitly instead of relying on the model to guess `uploads/<name>`.

4. Run-scoped workspace materialization:
- Before agent execution, validated sent attachments must be copied or mounted into a clean run workspace under deterministic collision-safe paths, for example `/workspace/input/<artifact_id>/<safe_name>`.
- The agent must receive the exact paths it can read.
- File tools must only see the current run workspace and current run outputs.

5. Workspace isolation and cleanup:
- No prior run, historical QA, or unrelated test files may be visible to `file_list`.
- Sandbox recycle must clear run workspace state before reuse.
- Tests must seed stale files and prove the current run cannot see them.

6. Agent fail-closed behavior:
- If an attachment is missing, deleted, pending, not materialized, or unreadable, the run must stop before normal agent reasoning.
- The user-facing response must explain the concrete file state and ask for re-upload, retry, or waiting for upload completion.
- The agent must not answer file-content questions from memory, stale files, web search, or unverified model inference.

7. Download delivery:
- Add `GET /api/v1/artifacts/{artifact_id}/download`.
- The endpoint must enforce tenant, conversation, user, artifact state, and storage-path checks.
- The response must include safe `Content-Disposition`, `Content-Type`, and `Content-Length` where available.
- The Files panel must expose a download action for downloadable artifacts without changing the established panel style.

8. Settings navigation:
- Selecting a conversation from `/settings` must select it and navigate to `/chat`.
- This is logic-only; sidebar rename/delete behavior and styling must remain intact.

9. General-agent boundary:
- W12 establishes strong success/failure contracts for file tasks only.
- Weather, search, booking, and broad web tasks need later tool-contract work and must not be marked solved by W12.

## Acceptance Tests

Backend contract tests:
- Upload text file -> artifact metadata -> content preview -> download bytes and headers match.
- Foreign tenant, foreign conversation, archived conversation, deleted artifact, failed artifact, and pending artifact access are rejected.
- Chat attachment validation rejects unavailable artifacts.
- Chat run materializes uploaded file into a clean workspace and `file_read` reads the uploaded bytes.
- `file_list` cannot see stale seeded files from previous runs.
- Missing materialization returns a typed fail-closed response before normal agent execution.

Frontend and browser QA:
- Upload a text file and observe state transition from uploading to available.
- Send a message with the attachment and verify the sent message still shows the file card.
- Ask the agent to read an exact phrase from the uploaded file and verify tool evidence shows the uploaded file path was read.
- Ask the agent to generate a file and verify it appears in Files, previews correctly, and downloads with matching bytes.
- Simulate upload failure or unavailable attachment and verify the UI shows a clear stop/retry path.
- From `/settings`, click an existing conversation and verify the app navigates to `/chat` with that conversation selected.

Verification environment:
- Use local Docker Desktop only.
- Run backend tests inside Docker.
- Run browser QA through the Windows browser path already configured for gstack/browse.
- Do not rely on host Python or host Node.

## Plan-Time Complexity Check

Likely high-pressure files:
- `backend/app/api/v1/conversations.py`
- `backend/app/core/agent/engine.py`
- `frontend/src/stores/chat-store.ts`
- `frontend/src/app/chat/page.tsx`

Better file boundary:
- Add a backend owner for run workspace materialization instead of growing `conversations.py` or `file_ops.py`.
- Keep artifact download logic in `backend/app/api/v1/artifacts.py`.
- Keep upload validation in `backend/app/api/v1/uploads.py`.
- Keep attachment rendering changes inside existing chat attachment/message components and reuse existing style classes.

Recommendation: add one focused backend owner for materialization, edit API/UI files only at their contract seams, and avoid broad refactors.

## ADR Signal

W12 changes a durable architecture boundary: artifact storage becomes the canonical file source of truth, and `/workspace` becomes a derived per-run execution view. After implementation, record or update an ADR if this boundary is accepted by tests and review.

## Decision Needed

Approve Option B as the W12 implementation direction, then write a detailed implementation plan before touching code.
