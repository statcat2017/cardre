"""Pure reporting contracts shared by use cases and adapters."""

from __future__ import annotations

from cardre.domain.evidence.kinds import EvidenceKind

REQUIRED_STEPS_COLLECTOR = [
    "final-woe-iv", "model-fit", "score-scaling", "validation-metrics", "cutoff-analysis",
    "manual-binning", "variable-clustering", "coefficient-sign-check",
    "separation-diagnostics", "vif-diagnostics", "calibration-diagnostics", "apply-exclusions",
    "sample-definition", "explicit-missing-outlier-treatment", "initial-woe-iv",
    "apply-woe", "freeze-scorecard-bundle", "apply-model", "scorecard-table-export",
    "scoring-export-python", "scoring-export-sql",
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


__all__ = [
    "REQUIRED_STEPS_COLLECTOR",
    "EVIDENCE_KIND_BY_STEP",
]
