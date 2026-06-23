"""Development patch proposal target tests."""

from __future__ import annotations

import uuid
import hashlib
from pathlib import Path
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.config import settings
from app.core.acquisition import lifecycle
from app.core.acquisition.development_patch import (
    record_development_patch_proposal,
    request_development_patch_handoff,
)
from app.models.acquisition import AcquisitionProposal, DevelopmentPatchProposal
from app.models.artifact import Artifact
from app.models.conversation import Conversation
from app.models.audit_log import AuditLog
from app.services.auth_service import decode_token


BASE_COMMIT = "a" * 40
PATCH_BYTES = (
    b"diff --git a/target.txt b/target.txt\n"
    b"--- a/target.txt\n"
    b"+++ b/target.txt\n"
    b"@@ -1 +1 @@\n"
    b"-old\n"
    b"+new\n"
)
NEW_FILE_PATCH_BYTES = (
    b"diff --git a/new.txt b/new.txt\n"
    b"new file mode 100644\n"
    b"--- /dev/null\n"
    b"+++ b/new.txt\n"
    b"@@ -0,0 +1 @@\n"
    b"+created\n"
)
PATCH_DIGEST = "sha256:" + hashlib.sha256(PATCH_BYTES).hexdigest()
NEW_FILE_PATCH_DIGEST = "sha256:" + hashlib.sha256(NEW_FILE_PATCH_BYTES).hexdigest()


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    token = headers["Authorization"].split(" ", 1)[1]
    payload = decode_token(token)
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def _patch_proposal(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    development_handoff: dict | None = None,
    rollback_plan: dict | None = None,
    idempotency_key: str | None = None,
) -> AcquisitionProposal:
    async with _async_session_factory() as db:
        gap = await lifecycle.record_gap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_kind="agent_runtime",
            source_run_id=f"patch-run-{uuid.uuid4().hex}",
            dedupe_key=f"Patch proposal {uuid.uuid4().hex}",
            title="Product code change needed",
            description="The task requires a reviewed code patch rather than runtime mutation.",
            gap_type="requires_code_patch",
            severity="high",
            evidence={"missing_capability": "self_modification"},
            source_evidence=[{"kind": "agent_failure", "message": "tool unavailable"}],
        )
        recommendation = await lifecycle.create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            recommendation_type="development_patch_recommendation",
            title="Create a reviewed development patch",
            summary="Convert the missing capability into a human-reviewed patch proposal.",
            reason="Runtime self-modification is forbidden.",
            evidence={"source": "test"},
            risk_level="risky",
            expected_value={"reviewable": True},
            required_permissions={"repo_write": "human_review_only"},
            candidate_targets=[{"target_type": "development_patch_proposal", "name": "patch"}],
        )
        proposal = await lifecycle.create_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_kind="development_patch_proposal",
            gap_id=gap.id,
            recommendation_id=recommendation.id,
            title="Reviewed patch proposal",
            reason="The product needs code changes that must go through review.",
            evidence={"source": "test"},
            risk_level="risky",
            permission_bundle={"target_type": "development_patch_proposal", "risk_level": "risky"},
            verification_plan={"kind": "patch_review"},
            rollback_plan=rollback_plan or {"rollback_plan_ref": "artifact://rollback.md"},
            user_visible_effect="A patch proposal is ready for human review.",
            development_handoff=development_handoff or {"handoff": "development"},
            idempotency_key=idempotency_key,
        )
        await db.commit()
        return proposal


async def _patch_artifact(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    patch_bytes: bytes = PATCH_BYTES,
    tmp_path=None,
) -> tuple[str, str]:
    root = tmp_path / "artifacts" if tmp_path is not None else Path(settings.artifact_base_path)
    async with _async_session_factory() as db:
        conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title="Patch artifact")
        db.add(conversation)
        await db.flush()
        artifact = Artifact(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            user_id=user_id,
            artifact_type="file",
            operation="write",
            workspace_path="patch.diff",
            state="available",
            mime_type="text/x-diff",
            size_bytes=len(patch_bytes),
            content_bytes_stored=len(patch_bytes),
            diff_bytes_stored=0,
            before_sha256=None,
            after_sha256=hashlib.sha256(patch_bytes).hexdigest(),
        )
        db.add(artifact)
        await db.flush()
        artifact_dir = root / str(tenant_id) / str(conversation.id) / str(artifact.id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        content_path = artifact_dir / "content.txt"
        content_path.write_bytes(patch_bytes)
        artifact.content_path = f"{tenant_id}/{conversation.id}/{artifact.id}/content.txt"
        artifact_ref = f"artifact://{artifact.id}"
        await db.commit()
    return artifact_ref, "sha256:" + hashlib.sha256(patch_bytes).hexdigest()


async def _record_patch(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    patch_artifact_ref: str = "artifact://00000000-0000-0000-0000-000000000000",
    patch_digest: str = PATCH_DIGEST,
) -> DevelopmentPatchProposal:
    async with _async_session_factory() as db:
        row = await record_development_patch_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal_id,
            base_git_commit=BASE_COMMIT,
            patch_artifact_ref=patch_artifact_ref,
            patch_digest=patch_digest,
            test_plan_ref="artifact://test-plan.md",
            rollback_plan_ref="artifact://rollback.md",
            review_checklist_ref="artifact://review.md",
            idempotency_key=f"patch-record-{uuid.uuid4().hex}",
        )
        await db.commit()
        return row


@pytest.mark.asyncio
async def test_development_patch_proposal_records_base_commit_patch_digest_test_plan_and_rollback(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)

    row = await _record_patch(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        persisted_proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted = (
            await db.execute(select(DevelopmentPatchProposal).where(DevelopmentPatchProposal.proposal_id == proposal.id))
        ).scalar_one()

    assert row.status == "verified"
    assert persisted.status == "verified"
    assert persisted.base_git_commit == BASE_COMMIT
    assert persisted.patch_digest == PATCH_DIGEST
    assert persisted.test_plan_ref == "artifact://test-plan.md"
    assert persisted.rollback_plan_ref == "artifact://rollback.md"
    assert persisted.review_checklist_ref == "artifact://review.md"
    assert persisted.working_tree_mutation_allowed is False
    assert persisted_proposal.status == "verified"
    assert persisted_proposal.development_handoff["patch_digest"] == PATCH_DIGEST


@pytest.mark.asyncio
async def test_development_patch_proposal_cannot_activate_as_runtime_tool(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    await _record_patch(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await lifecycle.activate_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                idempotency_key="patch-cannot-activate",
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "PROPOSAL_NOT_ACTIVATION_APPROVED"


@pytest.mark.asyncio
async def test_runtime_mutation_fields_are_forbidden(tenant_a_headers: dict[str, str]) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(
        tenant_id,
        user_id,
        development_handoff={"handoff": "development", "apply_patch": True},
    )

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await record_development_patch_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                base_git_commit=BASE_COMMIT,
                patch_artifact_ref="artifact://patch.diff",
                patch_digest=PATCH_DIGEST,
                test_plan_ref="artifact://test-plan.md",
                rollback_plan_ref="artifact://rollback.md",
                review_checklist_ref="artifact://review.md",
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_RUNTIME_MUTATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_development_patch_handoff_fails_when_current_git_revision_differs_from_base_commit(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    await _record_patch(tenant_id, user_id, proposal.id)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await request_development_patch_handoff(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                current_git_revision="c" * 40,
                patch_apply_checker=lambda repo_path, patch_ref: True,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_BASE_COMMIT_CHANGED"


@pytest.mark.asyncio
async def test_development_patch_handoff_fails_when_patch_no_longer_applies(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    patch_ref, patch_digest = await _patch_artifact(tenant_id, user_id)
    await _record_patch(tenant_id, user_id, proposal.id, patch_artifact_ref=patch_ref, patch_digest=patch_digest)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await request_development_patch_handoff(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                current_git_revision=BASE_COMMIT,
                patch_apply_checker=lambda repo_path, patch_ref: False,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_NO_LONGER_APPLIES"


@pytest.mark.asyncio
async def test_development_patch_handoff_rejects_digest_mismatch(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    patch_ref, _ = await _patch_artifact(tenant_id, user_id)
    await _record_patch(
        tenant_id,
        user_id,
        proposal.id,
        patch_artifact_ref=patch_ref,
        patch_digest="sha256:" + "0" * 64,
    )

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await request_development_patch_handoff(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                current_git_revision=BASE_COMMIT,
                patch_apply_checker=lambda repo_path, patch_ref: True,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_DIGEST_MISMATCH"


@pytest.mark.asyncio
async def test_development_patch_handoff_rejects_local_patch_path(
    tenant_a_headers: dict[str, str],
    tmp_path,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    local_patch = tmp_path / "patch.diff"
    local_patch.write_bytes(PATCH_BYTES)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await record_development_patch_proposal(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                base_git_commit=BASE_COMMIT,
                patch_artifact_ref=str(local_patch),
                patch_digest=PATCH_DIGEST,
                test_plan_ref="artifact://test-plan.md",
                rollback_plan_ref="artifact://rollback.md",
                review_checklist_ref="artifact://review.md",
            )

    assert exc.value.status_code == 422
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_ARTIFACT_REQUIRED"


@pytest.mark.asyncio
async def test_development_patch_handoff_rejects_mode_only_patch_without_hunk(
    tenant_a_headers: dict[str, str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    monkeypatch.setattr(settings, "artifact_base_path", str(tmp_path / "artifacts"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mode.txt").write_text("unchanged\n", encoding="utf-8")
    mode_only_patch = (
        b"diff --git a/mode.txt b/mode.txt\n"
        b"old mode 100644\n"
        b"new mode 100755\n"
    )
    patch_ref, patch_digest = await _patch_artifact(
        tenant_id,
        user_id,
        patch_bytes=mode_only_patch,
        tmp_path=tmp_path,
    )
    proposal = await _patch_proposal(tenant_id, user_id)
    await _record_patch(tenant_id, user_id, proposal.id, patch_artifact_ref=patch_ref, patch_digest=patch_digest)

    async with _async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await request_development_patch_handoff(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                proposal_id=proposal.id,
                repo_path=str(repo),
                current_git_revision=BASE_COMMIT,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DEVELOPMENT_PATCH_NO_LONGER_APPLIES"


@pytest.mark.asyncio
async def test_development_patch_handoff_ready_after_base_and_patch_apply_checks(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    proposal = await _patch_proposal(tenant_id, user_id)
    patch_ref, patch_digest = await _patch_artifact(tenant_id, user_id)
    await _record_patch(tenant_id, user_id, proposal.id, patch_artifact_ref=patch_ref, patch_digest=patch_digest)

    async with _async_session_factory() as db:
        row = await request_development_patch_handoff(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            current_git_revision=BASE_COMMIT,
            patch_apply_checker=lambda repo_path, patch_ref: True,
            idempotency_key="patch-handoff-ready",
        )
        await db.commit()

    async with _async_session_factory() as db:
        persisted_proposal = (
            await db.execute(select(AcquisitionProposal).where(AcquisitionProposal.id == proposal.id))
        ).scalar_one()
        persisted = (
            await db.execute(select(DevelopmentPatchProposal).where(DevelopmentPatchProposal.proposal_id == proposal.id))
        ).scalar_one()
        audit = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "acquisition.development_patch.handoff_ready",
                    AuditLog.resource_id == str(persisted.id),
                )
            )
        ).scalar_one()

    assert row.status == "handoff_ready"
    assert persisted.status == "handoff_ready"
    assert persisted.apply_check_status == "passed"
    assert persisted.handoff_requested_by == user_id
    assert persisted_proposal.status == "handoff_ready"
    assert audit.details["patch_digest"] == patch_digest


@pytest.mark.asyncio
async def test_development_patch_handoff_dry_applies_artifact_patch_without_mutation(
    tenant_a_headers: dict[str, str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    monkeypatch.setattr(settings, "artifact_base_path", str(tmp_path / "artifacts"))
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    patch_ref, patch_digest = await _patch_artifact(tenant_id, user_id, patch_bytes=PATCH_BYTES, tmp_path=tmp_path)

    proposal = await _patch_proposal(tenant_id, user_id)
    async with _async_session_factory() as db:
        await record_development_patch_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            base_git_commit=BASE_COMMIT,
            patch_artifact_ref=patch_ref,
            patch_digest=patch_digest,
            test_plan_ref="artifact://test-plan.md",
            rollback_plan_ref="artifact://rollback.md",
            review_checklist_ref="artifact://review.md",
        )
        await db.commit()

    async with _async_session_factory() as db:
        row = await request_development_patch_handoff(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            repo_path=str(repo),
            current_git_revision=BASE_COMMIT,
        )
        await db.commit()

    assert row.status == "handoff_ready"
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_development_patch_handoff_accepts_new_file_patch_without_mutation(
    tenant_a_headers: dict[str, str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    monkeypatch.setattr(settings, "artifact_base_path", str(tmp_path / "artifacts"))
    repo = tmp_path / "repo"
    repo.mkdir()
    patch_ref, patch_digest = await _patch_artifact(
        tenant_id,
        user_id,
        patch_bytes=NEW_FILE_PATCH_BYTES,
        tmp_path=tmp_path,
    )
    proposal = await _patch_proposal(tenant_id, user_id)
    async with _async_session_factory() as db:
        await record_development_patch_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            base_git_commit=BASE_COMMIT,
            patch_artifact_ref=patch_ref,
            patch_digest=patch_digest,
            test_plan_ref="artifact://test-plan.md",
            rollback_plan_ref="artifact://rollback.md",
            review_checklist_ref="artifact://review.md",
        )
        await db.commit()

    async with _async_session_factory() as db:
        row = await request_development_patch_handoff(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            repo_path=str(repo),
            current_git_revision=BASE_COMMIT,
        )
        await db.commit()

    assert row.status == "handoff_ready"
    assert not (repo / "new.txt").exists()
