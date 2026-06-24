"""W8 eval suite and CI gate contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.core.agent.code_executor import CODE_AS_ACTION_TOOL
from app.core.tools.builtin import ALL_TOOLS
from app.core.tools.schema import validate_openai_tool_schemas


def _load_eval_module():
    path = Path("scripts/run-eval.py")
    spec = importlib.util.spec_from_file_location("run_eval_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_builtin_tool_definitions_match_openai_function_schema() -> None:
    validate_openai_tool_schemas(ALL_TOOLS + [CODE_AS_ACTION_TOOL])


def test_spec_complete_suite_contains_deterministic_w8_contract_probes() -> None:
    tasks = json.loads(Path("tests/eval/tasks/spec_complete.json").read_text(encoding="utf-8"))
    ids = [task["id"] for task in tasks]
    runners = {task.get("runner") for task in tasks}

    assert len(ids) == len(set(ids))
    assert "parallel_subagent_runtime_probe" in runners
    assert "tool_schema_probe" in runners
    assert "mcp_default_risk_probe" in runners
    assert "mcp_isolated_runtime_probe" in runners


@pytest.mark.asyncio
async def test_w8_deterministic_eval_runners_return_hard_runtime_evidence() -> None:
    module = _load_eval_module()

    schema_result = await module.run_single_task(
        object(),
        object(),
        {
            "id": "schema",
            "prompt": "validate schemas",
            "runner": "tool_schema_probe",
            "pass_criteria": "runtime_evidence",
        },
        tenant_id="tenant-a",
    )
    mcp_result = await module.run_single_task(
        object(),
        object(),
        {
            "id": "mcp",
            "prompt": "validate mcp risk",
            "runner": "mcp_default_risk_probe",
            "pass_criteria": "runtime_evidence",
        },
        tenant_id="tenant-a",
    )
    mcp_runtime_result = await module.run_single_task(
        object(),
        object(),
        {
            "id": "mcp-runtime",
            "prompt": "validate isolated mcp runtime",
            "runner": "mcp_isolated_runtime_probe",
            "pass_criteria": "runtime_evidence",
        },
        tenant_id="tenant-a",
    )

    assert schema_result["passed"] is True
    assert schema_result["tool_log"][0]["evidence"]["tool_count"] >= 8
    assert mcp_result["passed"] is True
    assert mcp_result["tool_log"][0]["evidence"]["risk"] == "risky"
    assert mcp_runtime_result["passed"] is True
    assert "mcp__eval__echo" in mcp_runtime_result["tool_calls"]
    assert mcp_runtime_result["tool_log"][0]["evidence"]["runtime_kind"] == "isolated_stdio"
    assert mcp_runtime_result["tool_log"][0]["evidence"]["content"] == ["eval-runtime-ok"]


def test_eval_workflow_runs_required_w8_tests_and_threshold_gate() -> None:
    workflow_path = Path("/repo/.github/workflows/eval.yml")
    if not workflow_path.exists():
        workflow_path = Path("../.github/workflows/eval.yml")
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "tests/test_proactive_authorization.py" in workflow
    assert "tests/test_tool_cancellation.py" in workflow
    assert "backend-test-live" in workflow
    assert "--suite basic --json --min-pass-rate 1.0" in workflow
    assert "--suite spec_complete --json --min-pass-rate 1.0" in workflow

    script = Path("scripts/run-eval.py").read_text(encoding="utf-8")
    assert "pass_rate < args.min_pass_rate" in script
    assert "sys.exit(1)" in script
