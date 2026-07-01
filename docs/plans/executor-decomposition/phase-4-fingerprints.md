# Phase 4: Extract Fingerprint Construction

**Goal:** Extract `_build_execution_fingerprint`, `_output_logical_hashes`,
and `_build_parent_output_hashes` from `PlanExecutor` to
`cardre/execution/fingerprints.py` as pure functions.

## Files

- **Create:** `cardre/execution/fingerprints.py`
- **Edit:** `cardre/executor.py`
- **Edit:** `cardre/execution/__init__.py` (add fingerprint re-exports)
- **Create:** `tests/test_execution_fingerprints.py`

## Tests to Write First (RED)

### `tests/test_execution_fingerprints.py`

```python
"""Unit tests for cardre/execution/fingerprints.py — no PlanExecutor needed."""
from __future__ import annotations
import sys
from cardre.audit import ArtifactRef, RunStepRecord, StepSpec, json_logical_hash
from cardre.execution.fingerprints import (
    build_execution_fingerprint,
    build_parent_output_hashes,
    output_logical_hashes,
)


def _spec(step_id="s1", node_type="nt", node_version="1"):
    return StepSpec(step_id=step_id, node_type=node_type, node_version=node_version,
                    category="transform", params={},
                    params_hash=json_logical_hash({}),
                    parent_step_ids=[], branch_label="", position=0)


def _art(role="train", aid="a1", logical_hash="lh1"):
    return ArtifactRef(artifact_id=aid, artifact_type="dataset", role=role,
                       path="p", physical_hash="ph", logical_hash=logical_hash)


def _rs(step_id="p1", output_hashes=None):
    fp = {"output_artifact_logical_hashes": output_hashes or []}
    return RunStepRecord(run_step_id="r1", run_id="run", step_id=step_id,
                         plan_version_id="pv", status="succeeded",
                         started_at="", finished_at="",
                         input_artifact_ids=[], output_artifact_ids=[],
                         execution_fingerprint=fp, warnings=[], errors=[])


class TestBuildExecutionFingerprint:
    def test_contains_all_required_keys(self):
        spec = _spec(step_id="child")
        fp = build_execution_fingerprint("pv1", spec, [], [], [])
        for k in ["plan_version_id", "step_id", "node_type", "node_version",
                   "params_hash", "parent_run_step_ids",
                   "input_artifact_logical_hashes",
                   "output_artifact_logical_hashes",
                   "parent_output_logical_hashes_by_step",
                   "python_version", "cardre_version"]:
            assert k in fp, f"Missing key: {k}"

    def test_plan_version_id_and_step_id(self):
        fp = build_execution_fingerprint("pv1", _spec(), [], [], [])
        assert fp["plan_version_id"] == "pv1"
        assert fp["step_id"] == "s1"

    def test_node_type_and_version(self):
        spec = _spec(node_type="my.node", node_version="2")
        fp = build_execution_fingerprint("pv", spec, [], [], [])
        assert fp["node_type"] == "my.node"
        assert fp["node_version"] == "2"

    def test_params_hash(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["params_hash"] == json_logical_hash({})

    def test_parent_run_step_ids_with_parents(self):
        parent_rs = _rs(step_id="p1")
        fp = build_execution_fingerprint("pv", _spec(), [parent_rs], [], [])
        assert fp["parent_run_step_ids"] == ["r1"]

    def test_input_artifact_logical_hashes(self):
        arts = [_art(logical_hash="lh_in")]
        fp = build_execution_fingerprint("pv", _spec(), [], arts, [])
        assert fp["input_artifact_logical_hashes"] == ["lh_in"]

    def test_output_artifact_logical_hashes(self):
        arts = [_art(logical_hash="lh_out")]
        fp = build_execution_fingerprint("pv", _spec(), [], [], arts)
        assert fp["output_artifact_logical_hashes"] == ["lh_out"]

    def test_parent_output_logical_hashes_by_step(self):
        parent_rs = _rs(step_id="p1", output_hashes=["h1", "h2"])
        fp = build_execution_fingerprint("pv", _spec(), [parent_rs], [], [])
        assert fp["parent_output_logical_hashes_by_step"] == {"p1": ["h1", "h2"]}

    def test_python_version(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["python_version"] == sys.version.split()[0]

    def test_cardre_version(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["cardre_version"] == "0.1.0"

    def test_empty_parent_lists(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["parent_run_step_ids"] == []
        assert fp["parent_output_logical_hashes_by_step"] == {}


class TestOutputLogicalHashes:
    def test_returns_list_from_fingerprint(self):
        rs = _rs(output_hashes=["h1", "h2"])
        assert output_logical_hashes(rs) == ["h1", "h2"]

    def test_returns_empty_list_when_missing(self):
        rs = RunStepRecord(run_step_id="r1", run_id="run", step_id="s1",
                           plan_version_id="pv", status="succeeded",
                           started_at="", finished_at="",
                           input_artifact_ids=[], output_artifact_ids=[],
                           execution_fingerprint={}, warnings=[], errors=[])
        assert output_logical_hashes(rs) == []


class TestBuildParentOutputHashes:
    def test_maps_step_id_to_hashes(self):
        rs1 = _rs(step_id="p1", output_hashes=["h1"])
        rs2 = _rs(step_id="p2", output_hashes=["h2", "h3"])
        result = build_parent_output_hashes([rs1, rs2])
        assert result == {"p1": ["h1"], "p2": ["h2", "h3"]}

    def test_empty_input_returns_empty_dict(self):
        assert build_parent_output_hashes([]) == {}
```

Run:
```bash
python3 -m pytest tests/test_execution_fingerprints.py -q --tb=short
```
Expected: **fails** (module does not exist yet).

## Implementation

### 1. Create `cardre/execution/fingerprints.py`

```python
"""Execution fingerprint construction for RunStepRecord.

Pure data construction from StepSpec, RunStepRecord, and ArtifactRef.
No ProjectStore, no orchestration.
"""
from __future__ import annotations

import sys
from typing import Any

from cardre.audit import ArtifactRef, RunStepRecord, StepSpec

CARDRE_VERSION = "0.1.0"


def output_logical_hashes(rs: RunStepRecord) -> list[str]:
    return rs.execution_fingerprint.get("output_artifact_logical_hashes", [])


def build_parent_output_hashes(
    parent_run_steps: list[RunStepRecord],
) -> dict[str, list[str]]:
    return {rs.step_id: output_logical_hashes(rs) for rs in parent_run_steps}


def build_execution_fingerprint(
    plan_version_id: str,
    spec: StepSpec,
    parent_run_steps: list[RunStepRecord],
    input_artifacts: list[ArtifactRef],
    output_artifacts: list[ArtifactRef],
) -> dict[str, Any]:
    return {
        "plan_version_id": plan_version_id,
        "step_id": spec.step_id,
        "node_type": spec.node_type,
        "node_version": spec.node_version,
        "params_hash": spec.params_hash,
        "parent_run_step_ids": [rs.run_step_id for rs in parent_run_steps],
        "input_artifact_logical_hashes": [a.logical_hash for a in input_artifacts],
        "output_artifact_logical_hashes": [a.logical_hash for a in output_artifacts],
        "parent_output_logical_hashes_by_step": build_parent_output_hashes(parent_run_steps),
        "python_version": sys.version.split()[0],
        "cardre_version": CARDRE_VERSION,
    }
```

### 2. Edit `cardre/executor.py`

- Add import:
  ```python
  from cardre.execution.fingerprints import build_execution_fingerprint
  ```
- Add compatibility wrapper on `PlanExecutor`:
  ```python
  def _build_execution_fingerprint(self, plan_version_id, spec, parent_run_steps, input_artifacts, output_artifacts):
      return build_execution_fingerprint(plan_version_id, spec, parent_run_steps, input_artifacts, output_artifacts)
  ```
- Replace the two calls in `_execute_step`:
  - Success path (original ~line 518): `output.execution_fingerprint = build_execution_fingerprint(plan_version_id, spec, parent_run_steps, input_artifacts, output.artifacts)`
  - Failure path (original ~line 584): `output.execution_fingerprint = build_execution_fingerprint(plan_version_id, spec, parent_run_steps, input_artifacts, [])`
- Delete the moved methods `_build_execution_fingerprint`, `_output_logical_hashes`,
  `_build_parent_output_hashes` from `executor.py`.

### 3. Edit `cardre/execution/__init__.py`

Add:
```python
from cardre.execution.fingerprints import (
    build_execution_fingerprint,
    build_parent_output_hashes,
    output_logical_hashes,
)
```

## Verification

```bash
python3 -m pytest tests/test_execution_fingerprints.py -q --tb=short
python3 -m pytest tests/test_executor.py -q --tb=short
python3 -m pytest tests/test_executor_characterization.py::TestExecutorCharacterization::test_execution_fingerprint_contract_for_successful_step -q --tb=short
python3 -m pytest tests/test_staleness.py -q --tb=short
python3 -m pytest tests/test_manifest.py -q --tb=short
```

## Definition Of Done

- [ ] `build_execution_fingerprint()` in `cardre/execution/fingerprints.py`.
- [ ] All unit tests pass (`test_execution_fingerprints.py`).
- [ ] C4 (fingerprint contract) passes.
- [ ] Staleness tests pass (they read fingerprint keys).
- [ ] Manifest tests pass (they read fingerprint keys).
- [ ] The moved methods are deleted from `executor.py`.

## Failure Mode

If staleness tests fail, check that `build_parent_output_hashes` and
`output_logical_hashes` produce the exact same dict shape as before — the
key name `parent_output_logical_hashes_by_step` must match. If a test in
`test_staleness.py` constructs a `RunStepRecord` directly, it uses the same
`execution_fingerprint` dict — the extracted functions only create these
dicts, they don't change the schema.
