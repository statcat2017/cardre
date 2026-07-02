"""Canonical evidence contract — required steps, aliases, and resolution policy.

This is the single source of truth for what evidence a report, readiness check,
or comparison requires.  All consumers import from here instead of defining
their own required-step lists and alias maps.
"""

from __future__ import annotations

from cardre.domain.run import RunStep
from cardre.store import ProjectStore
from cardre.store.run_repo import RunRepository

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

def find_evidence_for_canonical_step(
    store: ProjectStore,
    plan_version_id: str,
    canonical_step_id: str,
    branch_id: str | None = None,
) -> RunStep | None:
    """Find the latest successful run step for a canonical step."""
    repo = RunRepository(store)
    rs = repo.get_latest_successful_step(plan_version_id, canonical_step_id, branch_id=branch_id)
    if rs is None and branch_id is not None:
        rs = repo.get_latest_successful_step(plan_version_id, canonical_step_id, branch_id=None)
    return rs
