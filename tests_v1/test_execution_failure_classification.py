"""Unit tests for cardre/execution/failure_classification.py — no PlanExecutor needed."""
from __future__ import annotations

import pytest

from cardre.errors import (
    CardreError,
    GraphValidationError,
    MissingInputArtifactError,
    ParameterValidationError,
    ArtifactReadError,
    ArtifactWriteError,
    NodeExecutionError,
    ContractViolationError,
)
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.validation import RoleAccessError, LeakageProtectionError


ERROR_SCENARIOS = [
    (GraphValidationError("x"), "GraphValidationError", "GRAPH_VALIDATION_ERROR"),
    (MissingInputArtifactError("x"), "MissingInputArtifactError", "MISSING_INPUT_ARTIFACT"),
    (ParameterValidationError("x"), "ParameterValidationError", "PARAMETER_VALIDATION_ERROR"),
    (ArtifactReadError("x"), "ArtifactReadError", "ARTIFACT_READ_ERROR"),
    (ArtifactWriteError("x"), "ArtifactWriteError", "ARTIFACT_WRITE_ERROR"),
    (NodeExecutionError("x"), "NodeExecutionError", "NODE_EXECUTION_ERROR"),
    (ContractViolationError("x"), "ContractViolationError", "CONTRACT_VIOLATION_ERROR"),
    (RoleAccessError("x"), "RoleAccessError", "ROLE_ACCESS_ERROR"),
    (LeakageProtectionError("x"), "LeakageProtectionError", "LEAKAGE_PROTECTION_ERROR"),
    (CardreError("x"), "CardreError", "CARDRE_ERROR"),
    (RuntimeError("x"), "InternalExecutionError", "STEP_FAILED"),
    (ValueError("x"), "InternalExecutionError", "STEP_FAILED"),
    (None, "InternalExecutionError", "STEP_FAILED"),
]


class TestClassifyStepFailure:
    @pytest.mark.parametrize("exc,exp_cat,exp_code", ERROR_SCENARIOS,
                             ids=[s[1] for s in ERROR_SCENARIOS])
    def test_category_and_code(self, exc, exp_cat, exp_code):
        entry = classify_step_failure(exc, "traceback content")
        assert entry["category"] == exp_cat
        assert entry["code"] == exp_code
        assert entry["traceback"] == "traceback content"
        assert "message" in entry

    def test_traceback_preserved(self):
        entry = classify_step_failure(RuntimeError("x"), "full traceback")
        assert entry["traceback"] == "full traceback"

    def test_exc_type_name_in_message(self):
        entry = classify_step_failure(ValueError("bad value"), "tb")
        assert "ValueError" in entry["message"]
        assert "bad value" in entry["message"]
