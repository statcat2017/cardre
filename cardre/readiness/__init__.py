"""Readiness validation — the single producer for report-readiness checks.

All readiness consumers (sidecar routes, workflow-guidance service) call
into this package instead of re-deriving readiness independently.
"""

from cardre.readiness.check import check_report_readiness, ReportReadinessResult
from cardre.readiness.dto import ReadinessBlocker, ReadinessWarning
from cardre.readiness.limitation_codes import LimitationCode

__all__ = [
    "check_report_readiness",
    "ReportReadinessResult",
    "ReadinessBlocker",
    "ReadinessWarning",
    "LimitationCode",
]
