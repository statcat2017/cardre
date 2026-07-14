"""Canonical evidence contract — required steps, aliases, and resolution policy.

This is the single source of truth for what evidence a report, readiness check,
or comparison requires.  All consumers import from here instead of defining
their own required-step lists and alias maps.

Evidence *lookup* (the branch→full→plan fallback) lives in
``cardre.evidence_locator.EvidenceLocator`` (ADR-0005 §3, ADR-0013).  This
module owns only the *what* (required-step lists), not the *how*.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Required canonical steps per report mode
# ---------------------------------------------------------------------------

REQUIRED_STEPS_BRANCH: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
]

REQUIRED_STEPS_CHAMPION: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "freeze-scorecard-bundle",
    "apply-model",
    "validation-metrics",
    "cutoff-analysis",
    "scorecard-table-export",
    "scoring-export-python",
    "scoring-export-sql",
]

REQUIRED_STEPS_COLLECTOR: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "manual-binning",
    "variable-clustering",
    "coefficient-sign-check",
    "separation-diagnostics",
    "vif-diagnostics",
    "calibration-diagnostics",
    "apply-exclusions",
    "sample-definition",
    "explicit-missing-outlier-treatment",
    "initial-woe-iv",
    "model-limitations",
    "freeze-scorecard-bundle",
    "apply-woe",
    "apply-model",
    "scorecard-table-export",
    "scoring-export-python",
    "scoring-export-sql",
]

REQUIRED_STEPS_COMPARISON: list[str] = [
    "final-woe-iv",
    "model-fit",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest",
]
