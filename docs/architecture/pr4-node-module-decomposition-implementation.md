# PR 4: Behavior-Preserving Node Module Decomposition

## Audience And Goal

This is a prescriptive implementation guide for a smaller coding agent. It
describes PR 4 of the remediation sprint: split independent node bundles into
small, testable modules without changing their observable behavior.

The baseline is `main` at commit `4892c26`. The existing test suite and
execution artifacts are the specification. This PR is a structural refactor,
not a feature change.

## Scope

| Existing module | New ownership boundary | Required outcome |
| --- | --- | --- |
| `cardre/nodes/feature_selection.py` | one module per filter, embedded, resampling, and SMOTE node; one narrow definition helper | Keep all four node identifiers and results unchanged. |
| `cardre/nodes/validate/analyse.py` | validation metrics, threshold optimization, cutoff analysis, and metrics-only calculation helpers | Keep metric formulas, gates, artifact schemas, and role-priority behavior unchanged. |
| `cardre/nodes/build/bins.py` | automatic-binning orchestration, fine-classing helpers, and manual-binning application | Keep schemas, bin IDs, bin payloads, override behavior, and optional optbinning dispatch unchanged. |
| `cardre/nodes/build/clustering.py` | no structural extraction required | Remove the broad `ValueError` recovery that hides real computation failures. |

## Hard Constraints

1. Do not alter `node_type`, `version`, `category`, input roles, output roles,
   optional dependencies, parameter defaults, or parameter validation messages
   unless a test proves the old value was incorrect. This PR should not do that.
2. Do not alter artifact stems, roles, metadata keys, payload schemas, warning
   codes, selection order, score calculations, random seeds, or result metrics.
3. Do not add compatibility forwarding modules for removed internal import
   paths. Update Cardre imports and tests to their new modules. Keep public
   class names re-exported from `cardre.nodes`, `cardre.nodes.validate`, and
   `cardre.nodes.build`.
4. Do not create one new catch-all `utils.py`, `common.py`, `base.py`, or
   replacement mega-module. A helper belongs with the smallest group of callers
   that share its policy.
5. Keep every new or changed Python module at 300 lines or fewer. Run
   `python3 scripts/check-line-counts.py` after every extraction.
6. Do not edit workflow topology, SQLite schema, frontend code, model-artifact
   contracts, OpenAPI schemas, or node-parameter infrastructure in this PR.
7. Move code first. Change behavior only for the explicitly listed clustering
   error boundary, and test that change directly.

## Why This Is Safe To Do Now

PRs 1 through 3 established enforcement, manifest/scoring contracts, and
frontend boundaries. The remaining large node files are now the main source of
mixed responsibilities:

| Module | Current size |
| --- | ---: |
| `feature_selection.py` | 805 lines |
| `validate/analyse.py` | 917 lines |
| `build/bins.py` | 820 lines |
| `build/clustering.py` | 782 lines |

The point is not to make files arbitrarily small. The point is to put code
that changes for different reasons behind separate module boundaries. Each
node class is already a natural seam.

## Delivery Order

Implement one ownership area at a time. Do not start the next area until its
focused tests, import checks, and line-count check pass.

1. Establish characterization tests and record the baseline behavior.
2. Decompose feature selection.
3. Decompose validation analysis.
4. Decompose automatic/manual binning.
5. Narrow clustering error recovery.
6. Run the combined focused suite, then preflight and the PR gate.

Commit after each numbered area if practical. This makes regressions easy to
bisect and review.

---

## Phase 0: Characterize Before Moving

Run the currently owning tests before any edit:

```bash
. .venv/bin/activate
python3 -m pytest tests/test_feature_selection.py tests/test_training_resampling.py -q --tb=short --no-cov
python3 -m pytest tests/test_binning_node.py tests/test_clustering_node.py -q --tb=short --no-cov
python3 scripts/check-line-counts.py
```

`tests/test_feature_selection.py` is intentionally empty at this baseline.
Replace it in this PR with real node-level tests; do not delete it.

There is no focused validation-analysis test module yet. Add one focused test
module per node family before moving implementation. Do not rely only on
executor, report, or end-to-end workflow tests.

### Required Registry Characterization

Before and after every extraction, prove the public registry contract stayed
stable. Add this to the most appropriate focused test module:

```python
from cardre.nodes.registry import NodeRegistry


def test_registry_preserves_decomposed_node_identifiers() -> None:
    registry = NodeRegistry.with_defaults()

    assert registry.resolve("cardre.feature_selection_filter").__name__ == "FeatureSelectionFilterNode"
    assert registry.resolve("cardre.feature_selection_embedded").__name__ == "FeatureSelectionEmbeddedNode"
    assert registry.resolve("cardre.resample_training_data").__name__ == "ResampleTrainingDataNode"
    assert registry.resolve("cardre.smote_training_data").__name__ == "SmoteTrainingDataNode"
    assert registry.resolve("cardre.validation_metrics").__name__ == "ValidationMetricsNode"
    assert registry.resolve("cardre.threshold_optimization").__name__ == "ThresholdOptimizationNode"
    assert registry.resolve("cardre.cutoff_analysis").__name__ == "CutoffAnalysisNode"
    assert registry.resolve("cardre.automatic_binning").__name__ == "AutomaticBinningNode"
    assert registry.resolve("cardre.manual_binning").__name__ == "ManualBinningNode"
```

This is a registry and public-class-name test only. It must not assert where a
class is implemented.

### Required Artifact Characterization

For every node moved, compare the full serialized JSON payload of a known
small fixture before and after the move. Assertions should include:

1. Artifact role, type, stem prefix, and metadata keys.
2. Ordered `selected` and `rejected` values for feature selection.
3. Validation role keys, gate codes/statuses, and `schema_version`.
4. Automatic-binning variable order, bin IDs, inclusion flags, counts, and
   special/missing/other-bin fields.
5. Manual-binning override output including all untouched variables.

Do not compare physical artifact paths, generated timestamps, logical hashes,
or run IDs. They are not stable across test runs.

---

## Phase 1: Feature Selection Package

### Target Layout

Replace the single module with this package. The paths below are proposed new
files, so they are intentionally not formatted as links to existing files.

```text
cardre/nodes/selection/
  __init__.py
  _definition.py
  filter.py
  embedded.py
  resampling.py
  smote.py
```

Delete `cardre/nodes/feature_selection.py` after all imports and tests have
moved. Do not leave a file that imports everything from the new package.

### 1.1 Narrow Shared Definition Policy

Move `_typed_definition_payload` into `_definition.py`. Add exactly one
definition-merge helper. It owns only the shared read priority and mutation
shape used by filter and embedded selection.

```python
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader


def typed_definition_payload(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def merge_selection_definition(
    reader: ArtifactEvidenceReader,
    definition_artifact_id: str | None,
    *,
    key: Literal["selection_filter", "selection_embedded"],
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Merge one selection result into a prior definition without changing its shape."""
    if definition_artifact_id is None:
        return selection

    existing_typed = (
        reader.read_optional(definition_artifact_id, EvidenceKind.FEATURE_SELECTION_EVIDENCE)
        or reader.read_optional(definition_artifact_id, EvidenceKind.MODELLING_METADATA)
        or reader.read_optional(definition_artifact_id, EvidenceKind.SELECTION_DEFINITION)
    )
    existing = typed_definition_payload(existing_typed)
    existing["selected"] = [entry["variable"] for entry in selection["selected"]]
    existing[key] = selection
    existing["selected_count"] = selection["selected_count"]
    existing["rejected_count"] = selection["rejected_count"]
    return existing
```

Important behavior requirements:

1. Keep evidence lookup priority exactly as it is now: feature-selection
   evidence, then modelling metadata, then selection definition.
2. Preserve the old defensive behavior. The caller catches only the current
   `KeyError`, `TypeError`, and `AttributeError` around merge and logs the same
   warning. The helper itself must not convert an unexpected read failure into
   an empty definition.
3. The helper receives an artifact ID or `None`, not `ExecutionContext`. It is
   a data-merge policy, not a hidden node framework.
4. Do not merge the filter and embedded algorithm output shapes. Their
   algorithm-specific fields remain different.

### 1.2 Move One Node Per Module

Move classes mechanically, with no algorithm edits:

| New module | Move exactly |
| --- | --- |
| selection/filter.py | `FeatureSelectionFilterNode` |
| selection/embedded.py | `FeatureSelectionEmbeddedNode` |
| selection/resampling.py | `ResampleTrainingDataNode` |
| selection/smote.py | `SmoteTrainingDataNode` |

The four files must keep these identifiers unchanged:

```python
FeatureSelectionFilterNode.node_type = "cardre.feature_selection_filter"
FeatureSelectionEmbeddedNode.node_type = "cardre.feature_selection_embedded"
ResampleTrainingDataNode.node_type = "cardre.resample_training_data"
SmoteTrainingDataNode.node_type = "cardre.smote_training_data"
```

`selection/__init__.py` re-exports all four class names. Update
`cardre/nodes/__init__.py` to import those class names from the new package.
The deferred registry already imports these classes through `cardre.nodes`, so
the registry list and node identifiers must not change.

### 1.3 Required Feature-Selection Tests

Replace the empty `tests/test_feature_selection.py` with direct tests. Keep
the existing execution-oriented cases in `tests/test_training_resampling.py`,
but update their imports to the new module paths.

#### Definition Merge Test

Test filter and embedded merge behavior against the same pre-existing
definition fixture. Mock the reader's `read_optional` calls or use a tiny
reader fake. Assert the merge shape, not the helper's implementation details.

```python
@pytest.mark.parametrize(
    ("key", "method"),
    [
        ("selection_filter", "filter"),
        ("selection_embedded", "embedded"),
    ],
)
def test_merge_selection_definition_preserves_existing_fields(key: str, method: str) -> None:
    reader = FakeReader({"project_name": "Credit", "target_column": "bad"})
    selection = {
        "method": method,
        "selected": [{"variable": "income"}],
        "rejected": [{"variable": "age"}],
        "selected_count": 1,
        "rejected_count": 1,
    }

    merged = merge_selection_definition(
        reader, "definition-artifact", key=key, selection=selection,
    )

    assert merged["project_name"] == "Credit"
    assert merged["selected"] == ["income"]
    assert merged[key] == selection
    assert merged["selected_count"] == 1
    assert merged["rejected_count"] == 1
```

#### Filter Tests

Use a small Polars train frame with one clearly missing, one zero-variance,
one low-IV, and two correlated columns. Assert:

1. Threshold rejections retain the existing reason strings and method names.
2. The IV tie-break retains the earlier column and rejects the later one.
3. `max_features` is applied after filtering and sorts by IV descending.
4. The JSON output has the same artifact stem prefix and metadata.

#### Embedded Tests

Use a deterministic small binary fixture with `random_seed` fixed. Assert:

1. Invalid estimator, threshold, and max-feature parameters return current
   validation messages.
2. `max_features=1` leaves one selected item and moves the rest to rejected.
3. Definition output contains `selection_embedded`; report output contains
   `feature_importance`.
4. Use a threshold that does not rely on a brittle exact sklearn importance
   value. Assert ordering and counts, not an opaque floating-point value.

#### Resampling And SMOTE Tests

Keep the existing real behavior tests in `tests/test_training_resampling.py`.
Add direct import tests that prove the moved classes still:

1. reject invalid strategy/ratio/seed values;
2. reject a single-class training input for ordinary resampling;
3. preserve `_is_synthetic_row` for original rows;
4. mark only generated rows as synthetic;
5. reject insufficient minority examples for SMOTE before producing artifacts;
6. preserve the `imbalance` optional dependency declaration.

Do not make SMOTE tests require the optional dependency in the default suite.
Use its existing availability/optional-dependency test strategy.

---

## Phase 2: Validation Analysis Package

### Target Layout

Replace the analysis mega-module with this package structure:

```text
cardre/nodes/validate/
  __init__.py
  apply.py                         # unchanged
  metrics.py                       # ValidationMetricsNode only
  _metrics_calculation.py          # pure metrics helpers used only by metrics.py
  threshold.py                     # ThresholdOptimizationNode only
  cutoff.py                        # CutoffAnalysisNode only
```

Delete `cardre/nodes/validate/analyse.py` after imports move. Do not preserve
the old module as a forwarding import.

### 2.1 Keep Validation Metrics Node Thin

`ValidationMetricsNode` currently owns both execution orchestration and all
calculation details. Move its calculation-only methods to
_metrics_calculation.py as functions. Keep `metrics.py` responsible for:

1. `node_type`, version, roles, and parameter schema;
2. reading `ExecutionContext` and evidence;
3. calling calculation helpers;
4. writing the report artifact;
5. raising `NodeFailedWithArtifacts` when gates fail.

Move the following behavior to calculation helpers without changing their
inputs or outputs:

| Existing method | Proposed helper |
| --- | --- |
| `_derive_y_bin` | `derive_binary_target` |
| `_compute_role_metrics` | `compute_role_metrics` |
| `_compute_stability` | `compute_stability` |
| `_apply_threshold_gates` | `apply_threshold_gates` |
| `_build_payload` | `build_validation_payload` |
| `_calibration` | `calibration_summary` |
| `_score_distribution` | `score_distribution` |
| `_psi` | `population_stability_index` |

Use plain functions, not a new class. A calculation helper must receive all
data it uses explicitly; it must not import or construct `ExecutionContext`.

Example signature:

```python
def derive_binary_target(
    frame: pl.DataFrame,
    target_column: str,
    good_values: set[str],
    bad_values: set[str],
) -> tuple[np.ndarray | None, np.ndarray | None, list[JsonDict]]:
    """Return current y_bin, known-row mask, and validation warnings unchanged."""
```

Do not use this extraction as an opportunity to change any of these details:

1. Unknown target values are excluded and emit `UNKNOWN_TARGET_VALUES`.
2. A single class emits the current warning codes and leaves discrimination
   metrics unavailable.
3. PSI empty-bin flooring is unchanged.
4. Threshold gates are applied after role metrics and stability are computed.
5. A failed required gate writes the report first, then raises
   `NodeFailedWithArtifacts` with that report.

### 2.2 Move Threshold And Cutoff Nodes Whole

Move `ThresholdOptimizationNode` into threshold.py and `CutoffAnalysisNode`
into cutoff.py without extracting speculative shared abstractions.

Preserve these selection and output rules exactly:

```text
Threshold role priority: test, then train, then oot, then 0.5 fallback.
Threshold objectives: youden, max_f1, max_g_mean, cost_minimize.
Cutoff explicit cutoffs override generated equal-width bands.
Cutoff analysis skips a role lacking score or predicted_bad_probability.
```

Keep imports in `cardre/nodes/validate/__init__.py` as the public API. The
registry imports `ValidationMetricsNode` and `CutoffAnalysisNode` from that
package; it should not need changes beyond the package re-exports.

### 2.3 Required Validation Tests

Create three focused test modules, one per node boundary. Do not make a
single validation integration file with all assertions.

#### Validation Metrics

Test helper functions directly for deterministic edge cases, then add one
node-level artifact/gate test.

```python
def test_derive_binary_target_excludes_unknown_target_values() -> None:
    frame = pl.DataFrame({"bad": ["N", "Y", "unknown"], "score": [500, 400, 450]})

    y_bin, known_mask, warnings = derive_binary_target(
        frame, "bad", {"N"}, {"Y"},
    )

    assert y_bin.tolist() == [0, 1]
    assert known_mask.tolist() == [True, True, False]
    assert [warning["code"] for warning in warnings] == ["UNKNOWN_TARGET_VALUES"]
```

Required metrics cases:

1. Missing target column produces the current warning and, when configured,
   a failing target gate.
2. All-good and all-bad target cases retain the existing single-class warning
   codes and do not call AUC on invalid data.
3. Missing score produces the current gate behavior.
4. A PSI empty bin emits `PSI_EMPTY_BIN` and remains finite.
5. A failing gate returns a report artifact through `NodeFailedWithArtifacts`.
6. A successful payload preserves `SCHEMA_VALIDATION_METRICS`, role ordering,
   source references, and gates.

#### Threshold Optimization

Use a tiny known probability/target fixture. Assert the selected threshold
without asserting every vectorized intermediate value.

```python
def test_threshold_prefers_test_role_over_train_and_oot(...) -> None:
    # Give each role a valid but different optimum.
    # Assert report["selected_threshold"] equals the test optimum.
    ...
```

Required cases:

1. Every accepted objective produces a threshold in `[0, 1]`.
2. `cost_minimize` rejects missing/non-numeric costs using current messages.
3. A missing probability column records the current role error.
4. A single-class role is skipped without an exception.
5. Test/train/oot priority and 0.5 fallback remain exact.

#### Cutoff Analysis

Required cases:

1. Explicit cutoffs are sorted and take precedence over `band_count`.
2. Generated bands use current equal-width boundaries.
3. Missing target metadata emits the existing warning and reports neutral
   target-derived values.
4. Zero-variance score still raises the current error.
5. Output retains `SCHEMA_CUTOFF_ANALYSIS` and the current per-role table
   shape: `score_cutoff`, `approval_rate`, `bad_rate`, `capture_rate`.

---

## Phase 3: Automatic And Manual Binning

### Target Layout

Automatic binning contains two independent concerns: method selection/schema
and fine-classing implementation. Fine classing itself has numeric and
categorical algorithms. Split it deliberately so the result stays under the
line-count limit.

```text
cardre/nodes/build/
  automatic.py
  _automatic_params.py
  _fine_classing.py
  _fine_classing_numeric.py
  _fine_classing_categorical.py
  _bin_counts.py
  _optbinning.py                  # existing module; retain
  manual.py
```

Delete `cardre/nodes/build/bins.py` after all imports move.

### 3.1 Automatic Binning Ownership

`automatic.py` contains only `AutomaticBinningNode` and the dispatch:

```python
class AutomaticBinningNode(NodeType):
    node_type = "cardre.automatic_binning"
    version = "1"
    category = "fit"
    input_roles = ["train", "definition"]
    output_roles = ["definition", "report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return automatic_binning_parameter_schema(cls.node_type, cls.version)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return validate_automatic_binning_params(params)

    def run(self, context: ExecutionContext) -> NodeOutput:
        method = context.validated_params.get("method", "fine_classing")
        if method == "fine_classing":
            return run_fine_classing(context)
        if method == "optbinning":
            return run_optbinning(context)
        raise ValueError(f"Unknown binning method: {method!r}")
```

The snippet is structural. Preserve exact existing strings, parameter schema,
and names in the final implementation. In particular, do not rename `method`,
change `VALID_METHODS`, alter coming-soon options, or replace optional
dependency checks.

Put the complete `NodeParameterSchema`, fine-classing validation, and
optbinning validation in `_automatic_params.py`. That module owns only
automatic-binning parameter policy.

### 3.2 Fine-Classing Ownership

Move the high-level loop and final definition payload to `_fine_classing.py`.
Move numeric bin construction to `_fine_classing_numeric.py`, categorical bin
construction to `_fine_classing_categorical.py`, and count calculation to
`_bin_counts.py` if doing so keeps all modules under the line limit.

Required behavior to preserve:

1. Feature columns exclude configured columns and the target column.
2. Target metadata validation occurs before bin construction, with current
   error messages.
3. Variable order is input DataFrame column order.
4. Numeric, categorical, missing, and other bins retain their current IDs,
   labels, boundary inclusion flags, counts, and booleans.
5. Warning ordering is unchanged.
6. `SCHEMA_BIN_DEFINITION` remains in the definition payload and metadata.
7. The existing optbinning implementation remains in `_optbinning.py`; do not
   copy it or make it import fine-classing internals.

Keep function arguments explicit. Do not create a mutable configuration object
just to avoid passing `target_column`, good/bad values, bin counts, and policy
parameters.

### 3.3 Manual Binning Ownership

Move `ManualBinningNode`, `validate_manual_binning_overrides`, and
`apply_manual_binning_overrides` into manual.py. Keep the two functions
available from `cardre.nodes.build` through its `__init__.py` re-export because
other Cardre code imports them from that package.

Do not move `LifecycleBinDefinition` algorithms into the node package. The
node remains an adapter that:

1. reads the bin/selection evidence;
2. validates overrides using the engine model;
3. applies overrides using the engine model;
4. writes the refined definition artifact.

Keep these invariants unchanged:

```text
reviewed and accept_automated cannot both be true.
merge_bins requires at least two source IDs.
Unknown action/reason code is rejected before artifact writing.
Selection-definition variables constrain overrides when selection evidence exists.
```

### 3.4 Import And Registry Changes

Update `cardre/nodes/build/__init__.py` to re-export:

```python
from cardre.nodes.build.automatic import AutomaticBinningNode
from cardre.nodes.build.manual import (
    ManualBinningNode,
    apply_manual_binning_overrides,
    validate_manual_binning_overrides,
)
```

`NodeRegistry` imports these names from `cardre.nodes.build`; preserve that
boundary. Do not change launch/deferred registration or node IDs.

Update direct test imports from the removed bins module to their narrow owner.
For example, tests for `AutomaticBinningNode` import from automatic.py; tests
for override helpers import from manual.py.

### 3.5 Required Binning Tests

Keep existing parameter tests in `tests/test_binning_node.py`, then add
behavior tests rather than only dispatch tests.

#### Automatic Fine Classing

Use a small DataFrame with one numeric, one categorical, one missing value,
and target values matching modelling metadata. Assert:

1. Variables retain source column order.
2. Numeric bin boundaries are deterministic for the fixture.
3. Missing-policy `separate_bin` creates the existing missing-bin shape.
4. Categorical levels above `max_categorical_levels` produce the existing
   `Other` representation.
5. Excluded columns and target are absent from variables.
6. Invalid target metadata and missing target column preserve current errors.
7. `method="optbinning"` still dispatches to the existing optbinning entry
   point. Patch the symbol at its new import location.

#### Manual Binning

Add direct node/helper tests for:

1. Invalid override action, missing reason, invalid reason code, non-list
   source IDs, and one-bin merge errors.
2. Merge of two known bins leaves unrelated variables untouched.
3. Selected-variable constraints reject an override outside the selected set.
4. `accept_automated` with no overrides preserves definition payload content.
5. A valid override writes a definition with the existing stem and metadata.

Use `LifecycleBinDefinition` fixtures or the existing bin-definition fixture
shape. Do not hand-build a second interpretation of bin semantics in tests.

---

## Phase 4: Clustering Must Not Hide Computation Failures

### Existing Problem

`VariableClusteringNode._cluster_candidates` currently catches every
`ValueError` and turns it into `CLUSTERING_FAILED` plus singleton pass-through.
That includes unexpected numeric/data bugs. A malformed correlation result or
programming error can therefore appear as a successful node with a warning.

### Required Change

Retain explicit no-cluster outcomes only where the code can prove the evidence
is insufficient:

1. fewer than two candidate columns: `INSUFFICIENT_CANDIDATES`;
2. WOE representation requested but bin/WOE evidence absent:
   `WOE_EVIDENCE_MISSING`;
3. fewer than two transformed WOE columns: `INSUFFICIENT_WOE_COLUMNS`;
4. no WOE expressions: `NO_WOE_COLUMNS`;
5. no complete cases and low/no pairwise overlap remain explicit warnings from
   `_compute_correlation_matrix`.

Remove the broad block equivalent to:

```python
except ValueError:
    return singleton_pass_through(..., code="CLUSTERING_FAILED")
```

Do not replace it with `except Exception`, a broader Polars/Numpy exception
tuple, or a generic diagnostic conversion. Unexpected failures must propagate
from the node. `StepRunner` then marks the step failed and records the causal
error through the existing execution machinery.

If repeated explicit singleton construction makes the method hard to read,
extract one small private helper that returns the existing
`(clusters, singletons, warnings)` tuple. It may accept a warning code and
message. It must not catch exceptions.

```python
def singleton_result(
    candidates: list[str], *, code: str, message: str,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    return [], list(candidates), [{
        "code": code,
        "severity": "warning",
        "variable_a": "",
        "variable_b": "",
        "message": message,
    }]
```

Use the exact current warning wording where it already exists. Do not emit a
new `CLUSTERING_FAILED` warning for unexpected failures.

### Required Clustering Tests

Keep the three existing integration tests in `tests/test_clustering_node.py`:

1. WOE evidence missing produces singleton pass-through.
2. Raw train clustering succeeds.
3. Insufficient candidates produces singleton pass-through.

Add these focused cases:

```python
def test_unexpected_correlation_value_error_propagates(monkeypatch) -> None:
    node = VariableClusteringNode()

    def fail(*args, **kwargs):
        raise ValueError("correlation matrix is malformed")

    monkeypatch.setattr(node, "_compute_correlation_matrix", fail)

    with pytest.raises(ValueError, match="correlation matrix is malformed"):
        node._cluster_candidates(
            frame_with_two_numeric_columns,
            ["income", "age"],
            None, None, {}, {}, "raw_train", "correlation_threshold",
            "pearson", "pairwise", True, 1, None, 0.7, "highest_iv", 50,
        )
```

Also test this at the node execution boundary if the existing `StepRunner`
fixture makes it inexpensive: a real unexpected `ValueError` must result in a
failed step, not `RunStepStatus.SUCCEEDED` plus a warning artifact.

---

## Import Migration Checklist

After each extraction, search production code and tests for old paths. Update
all internal imports before deleting an original module.

```bash
git grep -n "cardre.nodes.feature_selection"
git grep -n "cardre.nodes.validate.analyse"
git grep -n "cardre.nodes.build.bins"
python3 scripts/check-line-counts.py
```

Expected final state:

1. No production or test import of the three removed source modules remains.
2. `cardre.nodes`, `cardre.nodes.validate`, and `cardre.nodes.build` still
   export the same public class names used by registry construction.
3. Registry resolution and availability tiers are unchanged.
4. No new module exceeds the line-count limit.

## Focused Verification

Run these commands after all four phases:

```bash
. .venv/bin/activate
python3 -m pytest tests/test_feature_selection.py tests/test_training_resampling.py -q --tb=short --no-cov
python3 -m pytest tests/test_binning_node.py tests/test_clustering_node.py -q --tb=short --no-cov
python3 -m pytest tests/ -q --tb=short --no-cov
python3 -m mypy
python3 scripts/check-line-counts.py
python3 scripts/check_doc_references.py
```

Before pushing, run the required repository gate:

```bash
. .venv/bin/activate
ruff check --fix
make preflight
```

Use the required PR gate only after local preflight passes:

```bash
bash scripts/pr-gate.sh --base main --timeout 1800
```

## Completion Criteria

1. The three giant source modules are deleted and replaced by focused modules
   with clear ownership.
2. Registry identifiers, public class names, availability tiers, parameters,
   payloads, artifacts, warnings, and metrics are behaviorally identical.
3. Feature-selection, validation, and binning have node-level tests at their
   own boundaries rather than only executor coverage.
4. Expected clustering insufficiency remains a successful singleton result;
   unexpected computation errors fail the node.
5. Full test suite, mypy, line-count guard, preflight, and PR CI are green.
