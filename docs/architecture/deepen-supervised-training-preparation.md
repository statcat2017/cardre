# Deepen Supervised Training Preparation

## Purpose

This how-to implementation guide is for an implementation agent. It deepens
supervised training preparation into one module so classifiers, feature
selection, random resampling, and SMOTE share the same rules for:

- modelling metadata and target resolution;
- feature eligibility;
- target exclusion;
- governance/internal-column exclusion;
- binary target construction; and
- row-level sampling provenance.

Today those rules are fragmented. `BaseClassifierNode` uses
`_prepare_training_data`, while filter and embedded feature selection resolve
metadata and features independently. Random resampling and SMOTE each resolve
their own target metadata and claim different sampling facts. This loses
locality: a fix to target leakage or `_is_synthetic_row` requires changing
several modules and callers can observe different behaviour.

The target is a deep module in `cardre/nodes/_training_utils.py`. Its interface
accepts an `ExecutionContext` and returns a typed supervised-training value.
Its implementation owns metadata validation, train-Artifact loading, binary
target construction, and one feature-resolution rule. Callers receive leverage
without learning those details.

## ADR Constraints

This work implements the focused preparation slice of ADR-0007 and preserves
the build/validate model in ADR-0001.

1. Every supervised node resolves target meaning from
   `EvidenceKind.MODELLING_METADATA`, not an optional `target_column` parameter.
2. A missing target definition, missing target column, or single-class train
   Artifact fails closed.
3. Every underscore-prefixed dataframe column is internal. It must never enter
   supervised features, including when callers supply `include_columns`.
4. `_is_synthetic_row` is an immutable row-level provenance fact:
   - `False` for selected original rows;
   - `True` for added duplicate rows from random oversampling;
   - `True` for generated SMOTE rows.
5. Only `train` Artifacts enter the preparation module. No test or OOT Artifact
   is introduced to a fit, selection, or transform node.
6. Do not add a second training-preparation adapter. One module earns the seam;
   its internal helpers are implementation details.
7. ADR-0003 permits removing the feature-selection `target_column` fallback.
   Do not retain compatibility branches for saved experimental plans.

## Scope

Change these production modules:

- `cardre/nodes/_training_utils.py`
- `cardre/nodes/_classifier_base.py`
- `cardre/nodes/feature_selection.py`

Add focused tests in new files:

- `tests/test_supervised_training_preparation.py`
- `tests/test_feature_selection.py`
- `tests/test_training_resampling.py`

If an existing node-level test file already exercises the same node, extend it
instead of creating a duplicate fixture tree. The test names above describe test
ownership, not a requirement to create all three files.

Do not include these separate ADR-0007 concerns in this work item:

- ensemble weight optimisation;
- estimator-family parameter adapters;
- explainability dispatch from model Artifact metadata.

Do not change:

- `cardre/execution/context.py` role enforcement;
- node registry tiers or optional-dependency behaviour;
- Artifact store schemas, database migration, or run lifecycle;
- build/validate stream topology;
- `CONTEXT.md` or ADR text.

## Current Friction Map

| Concern | Current locality | Defect |
| --- | --- | --- |
| Classifier target + binary target | `_training_utils._prepare_training_data` | Good metadata requirement, but feature policy is not reused elsewhere |
| Classifier feature resolution | `_training_utils._resolve_features` | Underscore-prefixed columns can become features |
| Filter selection target | `FeatureSelectionFilterNode.run` | Falls back to `params["target_column"]`; candidate columns include internals |
| Embedded selection target | `FeatureSelectionEmbeddedNode.run` | Falls back to `params["target_column"]`; duplicates numeric feature filtering |
| Random resampling target | `ResampleTrainingDataNode.run` | Metadata is resolved locally; duplicate rows are not marked in the Parquet frame |
| SMOTE target + features | `SmoteTrainingDataNode.run` | Metadata and numeric feature filtering are local; synthetic rows are not marked |

Deleting the current per-node target and feature snippets would not delete the
requirements. They would reappear in every caller. That deletion test shows a
real deepening opportunity: the requirements belong in one preparation module.

## Target Module Shape

File: `cardre/nodes/_training_utils.py`

Add a typed value that represents one validated train Artifact and its target
evidence. It is the interface that callers and tests cross.

```python
@dataclass(frozen=True)
class SupervisedTrainingData:
    """Validated train frame and target evidence for supervised nodes."""

    frame: pl.DataFrame
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    y_binary: np.ndarray
    metadata: Any

    def feature_columns(self, params: Mapping[str, Any]) -> list[str]:
        """Return eligible numeric modelling columns for this train frame."""
        return resolve_supervised_feature_columns(
            self.frame,
            target_column=self.target_column,
            params=params,
        )
```

Add one factory:

```python
def prepare_supervised_training_data(
    context: ExecutionContext,
    *,
    operation: str,
) -> SupervisedTrainingData:
    """Load and validate the train Artifact and modelling metadata."""
```

Its implementation must:

1. call `context.require_train_artifact(operation)`;
2. call `context.target_metadata()`;
3. construct `TargetSpec.from_metadata(meta)`;
4. reject absent target metadata, absent target column, or unknown labels;
5. read the train Artifact through `ArtifactEvidenceReader`;
6. construct `y_binary` with `TargetSpec.encode_binary_strict`;
7. reject zero good or zero bad rows;
8. return immutable target values as `frozenset[str]`.

The module owns target metadata resolution. Individual nodes must not inspect
`params["target_column"]`, `meta.good_values`, or `meta.bad_values` directly.

### Feature Eligibility

Add the one shared feature resolver:

```python
INTERNAL_COLUMN_PREFIX = "_"


def resolve_supervised_feature_columns(
    frame: pl.DataFrame,
    *,
    target_column: str,
    params: Mapping[str, Any],
) -> list[str]:
    """Resolve numeric, non-target, non-internal supervised features."""
```

Required rules, in this order:

1. Read `include_columns` and `exclude_columns` from `params`.
2. Reject requested `include_columns` that do not exist.
3. Reject any requested `include_columns` beginning with `_`. An explicit
   include must not circumvent governance/internal exclusion.
4. Start from `include_columns` if supplied, otherwise all frame columns.
5. Exclude the metadata target column, all explicit excludes, and every
   underscore-prefixed column.
6. Keep only numeric columns.
7. Raise a clear error if no features remain.

Suggested implementation:

```python
def resolve_supervised_feature_columns(
    frame: pl.DataFrame,
    *,
    target_column: str,
    params: Mapping[str, Any],
) -> list[str]:
    include_columns = list(params.get("include_columns", []))
    exclude_columns = set(params.get("exclude_columns", []))

    missing = [column for column in include_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"include_columns references missing columns: {missing}")

    internal_includes = [
        column for column in include_columns
        if column.startswith(INTERNAL_COLUMN_PREFIX)
    ]
    if internal_includes:
        raise ValueError(
            "include_columns must not select internal columns: "
            f"{internal_includes}"
        )

    candidates = include_columns or list(frame.columns)
    excluded = exclude_columns | {target_column}
    features = [
        column
        for column in candidates
        if column not in excluded
        and not column.startswith(INTERNAL_COLUMN_PREFIX)
        and frame.schema[column].is_numeric()
    ]
    if not features:
        raise ValueError("No numeric supervised features available after exclusions")
    return features
```

Do not silently admit a non-numeric column when it is explicitly included. The
current classifier contract rejects it; preserve that constraint with a clear
message after selecting candidates.

### Compatibility of Existing Private Helpers

Replace `_prepare_training_data(...)` with a thin private bridge while all
classifier nodes still consume its tuple shape:

```python
def _prepare_training_data(
    context: ExecutionContext,
    params: Mapping[str, Any],
) -> tuple[pl.DataFrame, list[str], str, set[str], set[str], np.ndarray, Any]:
    prepared = prepare_supervised_training_data(
        context,
        operation="_prepare_training_data",
    )
    return (
        prepared.frame,
        prepared.feature_columns(params),
        prepared.target_column,
        set(prepared.good_values),
        set(prepared.bad_values),
        prepared.y_binary,
        prepared.metadata,
    )
```

This keeps the classifier template's shallow call site stable while moving its
implementation behind the deeper preparation interface. Do not preserve the
dead `_extract_target_metadata(...)` helper if no production caller remains.

## Production Changes

### 1. Deepen `_training_utils.py`

File: `cardre/nodes/_training_utils.py`

1. Import `dataclass` and `Mapping`.
2. Add `SupervisedTrainingData`, `INTERNAL_COLUMN_PREFIX`,
   `prepare_supervised_training_data`, and
   `resolve_supervised_feature_columns`.
3. Remove the old feature resolver after all callers use the new name, or keep
   it as a one-line private delegation during the same implementation commit.
4. Make `_prepare_training_data` a bridge as shown above.
5. Delete `_extract_target_metadata` when the production search confirms it has
   no callers.

Keep Artifact I/O inside `ArtifactEvidenceReader`. The preparation module is
not a new evidence parser or Artifact adapter.

### 2. Keep Classifiers Thin

File: `cardre/nodes/_classifier_base.py`

`BaseClassifierNode.run` already calls `_prepare_training_data`. After the
bridge is in place, it automatically receives metadata-only target resolution
and internal-column exclusion. Do not add classifier-specific copies of the
new rule.

Remove stale comments that say kwargs were "filtered" if the current code now
raises unknown parameters. That concern remains outside this focused work item;
do not redesign estimator-family adapters here.

### 3. Migrate Filter Feature Selection

File: `cardre/nodes/feature_selection.py`

Import the shared preparation module:

```python
from cardre.nodes._training_utils import (
    prepare_supervised_training_data,
    resolve_supervised_feature_columns,
)
```

In `FeatureSelectionFilterNode.run`, replace manual train Artifact loading and
target fallback:

```python
train_art = context.train_artifact()
reader = ArtifactEvidenceReader(store)
df = reader.read_dataframe(train_art)
meta = context.target_metadata()
target_column = meta.target_column if meta is not None else ""
if not target_column:
    target_column = params.get("target_column", "")
```

with:

```python
prepared = prepare_supervised_training_data(
    context,
    operation="feature_selection_filter",
)
df = prepared.frame
target_column = prepared.target_column
train_art = context.require_train_artifact("feature_selection_filter")
numeric_cols = resolve_supervised_feature_columns(
    df,
    target_column=target_column,
    params=params,
)
```

Remove the `params["target_column"]` fallback and its misleading error message.
Use the shared `numeric_cols` as the candidate set for missingness, variance,
IV, and correlation filtering. This prevents an underscore-prefixed governance
column or the target from reaching selection.

### 4. Migrate Embedded Feature Selection

File: `cardre/nodes/feature_selection.py`

In `FeatureSelectionEmbeddedNode.run`, replace local target fallback,
`bad_values` extraction, and `features = [...] numeric` filtering with:

```python
prepared = prepare_supervised_training_data(
    context,
    operation="feature_selection_embedded",
)
df = prepared.frame
target_column = prepared.target_column
features = prepared.feature_columns(params)
y_binary = prepared.y_binary
```

Use `prepared.bad_values` only where the output payload needs target metadata.
Do not rebuild the binary target with `cast(pl.String).is_in(...)`; that is
already preparation implementation.

Remove operational use of `target_column` from the feature-selection parameter
schema/defaults. If a caller supplies the now-unsupported parameter, validation
must report it as unsupported rather than silently using it as a fallback.

### 5. Materialise Random-Resampling Provenance

File: `cardre/nodes/feature_selection.py`

In `ResampleTrainingDataNode.run`, replace local metadata parsing with:

```python
prepared = prepare_supervised_training_data(
    context,
    operation="resample_training_data",
)
df = prepared.frame
target_col = prepared.target_column
y_bin = prepared.y_binary
```

Build rows and flags together. Do not calculate duplicate provenance from
shuffled dataframe values after selection; the index-selection operation is the
only reliable locality for it.

Suggested shape:

```python
base_indices = np.concatenate([bad_indices, good_indices])
extra_bad_indices = (
    rng.choice(bad_indices, size=target_minority - n_bad, replace=True)
    if target_minority > n_bad
    else np.array([], dtype=int)
)

selected_indices = np.concatenate([base_indices, extra_bad_indices])
synthetic_flags = np.concatenate([
    np.zeros(len(base_indices), dtype=bool),
    np.ones(len(extra_bad_indices), dtype=bool),
])
permutation = rng.permutation(len(selected_indices))
resampled_df = df[selected_indices[permutation]].with_columns(
    pl.Series("_is_synthetic_row", synthetic_flags[permutation])
)
```

For under-sampling and no-op resampling, every output row is an original row
and receives `False`. For combined resampling, only extra duplicate rows receive
`True`.

Keep metadata `synthetic_row_column: "_is_synthetic_row"`, but it now describes
a real Parquet column. Include the field in the report's provenance data if the
existing report schema has a suitable location.

### 6. Materialise SMOTE Provenance

File: `cardre/nodes/feature_selection.py`

In `SmoteTrainingDataNode.run`, replace local metadata parsing with
`prepare_supervised_training_data(...)` as above. Use the shared feature
resolver for numeric modelling inputs:

```python
prepared = prepare_supervised_training_data(
    context,
    operation="smote_training_data",
)
df = prepared.frame
target_col = prepared.target_column
feature_cols = prepared.feature_columns(params)
y_binary = prepared.y_binary
```

SMOTE may need non-feature passthrough columns for Artifact fidelity. Compute
them from the frame without treating underscore-prefixed columns as features:

```python
passthrough_cols = [
    column
    for column in df.columns
    if column not in set(feature_cols) | {target_col, "_is_synthetic_row"}
]
```

Always write `_is_synthetic_row`:

```python
original_frame = df.select(feature_cols + [target_col] + passthrough_cols).with_columns(
    pl.lit(False).alias("_is_synthetic_row")
)

if n_synthetic:
    synthetic_frame = synthetic_frame.with_columns(
        pl.lit(True).alias("_is_synthetic_row")
    )
    resampled_df = pl.concat([original_frame, synthetic_frame])
else:
    resampled_df = original_frame
```

The current comment saying the flag is excluded to avoid feature leakage is
obsolete. The preparation module prevents that leakage structurally by excluding
all underscore-prefixed columns from supervised features.

## Test Design

Use real `ProjectStore` fixtures, real Parquet Artifacts, and an
`ExecutionContext` that carries `MODELLING_METADATA`. Do not unit-test the
desired policy by mocking the preparation module; tests must exercise its
interface and the nodes that consume it.

### Shared Preparation Tests

File: `tests/test_supervised_training_preparation.py`

Build a reusable fixture with:

```text
numeric_feature      float
second_feature       int
target               string, good/bad labels
_is_synthetic_row    bool
_governance_marker   int
```

Required cases:

1. Metadata target is excluded even when numeric.
2. `_is_synthetic_row` and `_governance_marker` are excluded by default.
3. `include_columns=["numeric_feature", "_is_synthetic_row"]` raises a clear
   internal-column error.
4. Explicit excludes remove an otherwise eligible feature.
5. Missing modelling metadata raises before a supervised node can fit.
6. Unknown target labels and single-class frames fail closed.
7. `prepare_supervised_training_data` returns the expected binary target and
   metadata target column.

Example:

```python
def test_feature_resolution_excludes_target_and_internal_columns(prepared):
    assert prepared.feature_columns({}) == ["numeric_feature", "second_feature"]


def test_feature_resolution_rejects_internal_explicit_include(prepared):
    with pytest.raises(ValueError, match="internal columns"):
        prepared.feature_columns({"include_columns": ["_is_synthetic_row"]})
```

### Feature-Selection Tests

File: `tests/test_feature_selection.py`

For both filter and embedded nodes:

1. Omit `target_column` from params but provide metadata. Assert the node
   completes and neither the target nor underscore-prefixed columns appears in
   `selected` or the importance map.
2. Omit metadata. Assert a clear missing-target-metadata failure.
3. Supply a conflicting `target_column` parameter. Assert validation rejects it
   or the node ignores it according to the finalized parameter schema; it must
   never replace metadata target meaning.
4. Use a numeric target fixture. Assert it cannot be selected as a feature.

### Random-Resampling Tests

File: `tests/test_training_resampling.py`

Use a deterministic imbalanced train Artifact with an ID column for checking
duplicate provenance.

1. `oversample_minority` produces the advertised `_is_synthetic_row` Parquet
   column.
2. The count of `True` flags equals `synthetic_rows_added` in the report.
3. Every `True` random-resampling row has an ID that exists among original
   minority rows; every original selected row is `False`.
4. `undersample_majority` produces the column with all `False` values.
5. Downstream shared feature resolution excludes the flag.
6. Missing modelling metadata fails before a resampled Artifact is written.

### SMOTE Tests

File: `tests/test_training_resampling.py`

Skip only when the optional imbalance dependency is intentionally absent in the
test environment. When it is available:

1. The output frame always contains `_is_synthetic_row`.
2. First/original rows are `False`; generated rows are `True`.
3. `sum(_is_synthetic_row)` equals `synthetic_count` in the node metrics and
   `synthetic_rows_added` in the report.
4. The shared feature resolver does not include the flag.
5. A missing metadata target fails closed.

## Regression Matrix

| Scenario | Required result |
| --- | --- |
| Classifier train Artifact includes `_is_synthetic_row` | Flag is not a feature |
| Filter selection has numeric target | Target is not selected |
| Embedded selection has numeric target | Target is not selected |
| Any feature-selection node lacks metadata | Clear failure before fitting |
| Explicit include selects `_internal` | Clear validation error |
| Random oversampling adds duplicates | Only added duplicate rows have `True` |
| Under-sampling only | All output flags are `False` |
| SMOTE adds rows | Only generated rows have `True` |
| Resampled Artifact reaches classifier | Provenance flag remains non-feature |

## Verification

Run after implementation:

```bash
. .venv/bin/activate
ruff check cardre/nodes/_training_utils.py cardre/nodes/_classifier_base.py cardre/nodes/feature_selection.py tests/test_supervised_training_preparation.py tests/test_feature_selection.py tests/test_training_resampling.py
pytest tests/test_supervised_training_preparation.py tests/test_feature_selection.py tests/test_training_resampling.py
pytest tests/test_logit_helpers.py tests/test_logistic_regression_validation.py
make preflight
```

If optional SMOTE coverage is skipped locally, run the repository's optional
dependency test environment before opening a PR. Do not remove SMOTE assertions
solely to make a minimal environment pass.

## Review Checklist

- [ ] One preparation module owns metadata target resolution and binary target
  construction.
- [ ] Both feature-selection nodes use metadata only, never a params fallback.
- [ ] Classifiers, selection, random resampling, and SMOTE use shared feature
  eligibility.
- [ ] No underscore-prefixed column can become a supervised feature.
- [ ] Random-resampling duplicate rows and SMOTE-generated rows carry a real
  `_is_synthetic_row=True` Parquet value.
- [ ] Original rows carry `_is_synthetic_row=False`.
- [ ] The report and Artifact metadata match the materialised flag.
- [ ] Ensemble optimisation, estimator adapters, and explainability were not
  changed in this work item.
- [ ] Focused tests, Ruff, and preflight pass.
