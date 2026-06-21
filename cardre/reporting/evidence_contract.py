"""Canonical evidence contract — required steps, aliases, and resolution policy.

This is the single source of truth for what evidence a report, readiness check,
or comparison requires.  All consumers import from here instead of defining
their own required-step lists and alias maps.
"""

from __future__ import annotations

from cardre.audit import RunStepRecord
from cardre.evidence_locator import latest_successful_run_step
from cardre.store import ProjectStore

# ---------------------------------------------------------------------------
# Required canonical steps per report mode
# ---------------------------------------------------------------------------

REQUIRED_STEPS_BRANCH: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
]

REQUIRED_STEPS_CHAMPION: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
]

REQUIRED_STEPS_COLLECTOR: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "manual-binning",
    "variable-clustering",
]

REQUIRED_STEPS_COMPARISON: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest-stub",
]

# ---------------------------------------------------------------------------
# Legacy alias map
# ---------------------------------------------------------------------------

LEGACY_CANONICAL_ALIASES: dict[str, str] = {
    "logistic-regression": "model-fit",
}

# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def resolve_canonical_step_id(canonical_step_id: str) -> str:
    """Resolve a legacy canonical step ID to its current canonical form."""
    return LEGACY_CANONICAL_ALIASES.get(canonical_step_id, canonical_step_id)


def canonical_alias_candidates(canonical_step_id: str) -> list[str]:
    """Return current and legacy canonical IDs that may hold equivalent evidence."""
    candidates = [canonical_step_id]
    forward = LEGACY_CANONICAL_ALIASES.get(canonical_step_id)
    if forward and forward not in candidates:
        candidates.append(forward)
    for legacy, current in LEGACY_CANONICAL_ALIASES.items():
        if current == canonical_step_id and legacy not in candidates:
            candidates.append(legacy)
    return candidates


def find_evidence_for_canonical_step(
    store: ProjectStore,
    plan_version_id: str,
    canonical_step_id: str,
    branch_id: str | None = None,
) -> RunStepRecord | None:
    """Find the latest successful run step for a canonical step.

    Resolves legacy aliases automatically.  Uses the evidence locator's
    branch-scoped → full-plan → across-plan fallback chain.
    """
    for actual in canonical_alias_candidates(canonical_step_id):
        rs = latest_successful_run_step(store, plan_version_id, actual, branch_id=branch_id)
        if rs is not None:
            return rs
    return None
