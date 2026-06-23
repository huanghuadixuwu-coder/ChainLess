"""HTTP supervisor for isolated stdio MCP commands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, HTTPException
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

app = FastAPI(title="Chainless MCP Runtime")
_cleanup_events: dict[str, list[str]] = defaultdict(list)


class RuntimeRequest(BaseModel):
    server_name: str
    command: str
    args: list[str] = Field(default_factory=list)
    max_session_seconds: int = Field(ge=1)
    max_output_bytes: int = Field(ge=1)
    env: dict[str, str] = Field(default_factory=dict)
    env_secret_refs: list[dict[str, Any]] = Field(default_factory=list)
    filesystem_policy: dict[str, Any] = Field(default_factory=dict)
    network_policy: dict[str, Any] = Field(default_factory=dict)
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    restart_policy: dict[str, Any] = Field(default_factory=dict)
    image_ref: str
    package_digest: str
    command_provenance: dict[str, Any]
    approved_payload_hash: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class CleanupRequest(BaseModel):
    server_name: str
    reason: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/discover")
async def discover(request: RuntimeRequest) -> dict[str, Any]:
    _validate_runtime_payload(request)
    try:
        tools = await asyncio.wait_for(_discover(request), timeout=request.max_session_seconds)
    except asyncio.TimeoutError as exc:
        _cleanup_events[request.server_name].append("timeout")
        raise HTTPException(status_code=504, detail="MCP discovery timed out") from exc
    _enforce_output_cap(request, {"tools": tools})
    return {"tools": tools}


@app.post("/call")
async def call(request: RuntimeRequest) -> dict[str, Any]:
    _validate_runtime_payload(request)
    if not request.tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")
    try:
        content = await asyncio.wait_for(_call(request), timeout=_call_timeout(request))
    except asyncio.TimeoutError as exc:
        _cleanup_events[request.server_name].append("timeout")
        raise HTTPException(status_code=504, detail="MCP tool call timed out") from exc
    _enforce_output_cap(request, {"content": content})
    return {"content": content}


@app.post("/cleanup")
async def cleanup(request: CleanupRequest) -> dict[str, Any]:
    _cleanup_events[request.server_name].append(request.reason)
    return {"ok": True, "cleanup_events": list(_cleanup_events[request.server_name])}


@app.get("/evidence/{server_name}")
async def evidence(server_name: str) -> dict[str, Any]:
    return {"server_name": server_name, "cleanup_events": list(_cleanup_events[server_name])}


def _validate_runtime_payload(request: RuntimeRequest) -> None:
    expected_hash = _approved_payload_hash(request)
    if not request.approved_payload_hash:
        raise HTTPException(status_code=403, detail="approved_payload_hash is required")
    if request.approved_payload_hash != expected_hash:
        raise HTTPException(status_code=403, detail="approved_payload_hash does not match payload")
    allowed_hashes = {
        item.strip()
        for item in os.environ.get("MCP_RUNTIME_APPROVED_PAYLOAD_HASHES", "").split(",")
        if item.strip()
    }
    if request.approved_payload_hash not in allowed_hashes:
        raise HTTPException(status_code=403, detail="approved_payload_hash is not allowlisted")
    approved_image = os.environ.get("MCP_RUNTIME_APPROVED_IMAGE")
    if approved_image and request.image_ref != approved_image:
        raise HTTPException(status_code=403, detail="runtime image_ref is not approved")
    if not request.package_digest.startswith(("sha256:", "sha512:")):
        raise HTTPException(status_code=400, detail="package_digest must be a pinned digest")
    for key in ("source", "approved_by", "approved_at"):
        if not request.command_provenance.get(key):
            raise HTTPException(status_code=400, detail=f"command_provenance.{key} is required")
    if request.env:
        raise HTTPException(status_code=400, detail="raw env is forbidden in mcp-runtime payloads")
    if request.env_secret_refs:
        raise HTTPException(status_code=400, detail="env_secret_refs require a runtime secret injector")
    filesystem = request.filesystem_policy
    if filesystem.get("allow_docker_socket") is not False:
        raise HTTPException(status_code=403, detail="docker socket access is forbidden")
    if filesystem.get("allow_backend_fs") is not False:
        raise HTTPException(status_code=403, detail="backend filesystem access is forbidden")
    if filesystem.get("allow_host_fs") is not False:
        raise HTTPException(status_code=403, detail="host filesystem access is forbidden")
    for mount in filesystem.get("mounts", []):
        if not isinstance(mount, dict) or not mount.get("approved"):
            raise HTTPException(status_code=403, detail="unapproved filesystem mounts are forbidden")
    if request.network_policy.get("mode") != "none":
        raise HTTPException(status_code=403, detail="this mcp-runtime service requires network mode none")
    for key in ("memory_mb", "cpus", "pids", "timeout_seconds"):
        value = request.resource_limits.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise HTTPException(status_code=400, detail=f"resource_limits.{key} must be positive")
    if request.max_session_seconds <= 0 or request.max_output_bytes <= 0:
        raise HTTPException(status_code=400, detail="runtime session and output limits must be positive")


def _approved_payload_hash(request: RuntimeRequest) -> str:
    payload = {
        "command": request.command,
        "args": request.args,
        "image_ref": request.image_ref,
        "package_digest": request.package_digest,
        "command_provenance": request.command_provenance,
        "env_secret_refs": request.env_secret_refs,
        "filesystem_policy": request.filesystem_policy,
        "network_policy": request.network_policy,
        "resource_limits": request.resource_limits,
        "max_session_seconds": request.max_session_seconds,
        "max_output_bytes": request.max_output_bytes,
        "restart_policy": request.restart_policy,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def _discover(request: RuntimeRequest) -> list[dict[str, Any]]:
    async with stdio_client(_stdio_params(request)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
    return [
        {
            "name": tool.name,
            "description": tool.description or f"MCP tool from {request.server_name}: {tool.name}",
            "inputSchema": getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}},
        }
        for tool in result.tools
    ]


async def _call(request: RuntimeRequest) -> list[Any]:
    async with stdio_client(_stdio_params(request)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(request.tool_name or "", request.arguments)
    return [_content_item(item) for item in result.content]


def _stdio_params(request: RuntimeRequest) -> StdioServerParameters:
    return StdioServerParameters(
        command=request.command,
        args=request.args,
        env=request.env,
    )


def _content_item(item: Any) -> Any:
    text = getattr(item, "text", None)
    if text is not None:
        return text
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return str(item)


def _enforce_output_cap(request: RuntimeRequest, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > request.max_output_bytes:
        _cleanup_events[request.server_name].append("output_limit")
        raise HTTPException(status_code=413, detail="MCP runtime output exceeds max_output_bytes")


def _call_timeout(request: RuntimeRequest) -> float:
    timeout = request.resource_limits.get("timeout_seconds", request.max_session_seconds)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return float(request.max_session_seconds)
    return float(min(timeout, request.max_session_seconds))
