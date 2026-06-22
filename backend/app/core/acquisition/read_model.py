"""Read-model projections for the generated acquisition journal."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.acquisition import (
    AcquisitionProposal,
    ActivationTarget,
    CapabilityGap,
    DevelopmentPatchProposal,
    RuntimePlanningIssue,
)


OPEN_GAP_EXCLUDED_STATUSES = {"dismissed", "snoozed", "superseded"}
PROPOSAL_APPROVAL_STATUSES = {"drafted", "verified", "activation_requested"}
REJECTED_OR_DISMISSED_PROPOSAL_STATUSES = {
    "activation_rejected",
    "verification_failed",
    "activation_failed",
    "dismissed",
    "superseded",
    "rolled_back",
}


@dataclass(frozen=True)
class JournalSection:
    title: str
    api_path: str
    total: int
    items: list[Any]

    @property
    def shown(self) -> int:
        return len(self.items)

    @property
    def more(self) -> int:
        return max(self.total - self.shown, 0)


@dataclass(frozen=True)
class AcquisitionJournalReadModel:
    open_gaps: JournalSection
    proposals_needing_approval: JournalSection
    activated_capabilities: JournalSection
    rejected_or_dismissed: JournalSection
    runtime_planning_issues: JournalSection
    development_patch_proposals: JournalSection

    @property
    def sections(self) -> list[JournalSection]:
        return [
            self.open_gaps,
            self.proposals_needing_approval,
            self.activated_capabilities,
            self.rejected_or_dismissed,
            self.runtime_planning_issues,
            self.development_patch_proposals,
        ]


def _order(model: type[Any]) -> tuple[Any, Any]:
    return (model.created_at.asc(), model.id.asc())


async def _count(db: AsyncSession, stmt: Any) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


async def get_acquisition_journal_read_model(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    section_limit: int,
) -> AcquisitionJournalReadModel:
    """Load bounded, tenant/user-scoped source records for ACQUISITION.md."""

    open_gap_filter = (
        CapabilityGap.tenant_id == tenant_id,
        CapabilityGap.user_id == user_id,
        CapabilityGap.status.notin_(OPEN_GAP_EXCLUDED_STATUSES),
    )
    approval_filter = (
        AcquisitionProposal.tenant_id == tenant_id,
        AcquisitionProposal.user_id == user_id,
        AcquisitionProposal.proposal_kind == "runtime_activation",
        AcquisitionProposal.status.in_(PROPOSAL_APPROVAL_STATUSES),
    )
    activated_filter = (
        ActivationTarget.tenant_id == tenant_id,
        ActivationTarget.user_id == user_id,
        ActivationTarget.activation_status == "active",
    )
    rejected_filter = (
        AcquisitionProposal.tenant_id == tenant_id,
        AcquisitionProposal.user_id == user_id,
        AcquisitionProposal.proposal_kind == "runtime_activation",
        AcquisitionProposal.status.in_(REJECTED_OR_DISMISSED_PROPOSAL_STATUSES),
    )
    planning_filter = (
        RuntimePlanningIssue.tenant_id == tenant_id,
        RuntimePlanningIssue.user_id == user_id,
    )
    patch_filter = (
        AcquisitionProposal.tenant_id == tenant_id,
        AcquisitionProposal.user_id == user_id,
        AcquisitionProposal.proposal_kind == "development_patch_proposal",
    )

    open_gap_total = await _count(db, select(func.count()).select_from(CapabilityGap).where(*open_gap_filter))
    approval_total = await _count(db, select(func.count()).select_from(AcquisitionProposal).where(*approval_filter))
    activated_total = await _count(db, select(func.count()).select_from(ActivationTarget).where(*activated_filter))
    rejected_total = await _count(db, select(func.count()).select_from(AcquisitionProposal).where(*rejected_filter))
    planning_total = await _count(db, select(func.count()).select_from(RuntimePlanningIssue).where(*planning_filter))
    patch_total = await _count(db, select(func.count()).select_from(AcquisitionProposal).where(*patch_filter))

    open_gaps = list(
        (
            await db.execute(
                select(CapabilityGap)
                .where(*open_gap_filter)
                .order_by(*_order(CapabilityGap))
                .limit(section_limit)
            )
        ).scalars()
    )
    approvals = list(
        (
            await db.execute(
                select(AcquisitionProposal)
                .where(*approval_filter)
                .order_by(*_order(AcquisitionProposal))
                .limit(section_limit)
            )
        ).scalars()
    )
    activated = list(
        (
            await db.execute(
                select(ActivationTarget)
                .where(*activated_filter)
                .order_by(*_order(ActivationTarget))
                .limit(section_limit)
            )
        ).scalars()
    )
    rejected = list(
        (
            await db.execute(
                select(AcquisitionProposal)
                .where(*rejected_filter)
                .order_by(*_order(AcquisitionProposal))
                .limit(section_limit)
            )
        ).scalars()
    )
    planning = list(
        (
            await db.execute(
                select(RuntimePlanningIssue)
                .where(*planning_filter)
                .order_by(*_order(RuntimePlanningIssue))
                .limit(section_limit)
            )
        ).scalars()
    )
    patches = list(
        (
            await db.execute(
                select(AcquisitionProposal)
                .where(*patch_filter)
                .order_by(*_order(AcquisitionProposal))
                .limit(section_limit)
            )
        ).scalars()
    )

    return AcquisitionJournalReadModel(
        open_gaps=JournalSection("Open Gaps", "/api/v1/acquisition/gaps", open_gap_total, open_gaps),
        proposals_needing_approval=JournalSection(
            "Proposals Needing Approval",
            "/api/v1/acquisition/proposals",
            approval_total,
            approvals,
        ),
        activated_capabilities=JournalSection(
            "Activated Capabilities",
            "/api/v1/acquisition/activation-targets",
            activated_total,
            activated,
        ),
        rejected_or_dismissed=JournalSection(
            "Rejected or Dismissed",
            "/api/v1/acquisition/proposals",
            rejected_total,
            rejected,
        ),
        runtime_planning_issues=JournalSection(
            "Runtime Planning Issues",
            "/api/v1/acquisition/runtime-planning-issues",
            planning_total,
            planning,
        ),
        development_patch_proposals=JournalSection(
            "Development Patch Proposals",
            "/api/v1/acquisition/development-patch-proposals",
            patch_total,
            patches,
        ),
    )


async def get_development_patch_artifacts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal_ids: set[uuid.UUID],
) -> dict[uuid.UUID, DevelopmentPatchProposal]:
    if not proposal_ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(DevelopmentPatchProposal).where(
                    DevelopmentPatchProposal.tenant_id == tenant_id,
                    DevelopmentPatchProposal.user_id == user_id,
                    DevelopmentPatchProposal.proposal_id.in_(proposal_ids),
                )
            )
        ).scalars()
    )
    return {row.proposal_id: row for row in rows}
