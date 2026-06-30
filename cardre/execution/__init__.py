"""Execution helpers extracted from PlanExecutor.

Pure functions for failure classification, fingerprint construction,
and input validation. PlanExecutor remains the single orchestration
seam; these modules hold the reusable pieces.
"""
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.validation import (
    LEAKAGE_SENSITIVE_CATEGORIES,
    LeakageProtectionError,
    RoleAccessError,
    filter_inputs_by_role,
    validate_input_artifact_files,
    validate_leakage_rules,
    validate_node_input_roles,
    validate_role_access,
)

__all__ = [
    "LEAKAGE_SENSITIVE_CATEGORIES",
    "LeakageProtectionError",
    "RoleAccessError",
    "classify_step_failure",
    "filter_inputs_by_role",
    "validate_input_artifact_files",
    "validate_leakage_rules",
    "validate_node_input_roles",
    "validate_role_access",
]
