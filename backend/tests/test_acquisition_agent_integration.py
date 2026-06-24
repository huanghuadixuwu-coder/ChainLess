"""Agent runtime integration coverage for code-as-action acquisition evidence."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.agent.engine import run_agent
from app.core.workspace_connectors.mounts import (
    WorkspaceConnectorMount,
    WorkspaceConnectorMountBundle,
)
from app.models.acquisition import CapabilityGap, CapabilityRecommendation, ExplorationRun
from app.models.conversation import Conversation
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def _conversation_id(tenant_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    async with _async_session_factory() as db:
        conversation = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title="code-as-action acquisition",
        )
        db.add(conversation)
        await db.commit()
        return conversation.id


class _CodeGateway:
    def __init__(self, script: str, *, tool_call_id: str) -> None:
        self.script = script
        self.tool_call_id = tool_call_id
        self.calls = 0

    async def chat_stream(self, provider, messages, tools, tenant_id=None):
        self.calls += 1
        if self.calls == 1:
            yield {
                "type": "tool_call",
                "index": 0,
                "id": self.tool_call_id,
                "name": "code_as_action",
                "arguments": json.dumps({"script": self.script}),
            }
            return
        yield {"type": "text", "content": "done"}


class _SuccessfulSandbox:
    def __init__(self, *, stdout: str = "rows=3\n", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict] = []

    async def execute_disposable_parent(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "container_id": "code-as-action-parent",
            "deleted": True,
            "active_container_ids": [],
            "cleanup_errors": [],
            "exit_code": 0,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class _FailingSandbox:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[dict] = []

    async def execute_disposable_parent(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        raise RuntimeError(self.message)


class _NonZeroExitSandbox:
    def __init__(self, *, stderr: str, stdout: str = "", exit_code: int = 1) -> None:
        self.stderr = stderr
        self.stdout = stdout
        self.exit_code = exit_code
        self.calls: list[dict] = []

    async def execute_disposable_parent(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "container_id": "code-as-action-parent",
            "deleted": True,
            "active_container_ids": [],
            "cleanup_errors": [],
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


async def _run_code_as_action(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    script: str,
    sandbox,
    run_id: str,
    tool_call_id: str,
    connector_mount_context: dict | None = None,
    acquisition_recorder=None,
) -> list[dict]:
    return [
        event
        async for event in run_agent(
            _CodeGateway(script, tool_call_id=tool_call_id),
            sandbox,
            "default",
            [{"role": "user", "content": "run reusable analysis code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            run_id=run_id,
            connector_mount_context=connector_mount_context,
            acquisition_recorder=acquisition_recorder,
        )
    ]


async def _acquisition_rows(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[list[CapabilityGap], list[ExplorationRun], list[CapabilityRecommendation]]:
    async with _async_session_factory() as db:
        gaps = list(
            (
                await db.execute(
                    select(CapabilityGap).where(
                        CapabilityGap.tenant_id == tenant_id,
                        CapabilityGap.user_id == user_id,
                    )
                )
            ).scalars()
        )
        explorations = list(
            (
                await db.execute(
                    select(ExplorationRun).where(
                        ExplorationRun.tenant_id == tenant_id,
                        ExplorationRun.user_id == user_id,
                    )
                )
            ).scalars()
        )
        recommendations = list(
            (
                await db.execute(
                    select(CapabilityRecommendation).where(
                        CapabilityRecommendation.tenant_id == tenant_id,
                        CapabilityRecommendation.user_id == user_id,
                    )
                )
            ).scalars()
        )
        return gaps, explorations, recommendations


async def _wait_for_acquisition_rows(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    expected_gaps: int,
    expected_explorations: int | None = None,
    expected_recommendations: int | None = None,
    expected_gap_occurrence_count: int | None = None,
) -> tuple[list[CapabilityGap], list[ExplorationRun], list[CapabilityRecommendation]]:
    deadline = asyncio.get_running_loop().time() + 2.0
    last_rows = await _acquisition_rows(tenant_id, user_id)
    while True:
        gaps, explorations, recommendations = last_rows
        if (
            len(gaps) >= expected_gaps
            and (
                expected_explorations is None
                or len(explorations) >= expected_explorations
            )
            and (
                expected_recommendations is None
                or len(recommendations) >= expected_recommendations
            )
            and (
                expected_gap_occurrence_count is None
                or any(
                    gap.occurrence_count >= expected_gap_occurrence_count
                    for gap in gaps
                )
            )
        ):
            return last_rows
        if asyncio.get_running_loop().time() >= deadline:
            return last_rows
        await asyncio.sleep(0.02)
        last_rows = await _acquisition_rows(tenant_id, user_id)


async def test_code_as_action_success_creates_exploration_evidence(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    script = "print('rows=3')"

    events = await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script=script,
        sandbox=_SuccessfulSandbox(stdout="rows=3\n", stderr=""),
        run_id="code-success-run",
        tool_call_id="code-success-call",
    )

    assert any(event["type"] == "tool_result" and "rows=3" in event["result"] for event in events)
    gaps, explorations, recommendations = await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
    )
    assert len(gaps) == 1
    assert len(explorations) == 1
    assert recommendations == []

    gap = gaps[0]
    exploration = explorations[0]
    evidence_text = repr({"gap": gap.evidence, "source": gap.source_evidence, "exploration": exploration.tool_events})
    assert gap.gap_type == "requires_code_patch"
    assert gap.status == "explored_success"
    assert gap.occurrence_count == 1
    assert gap.evidence["code_as_action"]["status"] == "succeeded"
    assert gap.evidence["code_as_action"]["script_digest"].startswith("sha256:")
    assert gap.evidence["code_as_action"]["outputs"]["stdout_excerpt"] == "rows=3\n"
    assert exploration.status == "succeeded"
    assert exploration.strategy == "code_as_action"
    assert exploration.script_ref == gap.evidence["code_as_action"]["script_digest"]
    assert exploration.stdout_excerpt == "rows=3\n"
    assert any(item.get("kind") == "code_as_action_execution" for item in exploration.tool_events)
    assert script not in evidence_text


async def test_success_acquisition_recording_does_not_block_tool_result_or_next_iteration(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    tool_result_seen = asyncio.Event()
    next_text_seen = asyncio.Event()
    events: list[dict] = []

    async def slow_recorder(**kwargs) -> None:
        started.set()
        await release.wait()
        finished.set()

    async def consume_events() -> None:
        async for event in run_agent(
            _CodeGateway("print('rows=3')", tool_call_id="code-slow-record-call"),
            _SuccessfulSandbox(stdout="rows=3\n"),
            "default",
            [{"role": "user", "content": "run reusable analysis code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            run_id="code-slow-record-run",
            acquisition_recorder=slow_recorder,
        ):
            events.append(event)
            if event["type"] == "tool_result":
                tool_result_seen.set()
            elif tool_result_seen.is_set() and event["type"] == "text":
                next_text_seen.set()

    consume_task = asyncio.create_task(consume_events())
    try:
        await asyncio.wait_for(tool_result_seen.wait(), timeout=1)
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not finished.is_set()
        await asyncio.wait_for(next_text_seen.wait(), timeout=1)
        assert not finished.is_set()
    finally:
        release.set()

    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.wait_for(consume_task, timeout=1)
    assert any(
        event["type"] == "tool_result" and "rows=3" in event["result"]
        for event in events
    )
    assert any(event["type"] == "text" and event["content"] == "done" for event in events)


async def test_failure_acquisition_recording_does_not_block_tool_error_or_next_iteration(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    tool_error_seen = asyncio.Event()
    next_text_seen = asyncio.Event()
    events: list[dict] = []

    async def slow_recorder(**kwargs) -> None:
        started.set()
        await release.wait()
        finished.set()

    async def consume_events() -> None:
        async for event in run_agent(
            _CodeGateway("import private_sdk", tool_call_id="code-slow-failure-record-call"),
            _FailingSandbox("ModuleNotFoundError: No module named 'private_sdk'"),
            "default",
            [{"role": "user", "content": "run reusable analysis code"}],
            tools=[CODE_AS_ACTION_TOOL],
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            run_id="code-slow-failure-record-run",
            acquisition_recorder=slow_recorder,
        ):
            events.append(event)
            if event["type"] == "tool_error":
                tool_error_seen.set()
            elif tool_error_seen.is_set() and event["type"] == "text":
                next_text_seen.set()

    consume_task = asyncio.create_task(consume_events())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not finished.is_set()
        await asyncio.wait_for(tool_error_seen.wait(), timeout=1)
        assert not finished.is_set()
        await asyncio.wait_for(next_text_seen.wait(), timeout=1)
        assert not finished.is_set()
    finally:
        release.set()

    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.wait_for(consume_task, timeout=1)
    assert any(
        event["type"] == "tool_error" and "private_sdk" in event["error"]
        for event in events
    )
    assert any(event["type"] == "text" and event["content"] == "done" for event in events)


async def test_acquisition_recorder_receives_incrementally_capped_success_trace(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    long_stdout = "stdout-" + ("x" * 5000)
    long_stderr = "stderr-" + ("y" * 5000)
    recorded = asyncio.Event()
    captured: dict = {}

    async def recorder(**kwargs) -> None:
        captured.update(kwargs)
        recorded.set()

    events = await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script="print('large output')",
        sandbox=_SuccessfulSandbox(stdout=long_stdout, stderr=long_stderr),
        run_id="code-capped-success-run",
        tool_call_id="code-capped-success-call",
        acquisition_recorder=recorder,
    )

    await asyncio.wait_for(recorded.wait(), timeout=1)
    assert any(
        event["type"] == "sandbox_output"
        and event.get("stream") == "stdout"
        and event.get("data") == long_stdout
        for event in events
    )
    assert len(captured["stdout"]) <= 1001
    assert len(captured["stderr"]) <= 1001
    assert len(captured["sandbox_events"]) <= 24
    assert all(
        len(str(event.get("data", ""))) <= 401
        for event in captured["sandbox_events"]
    )


async def test_acquisition_recorder_receives_incrementally_capped_failure_error(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    long_error = "ModuleNotFoundError: " + ("private_sdk " * 500)
    recorded = asyncio.Event()
    captured: dict = {}

    async def recorder(**kwargs) -> None:
        captured.update(kwargs)
        recorded.set()

    events = await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script="import private_sdk",
        sandbox=_FailingSandbox(long_error),
        run_id="code-capped-failure-run",
        tool_call_id="code-capped-failure-call",
        acquisition_recorder=recorder,
    )

    await asyncio.wait_for(recorded.wait(), timeout=1)
    assert any(
        event["type"] == "tool_error" and "private_sdk" in event["error"]
        for event in events
    )
    assert len(captured["stderr"]) <= 1001
    assert len(captured["failure_reason"]) <= 1001
    assert len(captured["sandbox_events"]) <= 24
    assert all(
        len(str(event.get("data", ""))) <= 401
        for event in captured["sandbox_events"]
    )


async def test_repeated_success_creates_worker_or_skill_recommendation(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    script = "total = sum([1, 2, 3])\nprint(total)"

    await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script=script,
        sandbox=_SuccessfulSandbox(stdout="6\n"),
        run_id="code-repeat-run-1",
        tool_call_id="code-repeat-call-1",
    )
    await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
    )
    await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script=script,
        sandbox=_SuccessfulSandbox(stdout="6\n"),
        run_id="code-repeat-run-2",
        tool_call_id="code-repeat-call-2",
    )

    gaps, explorations, recommendations = await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
        expected_recommendations=1,
        expected_gap_occurrence_count=2,
    )
    assert len(gaps) == 1
    assert len(explorations) == 1
    assert len(recommendations) == 1
    assert gaps[0].occurrence_count == 2
    assert recommendations[0].recommendation_type in {
        "worker_recommendation",
        "skill_recommendation",
    }
    assert recommendations[0].exploration_run_id == explorations[0].id
    assert recommendations[0].evidence["code_as_action"]["script_digest"] == gaps[0].evidence["code_as_action"]["script_digest"]
    assert recommendations[0].candidate_targets[0]["target_type"] in {"worker", "skill"}
    assert script not in repr(recommendations[0].evidence)


async def test_failed_exploration_creates_gap_with_failure_reason(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    failure_reason = "ModuleNotFoundError: No module named 'private_sdk'"

    events = await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script="import private_sdk\nprint(private_sdk.run())",
        sandbox=_FailingSandbox(failure_reason),
        run_id="code-failure-run",
        tool_call_id="code-failure-call",
    )

    assert any(event["type"] == "tool_error" and "private_sdk" in event["error"] for event in events)
    gaps, explorations, recommendations = await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
    )
    assert len(gaps) == 1
    assert len(explorations) == 1
    assert recommendations == []
    assert gaps[0].status == "explored_failed"
    assert gaps[0].gap_type == "requires_code_patch"
    assert "private_sdk" in gaps[0].evidence["code_as_action"]["failure_reason"]
    assert explorations[0].status == "failed"
    assert "private_sdk" in explorations[0].failure_reason


async def test_nonzero_exit_code_records_failed_exploration_not_success(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    failure_reason = "ModuleNotFoundError: No module named 'private_sdk'"

    events = await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script="import private_sdk\nprint(private_sdk.run())",
        sandbox=_NonZeroExitSandbox(stderr=failure_reason),
        run_id="code-nonzero-exit-run",
        tool_call_id="code-nonzero-exit-call",
    )

    assert any(
        event["type"] == "sandbox_output"
        and event.get("stream") == "stderr"
        and "private_sdk" in event.get("data", "")
        for event in events
    )
    assert any(
        event["type"] == "tool_error"
        and "exit code 1" in event["error"]
        and "private_sdk" in event["error"]
        for event in events
    )
    assert not any(event["type"] == "tool_result" for event in events)

    gaps, explorations, recommendations = await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
    )
    assert len(gaps) == 1
    assert len(explorations) == 1
    assert recommendations == []
    assert gaps[0].status == "explored_failed"
    assert gaps[0].gap_type == "requires_code_patch"
    assert gaps[0].evidence["code_as_action"]["status"] == "failed"
    assert "private_sdk" in gaps[0].evidence["code_as_action"]["failure_reason"]
    assert "private_sdk" in gaps[0].evidence["code_as_action"]["outputs"]["stderr_excerpt"]
    assert explorations[0].status == "failed"
    assert "private_sdk" in explorations[0].failure_reason


async def test_code_as_action_connector_failure_records_gap_without_listing_stale_workspace_files(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    conversation_id = await _conversation_id(tenant_id, user_id)
    connector_id = f"wsc_{uuid.uuid4().hex}"
    bundle = WorkspaceConnectorMountBundle(
        schema_version="workspace_connector_mounts.v1",
        mounts=[
            WorkspaceConnectorMount(
                connector_id=connector_id,
                generation=1,
                container_mount_path=f"/workspace/connectors/{connector_id}",
                backend_mount_path=f"/workspace/connectors/{connector_id}",
                sandbox_mount_path=f"/workspace/connectors/{connector_id}",
                mode="read_only",
            )
        ],
    )
    failure_reason = (
        "WORKSPACE_CONNECTOR_GENERATION_MISMATCH: stale files "
        f"/workspace/connectors/{connector_id}/old.csv, "
        "E:\\private\\approved-source\\secret.csv, "
        "/home/alice/private/source.csv, "
        "/var/folders/app/token.json, "
        "/mnt/c/Users/alice/key.txt, "
        "/Users/alice/Desktop/plain.txt, "
        "/tmp/chainless-secret.sock, "
        "/private/tmp/staged-secret.txt"
    )

    await _run_code_as_action(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        script=f"open('/workspace/connectors/{connector_id}/old.csv').read()",
        sandbox=_FailingSandbox(failure_reason),
        run_id="code-connector-failure-run",
        tool_call_id="code-connector-failure-call",
        connector_mount_context={"workspace_connector_mount_bundle": bundle},
    )

    gaps, explorations, recommendations = await _wait_for_acquisition_rows(
        tenant_id,
        user_id,
        expected_gaps=1,
        expected_explorations=1,
    )
    assert len(gaps) == 1
    assert len(explorations) == 1
    assert recommendations == []
    assert gaps[0].gap_type == "missing_workspace_access"
    persisted = repr(
        {
            "gap_evidence": gaps[0].evidence,
            "source_evidence": gaps[0].source_evidence,
            "exploration_failure": explorations[0].failure_reason,
            "tool_events": explorations[0].tool_events,
        }
    )
    assert connector_id in persisted
    assert "WORKSPACE_CONNECTOR_GENERATION_MISMATCH" in persisted
    assert "<redacted-host-path>" in persisted
    for leaked in (
        "old.csv",
        "secret.csv",
        "source.csv",
        "token.json",
        "key.txt",
        "plain.txt",
        "chainless-secret.sock",
        "staged-secret.txt",
        "E:\\private",
        "/home/alice",
        "/var/folders",
        "/mnt/c",
        "/Users/alice",
        "/tmp/chainless-secret",
        "/private/tmp",
    ):
        assert leaked not in persisted
