"""Canonical activation snapshot hashing for acquisition proposals."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.acquisition import AcquisitionProposal, AcquisitionVerification

SNAPSHOT_SCHEMA_VERSION = "v3.activation_snapshot.v1"
_DIGEST_PREFIX = "sha256:"
_RAW_SECRET_EXACT_KEYS = {
    "api_key",
    "auth",
    "auth_header",
    "authorization",
    "client_secret",
    "cookie",
    "cookies",
    "password",
    "private_key",
    "secret",
    "secret_ref",
    "session_cookie",
    "token",
}
_RAW_SECRET_SUFFIXES = (
    "_api_key",
    "_auth",
    "_auth_header",
    "_authorization",
    "_cookie",
    "_password",
    "_private_key",
    "_secret",
    "_secret_ref",
    "_token",
)
_MUTABLE_TEXT_KEYS = (
    "blob",
    "blob_text",
    "body",
    "content",
    "display_url",
    "html",
    "log",
    "raw",
    "stderr",
    "stdout",
    "text",
    "url",
)
_REF_DIGEST_KEYS = ("artifact_id", "content_digest", "digest", "hash", "id", "ref", "sha256")


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump(mode="json"))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def _canonicalize(value: Any) -> Any:
    value = jsonable(value)
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_value(value: Any) -> str:
    return f"{_DIGEST_PREFIX}{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def snapshot_hash(payload: dict[str, Any]) -> str:
    return digest_value(payload)


def _is_secret_key(key: str) -> bool:
    key = key.casefold()
    return key in _RAW_SECRET_EXACT_KEYS or any(key.endswith(suffix) for suffix in _RAW_SECRET_SUFFIXES)


def _is_mutable_text_key(key: str) -> bool:
    key = key.casefold()
    return any(part in key for part in _MUTABLE_TEXT_KEYS)


def _digest_ref(ref: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for key, value in sorted(ref.items(), key=lambda item: str(item[0])):
        normalized_key = str(key)
        if _is_secret_key(normalized_key) or _is_mutable_text_key(normalized_key):
            continue
        if normalized_key in _REF_DIGEST_KEYS or normalized_key.endswith("_id") or normalized_key.endswith("_ref"):
            summarized[normalized_key] = jsonable(value)
    if not any(key in summarized for key in ("digest", "sha256", "content_digest", "hash")):
        summarized["ref_digest"] = digest_value(ref)
    return summarized


def sanitize_snapshot_value(value: Any, *, parent_key: str = "") -> Any:
    value = jsonable(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda entry: str(entry[0])):
            normalized_key = str(key)
            if _is_secret_key(normalized_key):
                continue
            elif _is_mutable_text_key(normalized_key):
                sanitized[f"{normalized_key}_digest"] = digest_value(item)
            else:
                sanitized[normalized_key] = sanitize_snapshot_value(item, parent_key=normalized_key)
        return sanitized
    if isinstance(value, list):
        return [sanitize_snapshot_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and (_is_mutable_text_key(parent_key) or len(value) > 512):
        return {"digest": digest_value(value), "byte_length": len(value.encode("utf-8"))}
    return value


def _verification_payload(verification: AcquisitionVerification | dict[str, Any]) -> dict[str, Any]:
    if isinstance(verification, AcquisitionVerification):
        verification_id = verification.id
        verification_kind = verification.verification_kind
        status = verification.status
        input_fixture = verification.input_fixture
        expected_result = verification.expected_result
        actual_result = verification.actual_result
        artifact_refs = verification.artifact_refs
        error_code = verification.error_code
    else:
        verification_id = verification.get("id") or verification.get("verification_id")
        verification_kind = verification.get("verification_kind")
        status = verification.get("status")
        input_fixture = verification.get("input_fixture", {})
        expected_result = verification.get("expected_result", {})
        actual_result = verification.get("actual_result", {})
        artifact_refs = verification.get("artifact_refs", [])
        error_code = verification.get("error_code")

    return {
        "verification_id": str(verification_id) if verification_id else None,
        "verification_kind": verification_kind,
        "status": status,
        "input_fixture_digest": digest_value(input_fixture),
        "expected_result_digest": digest_value(expected_result),
        "actual_result_digest": digest_value(actual_result),
        "artifact_refs": [_digest_ref(ref) for ref in artifact_refs if isinstance(ref, dict)],
        "error_code": error_code,
    }


def permission_bundles_for_proposal(proposal: AcquisitionProposal) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    if isinstance(proposal.permission_bundle, dict):
        bundles.append(proposal.permission_bundle)
    targets = [proposal.primary_target, *(proposal.secondary_targets or [])]
    for target in targets:
        if isinstance(target, dict) and isinstance(target.get("permission_bundle"), dict):
            bundles.append(target["permission_bundle"])
    return bundles


def credential_ref_ids_from_bundles(permission_bundles: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for bundle in permission_bundles:
        raw_refs = bundle.get("credential_connection_refs") or []
        if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, Iterable):
            raw_refs = [raw_refs]
        for ref in raw_refs:
            refs.append(str(ref))
    return sorted(dict.fromkeys(refs))


def build_activation_snapshot_payload(
    *,
    proposal: AcquisitionProposal,
    verification: AcquisitionVerification | dict[str, Any],
    credential_generations: list[dict[str, Any]] | None = None,
    runtime_owner_version_refs: list[dict[str, Any]] | None = None,
    egress_policy_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    permission_bundles = permission_bundles_for_proposal(proposal)
    payload = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "proposal_id": str(proposal.id),
        "proposal_kind": proposal.proposal_kind,
        "proposal_status": "verified",
        "proposal_reason": proposal.reason,
        "primary_target_payload": sanitize_snapshot_value(proposal.primary_target),
        "secondary_target_payloads": sanitize_snapshot_value(proposal.secondary_targets or []),
        "permission_bundles": sanitize_snapshot_value(permission_bundles),
        "verification_result": _verification_payload(verification),
        "rollback_plan": sanitize_snapshot_value(proposal.rollback_plan),
        "user_visible_effect": proposal.user_visible_effect,
        "runtime_owner_version_refs": sanitize_snapshot_value(runtime_owner_version_refs or []),
        "credential_generations": sanitize_snapshot_value(credential_generations or []),
        "egress_policy_snapshots": sanitize_snapshot_value(egress_policy_snapshots or []),
    }
    return _canonicalize(payload)
