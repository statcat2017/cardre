# Phase 3: Extract Validation (Role + Leakage + Artifact Files)

**Goal:** Move role filtering, role-access validation, role matching,
leakage protection, and artifact file/hash validation from `PlanExecutor`
to `cardre/execution/validation.py`. Also move `RoleAccessError` and
`LeakageProtectionError` there to break the circular import introduced in
Phase 2.

## Files

- **Create:** `cardre/execution/validation.py`
- **Edit:** `cardre/executor.py`
- **Edit:** `cardre/execution/failure_classification.py` (upgrade lazy import
  to top-level import)
- **Edit:** `cardre/execution/__init__.py` (add validation re-exports)
- **Create:** `tests/test_execution_validation.py`

## What Moves

| Symbol | Source (executor.py line) | Target function name |
|---|---|---|
| `LEAKAGE_SENSITIVE_CATEGORIES` | 110 | constant in `validation.py` |
| `RoleAccessError` | 947-951 | class in `validation.py` |
| `LeakageProtectionError` | 954-957 | class in `validation.py` |
| `_filter_inputs_by_role` | 655-663 | `filter_inputs_by_role` |
| `_validate_role_access` | 665-692 | `validate_role_access` |
| `_validate_node_input_roles` | 694-713 | `validate_node_input_roles` |
| `validate_leakage_rules` | 715-731 | `validate_leakage_rules` |
| `_validate_input_artifact_files` | 759-776 | `validate_input_artifact_files` |

## Tests to Write First (RED)

### `tests/test_execution_validation.py`

```python
"""Unit tests for cardre/execution/validation.py — no PlanExecutor needed."""
from __future__ import annotations
import pytest
from cardre.audit import ArtifactRef, NodeType, StepSpec, json_logical_hash
from cardre.errors import ArtifactReadError
from cardre.execution.validation import (
    LEAKAGE_SENSITIVE_CATEGORIES,
    RoleAccessError, LeakageProtectionError,
    filter_inputs_by_role, validate_role_access,
    validate_node_input_roles, validate_leakage_rules,
    validate_input_artifact_files,
)
from tests.helpers import make_store, _make_train_artifact
import polars as pl


class _TrainNode(NodeType):
    node_type = "test.train_node"; version = "1"; category = "transform"
    input_roles = ["train"]; output_roles = ["train"]


class _NoRolesNode(NodeType):
    node_type = "test.no_roles"; version = "1"; category = "transform"
    input_roles = []; output_roles = ["out"]


class _FitNode(NodeType):
    node_type = "test.fit"; version = "1"; category = "fit"
    input_roles = ["train"]; output_roles = ["prediction"]


class _ApplyNode(NodeType):
    node_type = "test.apply"; version = "1"; category = "apply"
    input_roles = ["train"]; output_roles = ["prediction"]


class TestFilterInputsByRole:
    def test_no_roles_returns_all(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh"),
                ArtifactRef("a2", "dataset", "test", "p", "ph", "lh")]
        result = filter_inputs_by_role(_NoRolesNode(), arts)
        assert len(result) == 2

    def test_returns_only_permitted(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh"),
                ArtifactRef("a2", "dataset", "test", "p", "ph", "lh")]
        result = filter_inputs_by_role(_TrainNode(), arts)
        assert len(result) == 1
        assert result[0].role == "train"

    def test_empty_list(self):
        result = filter_inputs_by_role(_TrainNode(), [])
        assert result == []


class TestValidateRoleAccess:
    def test_no_roles_passes(self):
        spec = StepSpec("s", "nt", "1", "t", {}, "h", [], "", 0)
        validate_role_access(_NoRolesNode(), spec, [], [])  # no raise

    def test_raises_when_parents_exist_but_no_matching(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        raw = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError):
            validate_role_access(node, spec, [], raw)

    def test_raises_when_artifact_has_unpermitted_role(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        filtered = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        raw = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError, match="cannot consume"):
            validate_role_access(node, spec, filtered, raw)

    def test_passes_when_role_matches(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        filtered = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        raw = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_role_access(node, spec, filtered, raw)  # no raise


class TestValidateNodeInputRoles:
    def test_raises_on_empty_when_roles_declared(self):
        with pytest.raises(RoleAccessError, match="no artifacts"):
            validate_node_input_roles(_TrainNode(), [])

    def test_raises_on_no_matching_role(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError, match="No permitted role"):
            validate_node_input_roles(_TrainNode(), arts)

    def test_passes_when_any_role_matches(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_node_input_roles(_TrainNode(), arts)  # no raise

    def test_no_roles_declared_passes(self):
        validate_node_input_roles(_NoRolesNode(), [])  # no raise


class TestValidateLeakageRules:
    def test_blocks_test_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(LeakageProtectionError):
            validate_leakage_rules(_FitNode(), arts)

    def test_blocks_oot_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "oot", "p", "ph", "lh")]
        with pytest.raises(LeakageProtectionError):
            validate_leakage_rules(_FitNode(), arts)

    def test_allows_train_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_leakage_rules(_FitNode(), arts)  # no raise

    def test_skips_non_sensitive_category(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        validate_leakage_rules(_ApplyNode(), arts)  # no raise

    def test_allows_explicitly_allowed_artifact(self):
        class _CalibNode(_FitNode):
            def allows_leakage_artifact(self, art):
                return True
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        validate_leakage_rules(_CalibNode(), arts)  # no raise


class TestValidateInputArtifactFiles:
    def test_raises_on_missing_file(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        store.artifact_path(art).unlink()
        with pytest.raises(ArtifactReadError):
            validate_input_artifact_files(store, [art])

    def test_raises_on_hash_mismatch(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        p = store.artifact_path(art)
        p.write_text("tampered data")
        with pytest.raises(ArtifactReadError):
            validate_input_artifact_files(store, [art])

    def test_passes_when_file_ok(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        validate_input_artifact_files(store, [art])  # no raise
```

Run:
```
python3 -m pytest tests/test_execution_validation.py -q --tb=short
```
Expected: **fails** (module does not exist yet).

## Implementation

### 1. Create `cardre/execution/validation.py`

Move the 8 symbols listed above. Use exact code from `executor.py` with
renamed functions (drop leading underscore). Import `physical_hash` from
`cardre.audit`, `CardreError`/`ArtifactReadError` from `cardre.errors`,
`ProjectStore` from `cardre.store`.

### 2. Edit `cardre/executor.py`

- Add import block:
  ```python
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
  ```
- Delete the moved constant, class, and method bodies.
- **Add compatibility wrappers** on `PlanExecutor`:
  ```python
  def _filter_inputs_by_role(self, node, artifacts):
      return filter_inputs_by_role(node, artifacts)

  def _validate_role_access(self, node, spec, filtered_artifacts, raw_inputs):
      validate_role_access(node, spec, filtered_artifacts, raw_inputs)

  def _validate_node_input_roles(self, node, artifacts):
      validate_node_input_roles(node, artifacts)

  def validate_leakage_rules(self, node, artifacts):
      validate_leakage_rules(node, artifacts)

  def _validate_input_artifact_files(self, store, artifacts):
      validate_input_artifact_files(store, artifacts)
  ```
- Replace inline calls in `_execute_step` (lines 493-498):
  ```python
  input_artifacts = filter_inputs_by_role(node, raw_inputs)
  validate_role_access(node, spec, input_artifacts, raw_inputs)
  validate_node_input_roles(node, input_artifacts)
  validate_leakage_rules(node, input_artifacts)
  validate_input_artifact_files(store, input_artifacts)
  ```

### 3. Edit `cardre/execution/failure_classification.py`

Replace the lazy import:
```python
from cardre.execution.validation import LeakageProtectionError, RoleAccessError
```
with a top-level import (same path). Remove the function-body import.

### 4. Edit `cardre/execution/__init__.py`

Add validation re-exports:
```python
from cardre.execution.validation import (
    LEAKAGE_SENSITIVE_CATEGORIES,
    RoleAccessError,
    LeakageProtectionError,
    filter_inputs_by_role,
    validate_role_access,
    validate_node_input_roles,
    validate_leakage_rules,
    validate_input_artifact_files,
)
```

## Verification

```bash
python3 -m pytest tests/test_execution_validation.py -q --tb=short
python3 -m pytest tests/test_executor.py -q --tb=short
python3 -m pytest tests/test_executor_characterization.py -q --tb=short
python3 -m pytest tests/test_executor_error_classification.py -q --tb=short
python3 -m pytest tests/test_executor_branch_execution.py -q --tb=short
python3 -c "from cardre.executor import RoleAccessError, LeakageProtectionError"
python3 -c "from cardre import RoleAccessError"
```

## Definition Of Done

- [ ] All validation functions + constants in `validation.py`.
- [ ] All unit tests pass (`test_execution_validation.py`).
- [ ] C2 (role access) and C3 (leakage) pass with exact codes.
- [ ] `tests/test_executor.py` direct calls to `executor._validate_input_artifact_files`
      still work (via wrapper).
- [ ] `cardre/__init__.py` `from cardre.executor import PlanExecutor, RoleAccessError` works.
- [ ] `failure_classification.py` has top-level import of `RoleAccessError`/`LeakageProtectionError`.
- [ ] No circular imports.

## Failure Mode

If a circular import emerges between `executor.py` and `validation.py`
(e.g. `validation.py` imports something from `executor.py` that references
back), check the import chain. The plan is designed to be acyclic:
`validation.py` imports only from `cardre.audit`, `cardre.errors`,
`cardre.store` — never from `cardre.executor`. If `failure_classification.py`
still has the lazy import (Phase 2 escape hatch), upgrade it now.
