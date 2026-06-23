"""Deprecation shim — re-exports from cardre.readiness.check.

This file exists for backwards compatibility during the cardre/reporting/
→ cardre/readiness/ migration. New code should import from cardre.readiness
directly. This shim will be removed after all import sites are migrated.
"""

from cardre.readiness.check import check_report_readiness  # noqa: F401
from cardre.readiness.dto import ReportReadinessResult  # noqa: F401
