"""Role enforcement and leakage protection for step execution.

Exception classes and constants extracted from PlanExecutor.
"""
from __future__ import annotations

from cardre.errors import CardreError

LEAKAGE_SENSITIVE_CATEGORIES = {"fit", "selection", "refinement"}


class RoleAccessError(CardreError):
    code = "ROLE_ACCESS_ERROR"
    status_code = 400


class LeakageProtectionError(CardreError):
    code = "LEAKAGE_PROTECTION_ERROR"
    status_code = 400
