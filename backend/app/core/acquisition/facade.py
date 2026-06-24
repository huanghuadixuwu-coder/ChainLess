"""Runtime-facing acquisition facade for exploratory code execution evidence."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition import lifecycle
from app.models.acquisition import CapabilityRecommendation, ExplorationRun


_EVIDENCE_SCHEMA_VERSION = "code_as_action_exploration.v1"
_MAX_EXCERPT_CHARS = 1000
_MAX_EVENT_EXCERPT_CHARS = 400
_MAX_TOOL_EVENTS = 24
_RECOMMENDATION_THRESHOLD = 2
_EXPLORABLE_SUCCESS_STATUSES = {
    "detected",
    "exploration_recommended",
    "exploration_approved",
    "explored_failed",
}
_EXPLORABLE_FAILURE_STATUSES = {
    "detected",
    "exploration_recommended",
    "exploration_approved",
    "explored_failed",
}
_VALID_RISK_LEVELS = {"safe", "risky", "high_risk", "blocked"}
_HOST_PATH_TOKEN = r"[^\s,'\")\]]+"
_POSIX_HOST_PATH_RE = re.compile(
    rf"(?<![A-Za-z0-9_.:-])/(?:home|root|var|mnt|Users|tmp|private/(?:tmp|var))(?:/{_HOST_PATH_TOKEN})?(?![A-Za-z0-9_.-])"
)
_WINDOWS_HOST_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s,'\")\]]+")


async def record_code_as_action_exploration(
    *,
    tenant_id: str | uuid.UUID | None,
    user_id: str | uuid.UUID | None,
    conversation_id: str | uuid.UUID | None = None,
    source_run_id: str | None,
    tool_call_id: str | None,
    script: str,
    status: str,
    risk_level: str,
    stdout: str | None = None,
    stderr: str | None = None,
    sandbox_events: list[dict[str, Any]] | None = None,
    failure_reason: str | None = None,
    mount_bundle: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Persist code-as-action evidence without exposing lifecycle internals.

    The agent runtime calls this best-effort facade after a temporary script
    succeeds or fails usefully. The facade intentionally stores a digest and
    bounded/redacted excerpts, never the raw script as the durable key.
    """

    tenant_uuid = _parse_uuid(tenant_id)
    user_uuid = _parse_uuid(user_id)
    if tenant_uuid is None or user_uuid is None:
        return

    conversation_uuid = _parse_uuid(conversation_id)
    source_run = str(source_run_id or f"code-as-action-{uuid.uuid4().hex}")
    evidence = _build_evidence(
        source_run_id=source_run,
        tool_call_id=tool_call_id,
        script=script,
        status=status,
        risk_level=risk_level,
        stdout=stdout,
        stderr=stderr,
        sandbox_events=sandbox_events,
        failure_reason=failure_reason,
        mount_bundle=mount_bundle,
    )

    if db is not None:
        await _record_with_session(
            db,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            conversation_id=conversation_uuid,
            source_run_id=source_run,
            evidence=evidence,
        )
        return

    from app.api.deps import _async_session_factory

    async with _async_session_factory() as session:
        await _record_with_session(
            session,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            conversation_id=conversation_uuid,
            source_run_id=source_run,
            evidence=evidence,
        )
        await session.commit()


async def _record_with_session(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    source_run_id: str,
    evidence: dict[str, Any],
) -> None:
    if evidence["status"] == "succeeded":
        await _record_success(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            source_run_id=source_run_id,
            evidence=evidence,
        )
        return
    await _record_failure(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        source_run_id=source_run_id,
        evidence=evidence,
    )


async def _record_success(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    source_run_id: str,
    evidence: dict[str, Any],
) -> None:
    digest = evidence["script_digest"]
    gap = await lifecycle.record_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind="agent_runtime",
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        dedupe_key=f"code_as_action:success:{digest}",
        title="Reusable code-as-action script candidate",
        description=(
            "A temporary code-as-action script completed successfully and may "
            "represent reusable automation."
        ),
        gap_type="requires_code_patch",
        severity="low",
        source_class="code_as_action_success",
        source_evidence=[
            {
                "kind": "code_as_action_success",
                "message": f"Temporary script completed successfully ({digest}).",
            }
        ],
        evidence={"code_as_action": evidence},
        idempotency_key=_idempotency_key("gap", source_run_id, evidence),
    )

    exploration = await _maybe_record_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap.id,
        source_run_id=source_run_id,
        evidence=evidence,
        status="succeeded",
        allowed_gap_statuses=_EXPLORABLE_SUCCESS_STATUSES,
        current_gap_status=gap.status,
    )
    if exploration is None:
        exploration = await _latest_exploration(db, tenant_id=tenant_id, user_id=user_id, gap_id=gap.id)

    if gap.occurrence_count >= _RECOMMENDATION_THRESHOLD:
        await _maybe_create_recommendation(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            gap_id=gap.id,
            exploration=exploration,
            evidence=evidence,
            success_count=gap.occurrence_count,
        )


async def _record_failure(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    source_run_id: str,
    evidence: dict[str, Any],
) -> None:
    digest = evidence["script_digest"]
    gap_type = (
        "missing_workspace_access"
        if _looks_like_workspace_connector_failure(evidence)
        else "requires_code_patch"
    )
    failure_reason = evidence.get("failure_reason") or "Code-as-action exploration failed."
    gap = await lifecycle.record_gap(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        source_kind="agent_runtime",
        source_run_id=source_run_id,
        conversation_id=conversation_id,
        dedupe_key=f"code_as_action:failure:{gap_type}:{digest}",
        title="Code-as-action exploration failed",
        description=f"A temporary code-as-action script failed: {failure_reason}",
        gap_type=gap_type,
        severity="medium",
        source_class="code_as_action_failure",
        source_evidence=[
            {
                "kind": "code_as_action_failure",
                "message": failure_reason,
            }
        ],
        evidence={"code_as_action": evidence},
        idempotency_key=_idempotency_key("gap", source_run_id, evidence),
    )
    await _maybe_record_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap.id,
        source_run_id=source_run_id,
        evidence=evidence,
        status="failed",
        allowed_gap_statuses=_EXPLORABLE_FAILURE_STATUSES,
        current_gap_status=gap.status,
    )


async def _maybe_record_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    source_run_id: str,
    evidence: dict[str, Any],
    status: str,
    allowed_gap_statuses: set[str],
    current_gap_status: str,
) -> ExplorationRun | None:
    if current_gap_status not in allowed_gap_statuses:
        return None

    exploration = await lifecycle.start_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        source_run_id=source_run_id,
        strategy="code_as_action",
        risk_level=evidence["risk_classification"]["risk_level"],
        bounds=_exploration_bounds(evidence),
        idempotency_key=_idempotency_key("exploration-start", source_run_id, evidence),
    )
    exploration = await lifecycle.complete_exploration(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        exploration_id=exploration.id,
        status=status,
        result_summary=_result_summary(evidence),
        failure_reason=evidence.get("failure_reason") if status != "succeeded" else None,
        idempotency_key=_idempotency_key("exploration-complete", source_run_id, evidence),
    )
    _attach_exploration_evidence(exploration, evidence)
    await db.flush()
    return exploration


async def _maybe_create_recommendation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
    exploration: ExplorationRun | None,
    evidence: dict[str, Any],
    success_count: int,
) -> None:
    existing = (
        await db.execute(
            select(CapabilityRecommendation.id).where(
                CapabilityRecommendation.tenant_id == tenant_id,
                CapabilityRecommendation.user_id == user_id,
                CapabilityRecommendation.gap_id == gap_id,
                CapabilityRecommendation.recommendation_type.in_(
                    ["worker_recommendation", "skill_recommendation"]
                ),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    target_type = _recommended_target_type(evidence)
    recommendation_type = f"{target_type}_recommendation"
    await lifecycle.create_recommendation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        gap_id=gap_id,
        exploration_run_id=exploration.id if exploration is not None else None,
        recommendation_type=recommendation_type,
        title=f"Promote repeated code-as-action script to {target_type}",
        summary=(
            "The same temporary script has succeeded repeatedly and is a "
            f"candidate for a reusable {target_type}."
        ),
        reason="Repeated successful temporary execution is evidence of reusable automation value.",
        evidence={
            "code_as_action": {
                **evidence,
                "observed_success_count": success_count,
            }
        },
        risk_level=evidence["risk_classification"]["risk_level"],
        expected_value={
            "reusable": True,
            "observed_success_count": success_count,
            "reduces_temporary_script_rework": True,
        },
        required_permissions={
            "execution_scope": "code_as_action_temp",
            "risk_level": evidence["risk_classification"]["risk_level"],
            "workspace_connectors": evidence.get("workspace_connectors", []),
        },
        candidate_targets=[
            {
                "target_type": target_type,
                "target_name": f"code_as_action_{evidence['script_digest'].removeprefix('sha256:')[:12]}",
                "target_owner": f"core.{target_type}s",
                "target_payload": {
                    "source_strategy": "code_as_action",
                    "script_digest": evidence["script_digest"],
                },
            }
        ],
        idempotency_key=f"code-as-action-rec:{target_type}:{evidence['script_digest']}",
    )


async def _latest_exploration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    gap_id: uuid.UUID,
) -> ExplorationRun | None:
    return (
        await db.execute(
            select(ExplorationRun)
            .where(
                ExplorationRun.tenant_id == tenant_id,
                ExplorationRun.user_id == user_id,
                ExplorationRun.gap_id == gap_id,
                ExplorationRun.status == "succeeded",
            )
            .order_by(ExplorationRun.completed_at.desc())
        )
    ).scalars().first()


def _attach_exploration_evidence(exploration: ExplorationRun, evidence: dict[str, Any]) -> None:
    event = {
        "kind": "code_as_action_execution",
        "status": evidence["status"],
        "script_digest": evidence["script_digest"],
        "tool_call_id": evidence["tool_calls"][0].get("tool_call_id"),
        "risk_classification": evidence["risk_classification"],
        "outputs": evidence["outputs"],
        "workspace_connectors": evidence.get("workspace_connectors", []),
    }
    if evidence.get("failure_reason"):
        event["failure_reason"] = evidence["failure_reason"]

    existing = list(exploration.tool_events or [])
    exploration.tool_events = [*existing, event][-_MAX_TOOL_EVENTS:]
    exploration.script_ref = evidence["script_digest"]
    exploration.artifact_refs = evidence.get("artifact_refs", [])
    exploration.stdout_excerpt = evidence["outputs"].get("stdout_excerpt")
    exploration.stderr_excerpt = evidence["outputs"].get("stderr_excerpt")


def _build_evidence(
    *,
    source_run_id: str,
    tool_call_id: str | None,
    script: str,
    status: str,
    risk_level: str,
    stdout: str | None,
    stderr: str | None,
    sandbox_events: list[dict[str, Any]] | None,
    failure_reason: str | None,
    mount_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    script_bytes = str(script or "").encode("utf-8", errors="replace")
    digest = f"sha256:{hashlib.sha256(script_bytes).hexdigest()}"
    stdout_excerpt, stdout_truncated = _bounded_text(stdout or "")
    stderr_excerpt, stderr_truncated = _bounded_text(stderr or "")
    clean_failure = _bounded_text(failure_reason or "")[0] if failure_reason else None
    risk = risk_level if risk_level in _VALID_RISK_LEVELS else "risky"

    evidence = {
        "schema_version": _EVIDENCE_SCHEMA_VERSION,
        "status": "succeeded" if status == "succeeded" else "failed",
        "source_run_id": source_run_id,
        "script_digest": digest,
        "inputs": {
            "script_digest": digest,
            "script_length_bytes": len(script_bytes),
            "has_workspace_connector_mounts": bool(_connector_summary(mount_bundle)),
        },
        "outputs": {
            "stdout_excerpt": stdout_excerpt,
            "stdout_truncated": stdout_truncated,
            "stderr_excerpt": stderr_excerpt,
            "stderr_truncated": stderr_truncated,
        },
        "tool_calls": [
            {
                "tool_name": "code_as_action",
                "tool_call_id": str(tool_call_id or ""),
            }
        ],
        "sandbox_events": _sandbox_event_summaries(sandbox_events or []),
        "risk_classification": {
            "tool_name": "code_as_action",
            "risk_level": risk,
        },
        "workspace_connectors": _connector_summary(mount_bundle),
        "artifact_refs": _artifact_refs(sandbox_events or []),
    }
    if clean_failure:
        evidence["failure_reason"] = clean_failure
    return evidence


def _exploration_bounds(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "read_only": True,
        "data_scope": "approved_tools" if evidence.get("workspace_connectors") else "run_workspace",
        "network_scope": "none",
        "write_scope": "run_workspace",
        "cleanup_supported": True,
        "risk_classification": evidence["risk_classification"],
    }


def _result_summary(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "succeeded":
        return f"Code-as-action succeeded for {evidence['script_digest']}."
    return f"Code-as-action failed for {evidence['script_digest']}."


def _recommended_target_type(evidence: dict[str, Any]) -> str:
    stdout = evidence.get("outputs", {}).get("stdout_excerpt") or ""
    if "usage:" in stdout.lower() or evidence.get("workspace_connectors"):
        return "worker"
    return "worker"


def _looks_like_workspace_connector_failure(evidence: dict[str, Any]) -> bool:
    if evidence.get("workspace_connectors"):
        return True
    reason = str(evidence.get("failure_reason") or "").casefold()
    return "workspace_connector" in reason or "/workspace/connectors/" in reason


def _sandbox_event_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for event in events[-_MAX_TOOL_EVENTS:]:
        if not isinstance(event, dict):
            continue
        summary = {
            "type": str(event.get("type", "")),
        }
        if event.get("phase"):
            summary["phase"] = str(event["phase"])
        if event.get("stream"):
            summary["stream"] = str(event["stream"])
        if event.get("data") is not None:
            data, truncated = _bounded_text(
                str(event.get("data", "")),
                limit=_MAX_EVENT_EXCERPT_CHARS,
            )
            summary["data_excerpt"] = data
            summary["data_truncated"] = truncated
        summaries.append(summary)
    return summaries


def _artifact_refs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "sandbox_output" or event.get("stream") != "artifact":
            continue
        data, truncated = _bounded_text(str(event.get("data", "")), limit=_MAX_EVENT_EXCERPT_CHARS)
        refs.append({"kind": "sandbox_artifact", "data_excerpt": data, "truncated": truncated})
    return refs[-10:]


def _connector_summary(mount_bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not mount_bundle:
        return []
    mapped = _as_mapping(mount_bundle)
    mounts = mapped.get("mounts")
    if not isinstance(mounts, list):
        return []
    summaries: list[dict[str, Any]] = []
    for mount in mounts:
        mount_map = _as_mapping(mount)
        if not mount_map.get("connector_id"):
            continue
        summaries.append(
            {
                "connector_id": str(mount_map.get("connector_id")),
                "generation": mount_map.get("generation"),
                "sandbox_mount_path": _redact_text(str(mount_map.get("sandbox_mount_path", ""))),
                "mode": str(mount_map.get("mode", "")),
            }
        )
    return summaries


def _as_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _bounded_text(value: str, *, limit: int = _MAX_EXCERPT_CHARS) -> tuple[str, bool]:
    redacted = _redact_text(value)
    if len(redacted) <= limit:
        return redacted, False
    return redacted[:limit] + "...[truncated]", True


def _redact_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(
        r"/workspace/connectors/([A-Za-z0-9_-]+)(/[^\s,'\")\]]+)",
        r"/workspace/connectors/\1/<redacted-path>",
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_-])/workspace/(?!connectors/[A-Za-z0-9_-]+(?:[\s,'\")\]]|$))[^\s,'\")\]]+",
        "/workspace/<redacted-path>",
        text,
    )
    text = _POSIX_HOST_PATH_RE.sub("<redacted-host-path>", text)
    text = _WINDOWS_HOST_PATH_RE.sub("<redacted-host-path>", text)
    return text


def _parse_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _idempotency_key(scope: str, source_run_id: str, evidence: dict[str, Any]) -> str:
    tool_call_id = evidence["tool_calls"][0].get("tool_call_id") or "unknown"
    digest = evidence["script_digest"].removeprefix("sha256:")
    status = evidence["status"]
    return f"code-as-action:{scope}:{source_run_id}:{tool_call_id}:{status}:{digest[:24]}"
