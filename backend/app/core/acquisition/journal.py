"""Generated private ACQUISITION.md renderer for capability acquisition."""

from __future__ import annotations

import json
import re
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.acquisition.read_model import (
    JournalSection,
    get_acquisition_journal_read_model,
    get_development_patch_artifacts,
)
from app.core.acquisition.schemas import AcquisitionJournalView, JournalEntryContract
from app.core.capabilities.bounds import validate_bounded_json
from app.models.acquisition import (
    AcquisitionJournalEntry,
    AcquisitionProposal,
    ActivationTarget,
    CapabilityGap,
    DevelopmentPatchProposal,
    RuntimePlanningIssue,
)


ACQUISITION_JOURNAL_NAME = "ACQUISITION.md"
DEFAULT_SECTION_LIMIT = 5
MAX_SECTION_LIMIT = 25
MAX_INLINE_JSON_CHARS = 480
MAX_PERSISTED_MARKDOWN_BYTES = 32768
PERSISTED_MARKDOWN_SAFETY_BYTES = 512
SNAPSHOT_ENTRY_KIND = "acquisition_journal_snapshot"

_CREDENTIAL_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
)
_TRACE_KEY_PARTS = (
    "stderr",
    "stdout",
    "trace",
    "trace_id",
    "trace_payload",
)
_PATH_KEY_PARTS = (
    "backend_mount_path",
    "config_path",
    "container_mount_path",
    "host_path",
    "host_realpath",
    "path",
    "profile_storage",
    "sandbox_mount_path",
    "script_ref",
)
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:\\(?:[^\s\\/:*?\"<>|]+\\?)+")
_POSIX_HOST_PATH_RE = re.compile(r"/(?:home|Users|repo|workspace|mnt|var|tmp|etc)/[^\s,;)]+")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_SECRETISH_RE = re.compile(r"(?i)\b(?:sk|pk|api|token|secret|key)[-_][a-z0-9][a-z0-9._-]{7,}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _key_has_part(key: str, parts: tuple[str, ...]) -> bool:
    normalized = key.strip().casefold().replace("-", "_")
    return any(part in normalized for part in parts)


def redact_sensitive_value(value: Any, *, key: str | None = None) -> Any:
    """Redact secrets, raw host paths, and trace-sensitive payloads."""

    key_text = key or ""
    if _key_has_part(key_text, _CREDENTIAL_KEY_PARTS):
        return "[REDACTED_CREDENTIAL]"
    if _key_has_part(key_text, _TRACE_KEY_PARTS):
        return "[REDACTED_TRACE]"
    if isinstance(value, dict):
        return {str(child_key): redact_sensitive_value(child_value, key=str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive_value(item, key=key) for item in value]
    if isinstance(value, str):
        text = value
        if _key_has_part(key_text, _PATH_KEY_PARTS) and (
            _WINDOWS_PATH_RE.search(text) or _POSIX_HOST_PATH_RE.search(text)
        ):
            return "[REDACTED_PATH]"
        text = _BEARER_RE.sub("[REDACTED_CREDENTIAL]", text)
        text = _SECRETISH_RE.sub("[REDACTED_CREDENTIAL]", text)
        text = _WINDOWS_PATH_RE.sub("[REDACTED_PATH]", text)
        text = _POSIX_HOST_PATH_RE.sub("[REDACTED_PATH]", text)
        traceish = re.compile(r"(?i)\btrace[-_][a-z0-9._-]{4,}")
        text = traceish.sub("[REDACTED_TRACE]", text)
        return text
    return _jsonable(value)


def _truncate_json_text(text: str, *, limit: int = MAX_INLINE_JSON_CHARS) -> str:
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    preview_limit = max(0, limit - 160)
    while True:
        bounded = json.dumps(
            {
                "preview": text[:preview_limit],
                "sha256": digest,
                "truncated": True,
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(bounded) <= limit or preview_limit == 0:
            return bounded
        preview_limit = max(0, preview_limit - 40)


def _compact_json(value: Any) -> str:
    redacted = redact_sensitive_value(_jsonable(value))
    text = json.dumps(redacted, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return _truncate_json_text(text)


def _line(text: str | None, *, limit: int = 180) -> str:
    redacted = str(redact_sensitive_value(text or ""))
    collapsed = " ".join(redacted.split())
    if len(collapsed) > limit:
        return f"{collapsed[: limit - 3]}..."
    return collapsed


def _safe_text(value: Any, *, limit: int = 180) -> str:
    return _line(str(value) if value is not None else "", limit=limit)


def _section_header(section: JournalSection, *, section_limit: int) -> list[str]:
    next_offset = section.shown if section.more else 0
    lines = [
        f"## {section.title}",
        f"Total: {section.total} | Showing: {section.shown} | More: {section.more}",
        f"Records: {section.api_path}?limit={section_limit}&offset=0",
    ]
    if section.more:
        lines.append(f"Next page: {section.api_path}?limit={section_limit}&offset={next_offset}")
    return lines


def _render_gap(row: CapabilityGap) -> str:
    return (
        f"- {_safe_text(row.title)} | status={_safe_text(row.status)} | severity={_safe_text(row.severity)} | "
        f"source={_safe_text(row.source_kind)}:{_safe_text(row.source_run_id)} | ref=capability_gap:{row.id} | "
        f"evidence={_compact_json(row.evidence)}"
    )


def _render_proposal(row: AcquisitionProposal) -> str:
    return (
        f"- {_safe_text(row.title)} | status={_safe_text(row.status)} | kind={_safe_text(row.proposal_kind)} | risk={_safe_text(row.risk_level)} | "
        f"gap=capability_gap:{row.gap_id} | proposal=acquisition_proposal:{row.id} | "
        f"effect={_line(row.user_visible_effect)} | evidence={_compact_json(row.evidence)}"
    )


def _render_target(row: ActivationTarget) -> str:
    return (
        f"- {_safe_text(row.target_name)} | type={_safe_text(row.target_type)} | owner={_safe_text(row.target_owner)} | "
        f"status={_safe_text(row.activation_status)} | target=activation_target:{row.id} | "
        f"proposal=acquisition_proposal:{row.proposal_id} | resource={_compact_json(row.activated_resource_ref)}"
    )


def _render_planning_issue(row: RuntimePlanningIssue) -> str:
    return (
        f"- {_safe_text(row.issue_type)} | status={_safe_text(row.status)} | severity={_safe_text(row.severity)} | "
        f"issue=runtime_planning_issue:{row.id} | source={_safe_text(row.source_run_id)} | "
        f"missed={_line(row.missed_signal)} | expected={_line(row.expected_decision_summary)} | "
        f"evidence={_compact_json(row.evidence)}"
    )


def _render_patch(row: AcquisitionProposal, patch: DevelopmentPatchProposal | None) -> str:
    patch_ref = f" | patch=development_patch_proposal:{patch.id}" if patch else ""
    apply_status = f" | apply_check={_safe_text(patch.apply_check_status)}" if patch else ""
    artifact = f" | patch_artifact={_line(patch.patch_artifact_ref)}" if patch else ""
    return (
        f"- {_safe_text(row.title)} | status={_safe_text(row.status)} | proposal=acquisition_proposal:{row.id}"
        f"{patch_ref}{apply_status}{artifact} | handoff={_compact_json(row.development_handoff)}"
    )


def _render_section(section: JournalSection, *, section_limit: int, patch_artifacts: dict[uuid.UUID, DevelopmentPatchProposal]) -> list[str]:
    lines = _section_header(section, section_limit=section_limit)
    if not section.items:
        return [*lines, "- None"]
    rendered: list[str] = []
    for row in section.items:
        if isinstance(row, CapabilityGap):
            rendered.append(_render_gap(row))
        elif isinstance(row, ActivationTarget):
            rendered.append(_render_target(row))
        elif isinstance(row, RuntimePlanningIssue):
            rendered.append(_render_planning_issue(row))
        elif isinstance(row, AcquisitionProposal) and row.proposal_kind == "development_patch_proposal":
            rendered.append(_render_patch(row, patch_artifacts.get(row.id)))
        elif isinstance(row, AcquisitionProposal):
            rendered.append(_render_proposal(row))
        else:
            rendered.append(f"- ref={type(row).__name__}:{getattr(row, 'id', 'unknown')}")
    return [*lines, *rendered]


def _bounded_section_limit(section_limit: int | None) -> int:
    if section_limit is None:
        return DEFAULT_SECTION_LIMIT
    return max(1, min(int(section_limit), MAX_SECTION_LIMIT))


def _bound_markdown_bytes(markdown: str, *, limit: int = MAX_PERSISTED_MARKDOWN_BYTES) -> str:
    if len(markdown.encode("utf-8")) <= limit:
        return markdown
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    notice = (
        "\n\n## Snapshot Truncated\n"
        "This persisted journal snapshot was truncated to fit the storage budget. "
        f"Full regenerated journal sha256={digest}.\n"
    )
    budget = max(0, limit - len(notice.encode("utf-8")) - PERSISTED_MARKDOWN_SAFETY_BYTES)
    prefix = markdown.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip()
    bounded = f"{prefix}{notice}"
    while len(bounded.encode("utf-8")) > limit and budget > 0:
        budget = max(0, budget - 256)
        prefix = markdown.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip()
        bounded = f"{prefix}{notice}"
    return bounded


async def render_acquisition_journal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    section_limit: int | None = None,
) -> AcquisitionJournalView:
    """Render a deterministic private Markdown view from durable records."""

    bounded_limit = _bounded_section_limit(section_limit)
    model = await get_acquisition_journal_read_model(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        section_limit=bounded_limit,
    )
    patch_ids = {
        row.id
        for row in model.development_patch_proposals.items
        if isinstance(row, AcquisitionProposal)
    }
    patch_artifacts = await get_development_patch_artifacts(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        proposal_ids=patch_ids,
    )

    lines = [
        "# ACQUISITION.md",
        "",
        "Generated evidence, not authority. This private journal is rendered from durable acquisition records for this tenant/user scope.",
        "Users cannot edit this journal through Chainless; all changes go through UI/API/audit paths. Manual edits outside the product are ignored or overwritten.",
        "Agents may cite excerpts as evidence, but cannot treat this journal as approval or activation.",
        "",
    ]
    for section in model.sections:
        lines.extend(_render_section(section, section_limit=bounded_limit, patch_artifacts=patch_artifacts))
        lines.append("")

    return AcquisitionJournalView(
        tenant_id=tenant_id,
        user_id=user_id,
        generated_at=_now(),
        entries=[],
        rendered_markdown="\n".join(lines).rstrip() + "\n",
    )


def _entry_contract(row: AcquisitionJournalEntry) -> JournalEntryContract:
    return JournalEntryContract(
        id=row.id,
        entry_kind=row.entry_kind,
        subject_ref=row.subject_ref,
        rendered_markdown=row.rendered_markdown,
        source_refs=row.source_refs,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def write_acquisition_journal_snapshot(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    section_limit: int | None = None,
) -> AcquisitionJournalView:
    """Persist one idempotent generated snapshot row for the private journal."""

    view = await render_acquisition_journal(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        section_limit=section_limit,
    )
    subject_ref = validate_bounded_json(
        {"name": ACQUISITION_JOURNAL_NAME, "role": "private_generated_evidence_not_authority"},
        field="subject_ref",
    )
    source_refs = validate_bounded_json(
        [
            {"type": "capability_gaps", "path": "/api/v1/acquisition/gaps"},
            {"type": "acquisition_proposals", "path": "/api/v1/acquisition/proposals"},
            {"type": "activation_targets", "path": "/api/v1/acquisition/activation-targets"},
            {"type": "runtime_planning_issues", "path": "/api/v1/acquisition/runtime-planning-issues"},
            {"type": "development_patch_proposals", "path": "/api/v1/acquisition/development-patch-proposals"},
        ],
        field="source_refs",
    )
    persisted_markdown = _bound_markdown_bytes(view.rendered_markdown)
    stmt = pg_insert(AcquisitionJournalEntry).values(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        entry_kind=SNAPSHOT_ENTRY_KIND,
        subject_ref=subject_ref,
        rendered_markdown=persisted_markdown,
        source_refs=source_refs,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            AcquisitionJournalEntry.tenant_id,
            AcquisitionJournalEntry.user_id,
            AcquisitionJournalEntry.entry_kind,
        ],
        index_where=AcquisitionJournalEntry.entry_kind == SNAPSHOT_ENTRY_KIND,
        set_={
            "subject_ref": subject_ref,
            "rendered_markdown": persisted_markdown,
            "source_refs": source_refs,
            "updated_at": _now(),
        },
    )
    await db.execute(stmt)
    row = (
        await db.execute(
            select(AcquisitionJournalEntry).where(
                AcquisitionJournalEntry.tenant_id == tenant_id,
                AcquisitionJournalEntry.user_id == user_id,
                AcquisitionJournalEntry.entry_kind == SNAPSHOT_ENTRY_KIND,
            )
        )
    ).scalar_one()

    return AcquisitionJournalView(
        tenant_id=view.tenant_id,
        user_id=view.user_id,
        generated_at=view.generated_at,
        entries=[_entry_contract(row)],
        rendered_markdown=persisted_markdown,
    )
