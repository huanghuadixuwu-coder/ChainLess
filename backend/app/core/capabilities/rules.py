"""Deterministic rule gate for capability candidate analysis."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


_REMEMBER_RE = re.compile(r"\bremember\b", re.IGNORECASE)
_NEXT_TIME_RE = re.compile(r"\bnext\s+time\b|\bfrom\s+now\s+on\b", re.IGNORECASE)
_ALWAYS_RE = re.compile(r"\balways\b|\bevery\s+time\b|\bwhenever\b", re.IGNORECASE)
_CORRECTION_RE = re.compile(
    r"\b(no|actually|correction|i\s+meant|not\s+.+\b(use|do|run))\b",
    re.IGNORECASE,
)

_MIN_FALLBACK_CHARS = 140
_MIN_FALLBACK_WORDS = 24


@dataclass(frozen=True)
class RunAnalysisSignal:
    """Serializable evidence that a completed run is worth analyzer spend."""

    should_analyze: bool
    reasons: list[str] = field(default_factory=list)
    user_correction: bool = False
    user_text: str = ""
    assistant_text: str = ""
    tool_names: list[str] = field(default_factory=list)
    artifact_refs: list[dict[str, str]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def should_analyze_run(
    *,
    user_messages: list[str] | tuple[str, ...],
    assistant_messages: list[str] | tuple[str, ...] | None = None,
    tool_events: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    artifacts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> RunAnalysisSignal:
    """Return deterministic eligibility signals before any LLM analyzer call."""

    user_text = _join_text(user_messages)
    assistant_text = _join_text(assistant_messages or [])
    reasons: list[str] = []

    if _REMEMBER_RE.search(user_text):
        reasons.append("remember_text")
    if _NEXT_TIME_RE.search(user_text):
        reasons.append("next_time_text")
    if _ALWAYS_RE.search(user_text):
        reasons.append("always_text")

    user_correction = bool(_CORRECTION_RE.search(user_text))
    if user_correction:
        reasons.append("user_correction")

    tool_names = _completed_tool_names(tool_events or [])
    if len(set(tool_names)) >= 2 or len(tool_names) >= 3:
        reasons.append("tool_chain")

    artifact_refs = _artifact_refs(artifacts or [])
    if artifact_refs:
        reasons.append("artifact")

    if not reasons and _looks_like_useful_run(user_text, assistant_text):
        reasons.append("fallback_useful_run")

    deduped_reasons = list(dict.fromkeys(reasons))
    return RunAnalysisSignal(
        should_analyze=bool(deduped_reasons),
        reasons=deduped_reasons,
        user_correction=user_correction,
        user_text=user_text[-2000:],
        assistant_text=assistant_text[-2000:],
        tool_names=tool_names[:10],
        artifact_refs=artifact_refs[:10],
    )


def signal_from_payload(payload: dict[str, Any] | None) -> RunAnalysisSignal:
    """Rehydrate a signal stored in the durable analysis outbox payload."""

    if not isinstance(payload, dict):
        return RunAnalysisSignal(should_analyze=False)
    raw_signal = payload.get("signal")
    if not isinstance(raw_signal, dict):
        return should_analyze_run(
            user_messages=_coerce_text_list(payload.get("user_messages")),
            assistant_messages=[str(payload.get("assistant_content") or "")],
            tool_events=_coerce_dict_list(payload.get("tool_events")),
            artifacts=_coerce_dict_list(payload.get("artifacts")),
        )
    reasons = [str(reason) for reason in raw_signal.get("reasons") or [] if str(reason)]
    return RunAnalysisSignal(
        should_analyze=bool(raw_signal.get("should_analyze", bool(reasons))),
        reasons=reasons,
        user_correction=bool(raw_signal.get("user_correction", False)),
        user_text=str(raw_signal.get("user_text") or "")[-2000:],
        assistant_text=str(raw_signal.get("assistant_text") or "")[-2000:],
        tool_names=[str(name) for name in raw_signal.get("tool_names") or []][:10],
        artifact_refs=_artifact_refs(_coerce_dict_list(raw_signal.get("artifact_refs"))),
    )


def _join_text(messages: list[str] | tuple[str, ...]) -> str:
    return "\n".join(str(message or "").strip() for message in messages if str(message or "").strip())


def _completed_tool_names(tool_events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[str]:
    names: list[str] = []
    for event in tool_events:
        status = str(event.get("status") or event.get("state") or "completed").lower()
        if status not in {"completed", "success", "succeeded", "ok"}:
            continue
        name = str(event.get("name") or event.get("tool_name") or "").strip()
        if name:
            names.append(name[:120])
    return names


def _artifact_refs(artifacts: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("id") or "").strip()
        path = str(artifact.get("path") or artifact.get("workspace_path") or "").strip()
        if artifact_id or path:
            refs.append({"id": artifact_id[:120], "path": path[:240]})
    return refs


def _looks_like_useful_run(user_text: str, assistant_text: str) -> bool:
    combined = f"{user_text}\n{assistant_text}".strip()
    if len(combined) < _MIN_FALLBACK_CHARS:
        return False
    word_count = len(re.findall(r"\w+", combined))
    if word_count < _MIN_FALLBACK_WORDS:
        return False
    low_signal = combined.lower().strip()
    return low_signal not in {"hi", "hello", "hey", "thanks", "thank you"}


def _coerce_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]
