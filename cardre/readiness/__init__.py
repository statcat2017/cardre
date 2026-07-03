"""Readiness validation — the single producer for report-readiness checks.

All readiness consumers (sidecar routes, workflow-guidance service) call
into this package instead of re-deriving readiness independently.
"""

from cardre.readiness.check import ReportReadinessResult, check_report_readiness
from cardre.readiness.dto import ReadinessBlocker, ReadinessWarning
from cardre.readiness.limitation_codes import LimitationCode
from cardre.readiness.manual_binning import compute_manual_binning_blockers

__all__ = [
    "LimitationCode",
    "ReadinessBlocker",
    "ReadinessWarning",
    "ReportReadinessResult",
    "check_report_readiness",
    "compute_manual_binning_blockers",
]
