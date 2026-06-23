"""Development patch proposal handoff owner.

This owner records self-modification proposals as durable review artifacts.
It never applies patches, stages files, commits, pushes, or deploys.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import api_error
from app.core.acquisition import repository
from app.core.audit.service import AuditRecord, add_audit_log
from app.core.artifacts.service import read_artifact_bytes
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import AcquisitionProposal, DevelopmentPatchProposal
from app.models.artifact import Artifact
from app.models.conversation import Conversation


PatchApplyChecker = Callable[[str, str], bool]
GitRevisionProvider = Callable[[str], str]
MAX_PATCH_BYTES = 1_000_000

FORBIDDEN_RUNTIME_MUTATION_KEYS = {
    "activate_runtime",
    "activation_target",
    "apply_patch",
    "apply_patch_now",
    "commit",
    "deploy",
    "edit_repo",
    "git_commit",
    "git_push",
    "merge",
    "push",
    "runtime_mutation",
    "runtime_target",
    "stage",
    "working_tree_mutation_allowed",
    "write_file",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def record_development_patch_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    base_git_commit: str,
    patch_artifact_ref: str,
    patch_digest: str,
    test_plan_ref: str,
    rollback_plan_ref: str,
    review_checklist_ref: str,
    idempotency_key: str | None = None,
) -> DevelopmentPatchProposal:
    """Persist immutable development handoff evidence for a patch proposal."""

    proposal = await _patch_proposal(db, tenant_id=tenant_id, user_id=user_id, proposal_id=proposal_id)
    _validate_no_runtime_mutation(proposal)
    payload = _patch_payload(
        base_git_commit=base_git_commit,
        patch_artifact_ref=patch_artifact_ref,
        patch_digest=patch_digest,
        test_plan_ref=test_plan_ref,
        rollback_plan_ref=rollback_plan_ref,
        review_checklist_ref=review_checklist_ref,
    )
    existing = await _existing_patch(db, proposal=proposal)
    if existing is not None:
        if _row_matches(existing, payload):
            return existing
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_PROPOSAL_ALREADY_EXISTS",
            "Development patch proposal already exists with different evidence",
            {"proposal_id": str(proposal.id)},
        )

    if proposal.status == "drafted":
        proposal, _ = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="verifying",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:verifying" if idempotency_key else None,
        )
    if proposal.status == "verifying":
        proposal, _ = await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="verified",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:verified" if idempotency_key else None,
        )
    if proposal.status != "verified":
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_PROPOSAL_NOT_VERIFIED",
            "Development patch handoff evidence requires a verified patch proposal",
            {"status": proposal.status},
        )

    handoff = proposal.development_handoff if isinstance(proposal.development_handoff, dict) else {}
    proposal.development_handoff = validate_bounded_json({**handoff, **payload}, field="development_handoff")
    row = DevelopmentPatchProposal(
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal.id,
        status="verified",
        base_git_commit=base_git_commit,
        patch_artifact_ref=patch_artifact_ref,
        patch_digest=patch_digest,
        test_plan_ref=test_plan_ref,
        rollback_plan_ref=rollback_plan_ref,
        review_checklist_ref=review_checklist_ref,
        apply_check_status="not_checked",
        working_tree_mutation_allowed=False,
    )
    db.add(row)
    await db.flush()
    return row


async def request_development_patch_handoff(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    repo_path: str = ".",
    current_git_revision: str | None = None,
    current_revision_provider: GitRevisionProvider | None = None,
    patch_apply_checker: PatchApplyChecker | None = None,
    idempotency_key: str | None = None,
) -> DevelopmentPatchProposal:
    """Validate a patch proposal is still safe to hand off for human review."""

    proposal = await _patch_proposal(db, tenant_id=tenant_id, user_id=user_id, proposal_id=proposal_id)
    row = await _existing_patch(db, proposal=proposal)
    if row is None:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_PROPOSAL_MISSING",
            "Development patch handoff evidence must be recorded before handoff",
            {"proposal_id": str(proposal_id)},
        )
    if row.status not in {"verified", "handoff_ready"}:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_HANDOFF_NOT_READY",
            "Development patch proposal must be verified before handoff",
            {"status": row.status},
        )
    current_revision = current_git_revision or (current_revision_provider or _current_git_revision)(repo_path)
    if current_revision != row.base_git_commit:
        row.apply_check_status = "base_changed"
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_BASE_COMMIT_CHANGED",
            "Current git revision differs from the verified base commit",
            {"base_git_commit": row.base_git_commit, "current_git_revision": current_revision},
        )
    patch_bytes = await _patch_artifact_bytes(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        patch_artifact_ref=row.patch_artifact_ref,
    )
    if _sha256_ref(patch_bytes) != row.patch_digest:
        row.apply_check_status = "digest_mismatch"
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_DIGEST_MISMATCH",
            "Patch artifact content digest does not match the verified patch digest",
            {"patch_artifact_ref": row.patch_artifact_ref},
        )
    if patch_apply_checker is not None:
        patch_applies = patch_apply_checker(repo_path, row.patch_artifact_ref)
    else:
        patch_applies = _patch_applies_without_mutation(repo_path=repo_path, patch_bytes=patch_bytes)
    if not patch_applies:
        row.apply_check_status = "failed"
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_NO_LONGER_APPLIES",
            "Patch no longer applies cleanly to the verified base commit",
            {"patch_artifact_ref": row.patch_artifact_ref},
        )

    row.apply_check_status = "passed"
    row.status = "handoff_ready"
    row.handoff_requested_at = _now()
    row.handoff_requested_by = user_id
    if proposal.status != "handoff_ready":
        await repository.transition_proposal(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            proposal_id=proposal.id,
            status="handoff_ready",
            actor_user_id=user_id,
            idempotency_key=f"{idempotency_key}:handoff-ready" if idempotency_key else None,
        )
    await add_audit_log(
        db,
        AuditRecord(
            action="acquisition.development_patch.handoff_ready",
            method="SYSTEM",
            path="/internal/acquisition/development-patch",
            status_code=200,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="development_patch_proposal",
            resource_id=str(row.id),
            details={
                "proposal_id": str(proposal.id),
                "base_git_commit": row.base_git_commit,
                "patch_digest": row.patch_digest,
                "patch_artifact_ref": row.patch_artifact_ref,
                "idempotency_key": idempotency_key,
            },
        ),
    )
    await db.flush()
    return row


async def _patch_proposal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> AcquisitionProposal:
    proposal = await repository.get_proposal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_id=proposal_id,
        for_update=True,
    )
    if proposal.proposal_kind != "development_patch_proposal":
        raise api_error(
            409,
            "PROPOSAL_NOT_DEVELOPMENT_PATCH",
            "Development patch handoff requires a development_patch_proposal",
            {"proposal_kind": proposal.proposal_kind},
        )
    if proposal.primary_target is not None:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_RUNTIME_TARGET_FORBIDDEN",
            "Development patch proposals cannot have runtime activation targets",
        )
    return proposal


async def _existing_patch(db: AsyncSession, *, proposal: AcquisitionProposal) -> DevelopmentPatchProposal | None:
    return (
        await db.execute(
            select(DevelopmentPatchProposal)
            .where(
                DevelopmentPatchProposal.tenant_id == proposal.tenant_id,
                DevelopmentPatchProposal.user_id == proposal.user_id,
                DevelopmentPatchProposal.proposal_id == proposal.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _patch_payload(
    *,
    base_git_commit: str,
    patch_artifact_ref: str,
    patch_digest: str,
    test_plan_ref: str,
    rollback_plan_ref: str,
    review_checklist_ref: str,
) -> dict[str, str]:
    payload = {
        "base_git_commit": _required_text(base_git_commit, "base_git_commit", max_len=80),
        "patch_artifact_ref": _required_text(patch_artifact_ref, "patch_artifact_ref", max_len=500),
        "patch_digest": _required_text(patch_digest, "patch_digest", max_len=128),
        "test_plan_ref": _required_text(test_plan_ref, "test_plan_ref", max_len=500),
        "rollback_plan_ref": _required_text(rollback_plan_ref, "rollback_plan_ref", max_len=500),
        "review_checklist_ref": _required_text(review_checklist_ref, "review_checklist_ref", max_len=500),
    }
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", payload["patch_digest"]) is None:
        raise api_error(422, "INVALID_PATCH_DIGEST", "Patch digest must be a sha256 digest reference")
    if _artifact_ref_id(payload["patch_artifact_ref"]) is None:
        raise api_error(
            422,
            "DEVELOPMENT_PATCH_ARTIFACT_REQUIRED",
            "Development patch proposals must reference an artifact:// patch",
            {"field": "patch_artifact_ref"},
        )
    return payload


def _required_text(value: str, field: str, *, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise api_error(422, "DEVELOPMENT_PATCH_FIELD_REQUIRED", f"{field} is required", {"field": field})
    if len(text) > max_len:
        raise api_error(422, "DEVELOPMENT_PATCH_FIELD_TOO_LONG", f"{field} is too long", {"field": field})
    return text


def _row_matches(row: DevelopmentPatchProposal, payload: Mapping[str, str]) -> bool:
    return all(str(getattr(row, key)) == str(value) for key, value in payload.items())


def _validate_no_runtime_mutation(proposal: AcquisitionProposal) -> None:
    forbidden = _forbidden_paths(
        {
            "development_handoff": proposal.development_handoff,
            "verification_plan": proposal.verification_plan,
            "rollback_plan": proposal.rollback_plan,
            "evidence": proposal.evidence,
        }
    )
    if forbidden:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_RUNTIME_MUTATION_FORBIDDEN",
            "Development patch proposal contains runtime mutation fields",
            {"forbidden_fields": forbidden[:20]},
        )


def _forbidden_paths(value: Any, *, path: str = "$") -> list[str]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_RUNTIME_MUTATION_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_paths(item, path=child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_paths(item, path=f"{path}[{index}]"))
        return paths
    return []


def _current_git_revision(repo_path: str) -> str:
    configured_revision = os.getenv("CHAINLESS_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    if configured_revision:
        return configured_revision.strip()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_GIT_REVISION_UNAVAILABLE",
            "Current git revision could not be read for development patch handoff",
        )
    return result.stdout.strip()


async def _patch_artifact_bytes(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    patch_artifact_ref: str,
) -> bytes:
    artifact_id = _artifact_ref_id(patch_artifact_ref)
    if artifact_id is None:
        raise api_error(
            409,
            "DEVELOPMENT_PATCH_ARTIFACT_REQUIRED",
            "Development patch handoff requires an artifact:// patch reference",
            {"patch_artifact_ref": patch_artifact_ref},
        )
    artifact = await _owned_patch_artifact(db, tenant_id=tenant_id, user_id=user_id, artifact_id=artifact_id)
    if artifact is None:
        raise api_error(404, "DEVELOPMENT_PATCH_ARTIFACT_NOT_FOUND", "Development patch artifact not found")
    try:
        patch_bytes = await read_artifact_bytes(artifact, content_kind="content")
    except (FileNotFoundError, PermissionError):
        raise api_error(409, "DEVELOPMENT_PATCH_ARTIFACT_UNREADABLE", "Development patch artifact is not readable")
    if len(patch_bytes) > MAX_PATCH_BYTES:
        raise api_error(409, "DEVELOPMENT_PATCH_TOO_LARGE", "Development patch artifact exceeds the handoff byte cap")
    return patch_bytes


def _patch_applies_without_mutation(*, repo_path: str, patch_bytes: bytes) -> bool:
    try:
        return _unified_patch_applies_without_mutation(Path(repo_path), patch_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False


def _unified_patch_applies_without_mutation(repo_path: Path, patch_text: str) -> bool:
    lines = patch_text.splitlines()
    index = 0
    saw_file = False
    saw_hunk = False
    while index < len(lines):
        line = lines[index]
        if not line.startswith("diff --git "):
            index += 1
            continue
        saw_file = True
        old_path, new_path = _parse_diff_paths(line)
        target_path = _safe_repo_path(repo_path, new_path or old_path)
        old_is_dev_null = False
        target_lines: list[str] | None = None
        index += 1
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if lines[index].startswith("--- "):
                old_is_dev_null = lines[index][4:].strip() == "/dev/null"
                index += 1
                continue
            if lines[index].startswith("+++ "):
                declared_target = lines[index][4:].strip()
                if declared_target != "/dev/null":
                    target_path = _safe_repo_path(repo_path, declared_target)
                index += 1
                continue
            if lines[index].startswith("@@ "):
                saw_hunk = True
                if target_lines is None:
                    if target_path is None:
                        return False
                    if old_is_dev_null:
                        if target_path.exists():
                            return False
                        target_lines = []
                    elif not target_path.exists() or not target_path.is_file():
                        return False
                    else:
                        target_lines = target_path.read_text(encoding="utf-8").splitlines()
                hunk_lines: list[str] = []
                hunk_header = lines[index]
                index += 1
                while index < len(lines) and not lines[index].startswith("@@ ") and not lines[index].startswith("diff --git "):
                    hunk_lines.append(lines[index])
                    index += 1
                if not _hunk_applies(target_lines, hunk_header, hunk_lines):
                    return False
                continue
            index += 1
    return saw_file and saw_hunk


def _parse_diff_paths(line: str) -> tuple[str, str]:
    parts = line.split()
    if len(parts) < 4:
        raise ValueError("Invalid diff header")
    return parts[2], parts[3]


def _safe_repo_path(repo_path: Path, diff_path: str) -> Path | None:
    normalized = diff_path[2:] if diff_path.startswith(("a/", "b/")) else diff_path
    if normalized == "/dev/null" or normalized.startswith("../") or Path(normalized).is_absolute():
        return None
    candidate = (repo_path / normalized).resolve()
    repo_root = repo_path.resolve()
    if candidate != repo_root and repo_root not in candidate.parents:
        return None
    return candidate


def _hunk_applies(target_lines: list[str], hunk_header: str, hunk_lines: list[str]) -> bool:
    old_start = _old_start_from_hunk_header(hunk_header)
    cursor = max(old_start - 1, 0)
    for line in hunk_lines:
        if not line:
            continue
        marker = line[0]
        text = line[1:]
        if marker in {" ", "-"}:
            if cursor >= len(target_lines) or target_lines[cursor] != text:
                return False
            cursor += 1
        elif marker == "+":
            continue
        elif line == "\\ No newline at end of file":
            continue
        else:
            return False
    return True


def _old_start_from_hunk_header(header: str) -> int:
    marker = header.split(" ", 2)[1]
    if not marker.startswith("-"):
        raise ValueError("Invalid hunk header")
    start = marker[1:].split(",", 1)[0]
    return int(start)


async def _owned_patch_artifact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> Artifact | None:
    return (
        await db.execute(
            select(Artifact)
            .join(Conversation, Artifact.conversation_id == Conversation.id)
            .where(
                Artifact.id == artifact_id,
                Artifact.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.status != "archived",
            )
        )
    ).scalar_one_or_none()


def _artifact_ref_id(patch_artifact_ref: str) -> uuid.UUID | None:
    parsed = urlparse(patch_artifact_ref)
    if parsed.scheme != "artifact":
        return None
    raw_id = parsed.netloc or parsed.path.lstrip("/")
    try:
        return uuid.UUID(raw_id)
    except (TypeError, ValueError):
        return None


def _sha256_ref(data: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()
