"""W7 acquisition outbox and observability contracts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.deps import _async_session_factory
from app.api.v1 import system
from app.core.acquisition import outbox
from app.core.observability import (
    ACQUISITION_METRIC_NAMES,
    get_runtime_metric_snapshot,
    increment_acquisition_metric,
    reset_runtime_metrics,
)
from app.models.acquisition import AcquisitionAnalysisJob
from app.models.acquisition import RuntimePlanningIssue
from app.services.auth_service import decode_token

pytestmark = pytest.mark.asyncio


def _identity(headers: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    payload = decode_token(headers["Authorization"].split(" ", 1)[1])
    return uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["user_id"])


async def test_acquisition_analysis_outbox_enqueue_is_idempotent(
    tenant_a_headers: dict[str, str],
) -> None:
    reset_runtime_metrics()
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        first = await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-outbox-idempotent",
            source_kind="conversation_stream",
            payload={"status": "completed"},
        )
        second = await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-outbox-idempotent",
            source_kind="conversation_stream",
            payload={"status": "completed", "changed": True},
        )
        await db.commit()

        rows = list(
            (
                await db.execute(
                    select(AcquisitionAnalysisJob).where(
                        AcquisitionAnalysisJob.tenant_id == tenant_id,
                        AcquisitionAnalysisJob.user_id == user_id,
                        AcquisitionAnalysisJob.source_run_id == "w7-outbox-idempotent",
                    )
                )
            ).scalars()
        )

    assert first.id == second.id
    assert len(rows) == 1
    assert get_runtime_metric_snapshot()["acquisition_analysis_jobs_enqueued"] == 1
    assert get_runtime_metric_snapshot()["acquisition_analysis_duplicate_enqueues"] == 1


async def test_acquisition_outbox_processor_completes_jobs_and_creates_runtime_planning_issue(
    tenant_a_headers: dict[str, str],
) -> None:
    reset_runtime_metrics()
    tenant_id, user_id = _identity(tenant_a_headers)
    source_run_id = f"w7-process-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation_stream",
            payload={
                "status": "completed",
                "runtime_planning_issue": {
                    "available_capability_ref": {"target_type": "worker", "worker_id": str(uuid.uuid4())},
                    "missed_signal": "The planner ignored a high-confidence Worker match.",
                    "planner_decision_summary": "Agent used a generic answer.",
                    "expected_decision_summary": "Agent should have used the existing Worker.",
                },
            },
        )
        processed = await outbox.process_pending_acquisition_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            batch_limit=5,
        )
        await db.commit()

    assert len(processed) == 1
    assert processed[0].status == "succeeded"
    assert processed[0].result_metadata["analysis_result"] == "runtime_planning_issue_created"
    assert get_runtime_metric_snapshot()["acquisition_analysis_succeeded"] == 1

    async with _async_session_factory() as db:
        issue = (
            await db.execute(
                select(RuntimePlanningIssue).where(
                    RuntimePlanningIssue.tenant_id == tenant_id,
                    RuntimePlanningIssue.user_id == user_id,
                    RuntimePlanningIssue.source_run_id == source_run_id,
                )
            )
        ).scalar_one()

    assert issue.issue_type == "planner_missed_existing_tool"
    assert issue.available_capability_ref["target_type"] == "worker"


async def test_acquisition_outbox_completion_is_fenced_by_current_lease(
    tenant_a_headers: dict[str, str],
) -> None:
    tenant_id, user_id = _identity(tenant_a_headers)
    source_run_id = f"w7-lease-{uuid.uuid4().hex}"

    async with _async_session_factory() as db:
        await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation_stream",
            payload={"status": "completed"},
        )
        claimed = await outbox.claim_pending_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db.commit()

    assert claimed is not None
    async with _async_session_factory() as db:
        fresh = (
            await db.execute(
                select(AcquisitionAnalysisJob).where(AcquisitionAnalysisJob.id == claimed.id).with_for_update()
            )
        ).scalar_one()
        fresh.attempts += 1
        fresh.claimed_at = datetime.now(timezone.utc)
        await db.commit()

    async with _async_session_factory() as db:
        with pytest.raises(outbox.AcquisitionAnalysisLeaseLost):
            await outbox.complete_analysis_job(
                db,
                claimed,
                result_metadata={"processed": True},
            )


async def test_acquisition_outbox_claim_uses_skip_locked_lease_and_batch_limit(
    tenant_a_headers: dict[str, str],
) -> None:
    reset_runtime_metrics()
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        for idx in range(3):
            await outbox.enqueue_run_analysis(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                source_run_id=f"w7-batch-{idx}",
                source_kind="conversation_stream",
                payload={"idx": idx},
            )
        await db.commit()

    async with _async_session_factory() as db:
        claimed = await outbox.claim_pending_analysis_jobs(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            batch_limit=2,
        )
        await db.commit()

    assert len(claimed) == 2
    assert all(job.status == "running" and job.attempts == 1 for job in claimed)
    assert get_runtime_metric_snapshot()["acquisition_analysis_jobs_claimed"] == 2


async def test_acquisition_outbox_retries_timeout_and_records_metrics(
    tenant_a_headers: dict[str, str],
) -> None:
    reset_runtime_metrics()
    tenant_id, user_id = _identity(tenant_a_headers)

    async with _async_session_factory() as db:
        job = await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id="w7-timeout",
            source_kind="conversation_stream",
            payload={"status": "pending"},
        )
        job.status = "running"
        job.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        await db.commit()

    async with _async_session_factory() as db:
        reclaimed = await outbox.claim_pending_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            lease_seconds=1,
        )
        assert reclaimed is not None
        await outbox.fail_analysis_job(
            db,
            reclaimed,
            error_code="ANALYZER_TIMEOUT",
            error_message="timeout while analyzing run",
            timed_out=True,
        )
        await db.commit()

    metrics = get_runtime_metric_snapshot()
    assert metrics["acquisition_analysis_stale_reclaims"] == 1
    assert metrics["acquisition_analysis_timeouts"] == 1


async def test_failed_acquisition_outbox_job_retries_idempotently(
    tenant_a_headers: dict[str, str],
) -> None:
    reset_runtime_metrics()
    tenant_id, user_id = _identity(tenant_a_headers)
    source_run_id = f"w7-retry-{uuid.uuid4().hex}"
    calls = 0

    async def flaky_handler(db, job):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient analyzer failure")
        return {"processed": True, "analysis_result": "retry_succeeded"}

    async with _async_session_factory() as db:
        await outbox.enqueue_run_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_run_id=source_run_id,
            source_kind="conversation_stream",
            payload={"status": "completed"},
        )
        first = await outbox.process_pending_acquisition_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            batch_limit=1,
            handler=flaky_handler,
        )
        await db.commit()

    assert first[0].status == "failed"

    async with _async_session_factory() as db:
        second = await outbox.process_pending_acquisition_analysis(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            batch_limit=1,
            retry_seconds=0,
            handler=flaky_handler,
        )
        await db.commit()

    assert second[0].status == "succeeded"
    assert second[0].result_metadata["analysis_result"] == "retry_succeeded"
    assert second[0].attempts == 2
    assert get_runtime_metric_snapshot()["acquisition_analysis_retries"] == 1


async def test_acquisition_analysis_is_registered_on_arq_worker() -> None:
    from app.core.acquisition.tasks import process_acquisition_analysis
    from app.core.capabilities.tasks import process_capability_analysis
    from app.core.proactive.scheduler import WorkerSettings

    assert process_acquisition_analysis in WorkerSettings.functions
    assert process_capability_analysis in WorkerSettings.functions


async def test_acquisition_metric_names_match_spec_contract() -> None:
    assert {
        "acquisition_analysis_jobs_enqueued",
        "acquisition_analysis_duplicate_enqueues",
        "acquisition_analysis_jobs_claimed",
        "acquisition_analysis_stale_reclaims",
        "acquisition_analysis_retries",
        "acquisition_analysis_succeeded",
        "acquisition_analysis_failures",
        "acquisition_analysis_timeouts",
        "acquisition_policy_blocks",
        "acquisition_rollback_failures",
        "acquisition_session_cleanups",
        "acquisition_credential_revocations",
        "acquisition_disabled_events",
    } == set(ACQUISITION_METRIC_NAMES)


async def test_policy_block_rollback_failure_session_cleanup_and_credential_revocation_emit_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime_metrics()
    for name in (
        "acquisition_policy_blocks",
        "acquisition_rollback_failures",
        "acquisition_session_cleanups",
        "acquisition_credential_revocations",
    ):
        increment_acquisition_metric(name)

    async def fake_health(sandbox_manager=None):
        return {
            "checks": {
                "db": {"status": "connected"},
                "redis": {"status": "connected"},
                "worker": {"status": "ok"},
                "sandbox": {"status": "ok", "pool_size": 1, "total_containers": 1},
            }
        }

    monkeypatch.setattr(system, "collect_operational_health", fake_health)
    async def fake_proactive_summary():
        return {"total": 0, "blocked": 0, "delivery_failed": 0}

    monkeypatch.setattr(system, "summarize_run_records", fake_proactive_summary)
    monkeypatch.setattr(system, "summarize_eval_outcomes", lambda: {"pass": 0, "fail": 0, "error": 0})

    response = await system.system_metrics(_current_user={"role": "admin"}, sandbox_manager=None)
    body = response.body.decode("utf-8")

    assert 'chainless_acquisition_runtime_events_total{counter="acquisition_policy_blocks"} 1' in body
    assert 'chainless_acquisition_runtime_events_total{counter="acquisition_rollback_failures"} 1' in body
    assert 'chainless_acquisition_runtime_events_total{counter="acquisition_session_cleanups"} 1' in body
    assert 'chainless_acquisition_runtime_events_total{counter="acquisition_credential_revocations"} 1' in body


async def test_metrics_labels_do_not_include_secret_material_or_raw_paths() -> None:
    for unsafe in (
        "acquisition_secret_leak",
        "acquisition_token_label",
        "acquisition_path_c:\\users\\alice",
        "acquisition_path_/home/alice",
    ):
        with pytest.raises(ValueError):
            increment_acquisition_metric(unsafe)
