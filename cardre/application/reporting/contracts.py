"""Pure reporting contracts shared by use cases and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cardre.domain.evidence.kinds import EvidenceKind

ReportMode = Literal["branch", "champion"]

REQUIRED_STEPS_BRANCH = [
    "final-woe-iv", "model-fit", "score-scaling", "validation-metrics", "cutoff-analysis",
]
REQUIRED_STEPS_CHAMPION = [
    "final-woe-iv", "model-fit", "score-scaling", "freeze-scorecard-bundle", "apply-model",
    "validation-metrics", "cutoff-analysis", "scorecard-table-export", "scoring-export-python",
    "scoring-export-sql",
]
REQUIRED_STEPS_COLLECTOR = [
    *REQUIRED_STEPS_CHAMPION, "manual-binning", "variable-clustering", "coefficient-sign-check",
    "separation-diagnostics", "vif-diagnostics", "calibration-diagnostics", "apply-exclusions",
    "sample-definition", "explicit-missing-outlier-treatment", "initial-woe-iv", "model-limitations",
    "apply-woe",
]
REQUIRED_STEPS_COMPARISON = [
    "final-woe-iv", "model-fit", "score-scaling", "validation-metrics", "cutoff-analysis",
    "technical-manifest",
]
EVIDENCE_KIND_BY_STEP = {
    "final-woe-iv": EvidenceKind.WOE_IV_EVIDENCE,
    "model-fit": EvidenceKind.MODEL_ARTIFACT,
    "score-scaling": EvidenceKind.SCORE_SCALING,
    "validation-metrics": EvidenceKind.VALIDATION_METRICS,
    "cutoff-analysis": EvidenceKind.CUTOFF_ANALYSIS,
    "freeze-scorecard-bundle": EvidenceKind.FROZEN_SCORECARD_BUNDLE,
    "apply-model": EvidenceKind.APPLY_MODEL_EVIDENCE,
    "scorecard-table-export": EvidenceKind.SCORE_TABLE,
    "scoring-export-python": EvidenceKind.SCORING_EXPORT_PYTHON,
    "scoring-export-sql": EvidenceKind.SCORING_EXPORT_SQL,
}


@dataclass(frozen=True)
class ResolvedStepRef:
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str = "exact"


def resolve_required_steps(
    branch_id: str,
    canonical_step_ids: list[str],
    branch_step_map: list[dict[str, object]],
) -> dict[str, ResolvedStepRef]:
    resolved: dict[str, ResolvedStepRef] = {}
    for row in branch_step_map:
        canonical_step_id = str(row.get("canonical_step_id", ""))
        if canonical_step_id not in canonical_step_ids or canonical_step_id in resolved:
            continue
        source_branch_id = row.get("source_branch_id")
        inherited = bool(row.get("is_shared_upstream")) and bool(source_branch_id)
        resolved[canonical_step_id] = ResolvedStepRef(
            requested_branch_id=branch_id,
            resolved_branch_id=str(source_branch_id) if inherited else branch_id,
            canonical_step_id=canonical_step_id,
            step_id=str(row.get("source_step_id") if inherited and row.get("source_step_id") else row.get("step_id", "")),
            resolution="ancestor" if inherited else "exact",
        )
    return resolved


__all__ = [
    "REQUIRED_STEPS_BRANCH", "REQUIRED_STEPS_CHAMPION", "REQUIRED_STEPS_COLLECTOR",
    "EVIDENCE_KIND_BY_STEP", "REQUIRED_STEPS_COMPARISON", "ReportMode", "ResolvedStepRef",
    "resolve_required_steps",
]
