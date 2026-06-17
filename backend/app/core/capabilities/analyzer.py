"""LLM analyzer normalization for inactive capability candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.capabilities.bounds import validate_bounded_json
from app.core.capabilities.rules import RunAnalysisSignal
from app.core.capabilities.schemas import CANDIDATE_TYPES


MAX_ANALYZER_OUTPUT_CHARS = 12000
MAX_EVIDENCE_ITEMS = 5
MAX_EVIDENCE_CHARS = 500
MAX_BODY_CHARS = 2000
MAX_TITLE_CHARS = 255
MAX_DEDUPE_KEY_CHARS = 255


@dataclass(frozen=True)
class AnalyzerCandidate:
    """Candidate proposal normalized from strict analyzer JSON."""

    candidate_type: str
    title: str
    body: str | None
    dedupe_key: str
    confidence: float
    source_evidence: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


async def analyze_run_for_candidates(
    gateway: Any,
    *,
    provider: str,
    tenant_id: str,
    signal: RunAnalysisSignal,
    run_payload: dict[str, Any],
) -> list[AnalyzerCandidate]:
    """Call the analyzer and parse only strict JSON candidate output."""

    if not signal.should_analyze:
        return []

    content = ""
    async for event in gateway.chat_stream(
        provider,
        _build_analyzer_messages(signal=signal, run_payload=run_payload),
        tools=None,
        max_tokens=1200,
        tenant_id=tenant_id,
    ):
        if event.get("type") == "text":
            content += str(event.get("content") or "")
            if len(content) > MAX_ANALYZER_OUTPUT_CHARS:
                return []

    try:
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    if not isinstance(parsed, dict):
        return []
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[AnalyzerCandidate] = []
    for raw_candidate in raw_candidates:
        candidate = _parse_candidate(raw_candidate)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _build_analyzer_messages(
    *,
    signal: RunAnalysisSignal,
    run_payload: dict[str, Any],
) -> list[dict[str, str]]:
    instructions = (
        "Analyze the completed chat run for possible inactive personal capability candidates. "
        "Return strict JSON only: {\"candidates\":[...]}. Candidate type must be one of "
        "memory, skill, worker. Do not include markdown or explanatory text. Candidates are "
        "inactive suggestions only and must include title, dedupe_key, confidence, "
        "source_evidence, and payload."
    )
    evidence = {
        "signal": signal.to_payload(),
        "run": {
            "source_run_id": run_payload.get("source_run_id"),
            "conversation_id": run_payload.get("conversation_id"),
            "user_messages": run_payload.get("user_messages") or [],
            "assistant_content": run_payload.get("assistant_content") or "",
            "tool_events": run_payload.get("tool_events") or [],
            "artifacts": run_payload.get("artifacts") or [],
        },
    }
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=True, sort_keys=True)},
    ]


def _parse_candidate(raw_candidate: Any) -> AnalyzerCandidate | None:
    if not isinstance(raw_candidate, dict):
        return None
    candidate_type = str(raw_candidate.get("type") or raw_candidate.get("candidate_type") or "").strip().lower()
    if candidate_type not in CANDIDATE_TYPES:
        return None
    title = _trim_text(raw_candidate.get("title"), MAX_TITLE_CHARS)
    dedupe_key = _trim_text(raw_candidate.get("dedupe_key"), MAX_DEDUPE_KEY_CHARS)
    if not title or not dedupe_key:
        return None

    body = _trim_text(raw_candidate.get("body"), MAX_BODY_CHARS) or None
    source_evidence = _parse_source_evidence(raw_candidate.get("source_evidence"))
    payload = raw_candidate.get("payload") if isinstance(raw_candidate.get("payload"), dict) else {}
    try:
        bounded_payload = validate_bounded_json(payload, field="payload")
    except Exception:
        return None

    return AnalyzerCandidate(
        candidate_type=candidate_type,
        title=title,
        body=body,
        dedupe_key=dedupe_key,
        confidence=_clamp_confidence(raw_candidate.get("confidence")),
        source_evidence=source_evidence,
        payload=bounded_payload,
    )


def _parse_source_evidence(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    evidence: list[str] = []
    for item in value:
        text = _trim_text(item, MAX_EVIDENCE_CHARS)
        if text:
            evidence.append(text)
        if len(evidence) >= MAX_EVIDENCE_ITEMS:
            break
    return evidence


def _trim_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
