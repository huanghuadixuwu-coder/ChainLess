"""V3 capability acquisition lifecycle package."""

from app.core.acquisition.lifecycle import (
    ExplorationBoundsDecision,
    GapClassification,
    activate_proposal,
    classify_failure_for_gap,
    complete_exploration,
    create_proposal,
    create_recommendation,
    evaluate_exploration_bounds,
    record_failure,
    record_gap,
    reject_activation,
    start_exploration,
)
from app.core.acquisition.repository import normalize_gap_dedupe_key

__all__ = [
    "ExplorationBoundsDecision",
    "GapClassification",
    "activate_proposal",
    "classify_failure_for_gap",
    "complete_exploration",
    "create_proposal",
    "create_recommendation",
    "evaluate_exploration_bounds",
    "normalize_gap_dedupe_key",
    "record_failure",
    "record_gap",
    "reject_activation",
    "start_exploration",
]
