# Phase 2: Extract Failure Classification

**Goal:** Extract the inline `_CATEGORY_MAP`/`_CODE_MAP` mapping and
`error_entry` construction from `PlanExecutor._execute_step` into a pure
function `classify_step_failure()` in `cardre/execution/failure_classification.py`.

## Files

- **Create:** `cardre/execution/__init__.py`, `cardre/execution/failure_classification.py`
- **Create:** `tests/test_execution_failure_classification.py`
- **Edit:** `cardre/executor.py`

## Tests to Write First (RED)

### `tests/test_execution_failure_classification.py`

Parametrized matrix capturing every category in `_CATEGORY_MAP` plus the
fallback `InternalExecutionError`:

```python
import pytest
from cardre.errors import (
    CardreError, GraphValidationError, MissingInputArtifactError,
    ParameterValidationError, ArtifactReadError, ArtifactWriteError,
    NodeExecutionError, ContractViolationError,
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
```

Run:
```bash
python3 -m pytest tests/test_execution_failure_classification.py -q --tb=short
```
Expected: **fails** (module does not exist yet).

## Implementation

### 1. Create `cardre/execution/__init__.py`

```python
"""Execution helpers extracted from PlanExecutor."""
from cardre.execution.failure_classification import classify_step_failure

__all__ = ["classify_step_failure"]
```

### 2. Create `cardre/execution/failure_classification.py`

```python
"""Classify a step-execution exception into the structured error_entry
dict recorded in RunStepRecord.errors.

Pure mapping — no ProjectStore, no run/step IDs.
"""
from __future__ import annotations

from typing import Any

from cardre.errors import (
    ArtifactReadError,
    ArtifactWriteError,
    CardreError,
    ContractViolationError,
    GraphValidationError,
    MissingInputArtifactError,
    NodeExecutionError,
    ParameterValidationError,
)
from cardre.execution.validation import LeakageProtectionError, RoleAccessError

# Order matters: more specific subclasses first.
_CATEGORY_MAP: tuple = (
    (GraphValidationError, "GraphValidationError"),
    (MissingInputArtifactError, "MissingInputArtifactError"),
    (ParameterValidationError, "ParameterValidationError"),
    (ArtifactReadError, "ArtifactReadError"),
    (ArtifactWriteError, "ArtifactWriteError"),
    (NodeExecutionError, "NodeExecutionError"),
    (ContractViolationError, "ContractViolationError"),
    (RoleAccessError, "RoleAccessError"),
    (LeakageProtectionError, "LeakageProtectionError"),
    (CardreError, "CardreError"),
)

_CODE_MAP: dict[str, str] = {
    "GraphValidationError": "GRAPH_VALIDATION_ERROR",
    "MissingInputArtifactError": "MISSING_INPUT_ARTIFACT",
    "ParameterValidationError": "PARAMETER_VALIDATION_ERROR",
    "ArtifactReadError": "ARTIFACT_READ_ERROR",
    "ArtifactWriteError": "ARTIFACT_WRITE_ERROR",
    "NodeExecutionError": "NODE_EXECUTION_ERROR",
    "ContractViolationError": "CONTRACT_VIOLATION_ERROR",
    "RoleAccessError": "ROLE_ACCESS_ERROR",
    "LeakageProtectionError": "LEAKAGE_PROTECTION_ERROR",
    "CardreError": "CARDRE_ERROR",
}

_DEFAULT_CATEGORY = "InternalExecutionError"
_DEFAULT_CODE = "STEP_FAILED"


def classify_step_failure(exc_value: BaseException | None, traceback_str: str) -> dict[str, Any]:
    category = _DEFAULT_CATEGORY
    if exc_value is not None:
        for exc_cls, cat in _CATEGORY_MAP:
            if isinstance(exc_value, exc_cls):
                category = cat
                break
    code = _CODE_MAP.get(category, _DEFAULT_CODE)
    exc_type_name = type(exc_value).__name__ if exc_value is not None else "Unknown"
    return {
        "code": code,
        "message": f"{exc_type_name}: {exc_value}",
        "traceback": traceback_str,
        "category": category,
    }
```

Note: the `from cardre.execution.validation import LeakageProtectionError, RoleAccessError`
import will fail until Phase 3 creates `validation.py` and moves the exception
classes. For this phase only, use a **lazy import** inside the function body:

```python
def classify_step_failure(exc_value: BaseException | None, traceback_str: str) -> dict[str, Any]:
    from cardre.execution.validation import LeakageProtectionError, RoleAccessError
    # Use locals for the lookups — safe because the classes are stable.
    ...
```

This lazy import will be replaced with a top-level import in Phase 3.

### 3. Wire into `PlanExecutor._execute_step` (edit `executor.py`)

Add import at top of `executor.py`:
```python
from cardre.execution.failure_classification import classify_step_failure
```

Replace the inline classification block (original `executor.py` lines 536-577)
with:
```python
except Exception:
    tb = traceback.format_exc()
    exc_value = sys.exc_info()[1]
    error_entry = classify_step_failure(exc_value, tb)
    recorded_input_ids = [a.artifact_id for a in input_artifacts]
    # ... rest unchanged (lines 579 onward)
```

Remove the now-unused `exc_type = sys.exc_info()[0]` line and the `_CATEGORY_MAP`/
`_CODE_MAP` definitions if they are no longer referenced anywhere else in the file.
Verify: `_CATEGORY_MAP` and `_CODE_MAP` are only used in the inline block — safe to delete.

## Verification

```bash
python3 -m pytest tests/test_execution_failure_classification.py -q --tb=short
python3 -m pytest tests/test_executor_error_classification.py -q --tb=short
python3 -m pytest tests/test_executor_characterization.py::TestExecutorCharacterization::test_failed_step_records_resolved_input_evidence -q --tb=short
python3 -m pytest tests/test_executor.py -q --tb=short
```

## Definition Of Done

- [ ] `classify_step_failure()` in `cardre/execution/failure_classification.py`.
- [ ] All unit tests pass (`test_execution_failure_classification.py`).
- [ ] Existing error-category test (`test_executor_error_classification.py`) still passes.
- [ ] C1 (failed-step evidence) still passes.
- [ ] The `_CATEGORY_MAP`/`_CODE_MAP` definitions are removed from `executor.py`.
- [ ] No circular import errors at runtime.

## Failure Mode

If `import` of `failure_classification` into `executor.py` fails with a cycle:
the lazy import inside `classify_step_failure` is the escape hatch. If the
lazy import works, proceed. The lazy import will be upgraded to top-level in
Phase 3 when the exception classes move.
