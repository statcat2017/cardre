# Cardre Item 3 Finalized Plan: First-Class OptBinning Supervised Binning Path

**Status:** Finalized for review
**Date:** 2026-06-19
**Supersedes scope of:** `docs/plans/optbinning-integration-plan.md` (this plan is the
narrower, codebase-grounded successor focused on the supervised binning path only)
**Baseline assumption:** No legacy plans exist in any store. Backward-compatibility
with persisted `cardre.fine_classing` / `cardre.auto_binning_fit` steps is NOT
required. The read-time migration map in `cardre/store.py:32-35` is kept as
defence-in-depth but is not load-bearing for this phase.

---

## 1. Purpose

Make OptBinning a first-class supervised binning method in Cardre, behaving like a
governed Cardre modelling path:

```
Import → target validation → train/test/OOT split → Binning(method="optbinning")
→ variable/bin inspection → manual review/override → WOE/IV → WOE transform
→ logistic regression → score scaling → validation → audit export
```

Cardre uses OptBinning for supervised bin discovery only. Cardre continues to own:
artifact format, manual overrides, WOE calculation, train/test/OOT apply,
scorecard modelling, validation, audit reporting, scoring export.

---

## 2. Product decision

After this phase, OptBinning is represented as a method of the canonical binning
node (`cardre.binning`), not as a standalone node:

```json
{
  "node_type": "cardre.binning",
  "params": {
    "method": "optbinning",
    "engine": "optbinning",
    "prebinning_method": "cart",
    "solver": "cp",
    "divergence": "iv",
    "max_n_prebins": 20,
    "max_n_bins": 6,
    "min_prebin_size": 0.05,
    "min_bin_size": 0.03,
    "min_bin_n_event": 20,
    "min_bin_n_nonevent": 20,
    "monotonic_trend": "auto",
    "cat_cutoff": 0.01,
    "time_limit": 100,
    "special_codes": {},
    "exclude_columns": []
  }
}
```

`cardre.auto_binning_fit` remains registered and executable (delegated by
`BinningNode._run_optbinning`) but is hidden from the node picker as an
`is_internal` node.

---

## 3. Scope

### In scope

1. Canonical OptBinning path cleanup (single visible path).
2. Default pathway switch from `cardre.fine_classing` to `cardre.binning`.
3. Richer Cardre-native OptBinning artifacts (bin metrics, variable summary, manifest).
4. Variable-level summary artifact (Parquet).
5. Structured warnings with stable codes.
6. Train-only leakage guard (explicit + tested).
7. Manual binning source generalisation (the highest-risk integration point).
8. WOE/IV and WOE transform compatibility.
9. End-to-end demo pathway through logistic regression.
10. Regression, contract, and optional-dependency tests.
11. Audit-ready metadata for later report generation.

### Out of scope (do not implement this phase)

- BinningEngine protocol / FrozenBinningSpec abstraction.
- OptBinning Scorecard node.
- OptBinning BinningProcess integration.
- Parallel variable fitting.
- 2D optimal binning, continuous-target binning, multiclass binning.
- Large-data sketch binning.
- Direct use of optbinning transform in scoring/export.
- Full solver/constraint surface.

---

## 4. Architectural principles

### 4.1 Cardre owns the workflow

OptBinning may suggest bins; Cardre owns the bins once persisted.

- OptBinning object state is NOT the scoring source of truth.
- Cardre JSON artifacts ARE the scoring source of truth.
- Manual edits operate on Cardre artifacts.
- Apply/score/export do NOT require optbinning installed.

### 4.2 No new execution system

This phase must not modify `PlanExecutor` scheduling, artifact reuse, staleness,
cancellation, branch execution, or run manifests except where artifact metadata
naturally flows through existing mechanisms. All parameter changes continue to use
`StepSpec.params`, `params_hash`, `PlanService.update_params`, existing staleness
logic, existing run execution. This directly respects ADR 0002.

### 4.3 No duplicate visible OptBinning paths

The user sees one OptBinning option: `Binning → Method → OptBinning`. They do NOT
see `Fine classing`, `AutoBinningFitNode`, and `BinningNode(method=optbinning)` as
separate competing node choices.

---

## 5. Current implementation baseline (verified against codebase)

### Verified current state

| Module | Status |
|---|---|
| `cardre/engine/binning/optbinning_adapter.py` | Per-variable `OptimalBinning` adapter; `VariableBinningResult` has `variable/dtype/status/bins/warnings` only. |
| `cardre/engine/binning/capabilities.py` | Detects optbinning availability + version; emits install hint. |
| `cardre/engine/binning/diagnostics.py` | `BinningDiagnostic` dataclass with `variable/diagnostic_type/message/details`; `check_solver_status`, `check_too_few_bins`, `check_sparse_bins`, `check_variable_failed`, `run_all`. |
| `cardre/nodes/build/auto_binning_fit.py` | Produces bin-definition + manifest artifacts; validates engine/solver/etc; resolves train via `next(a for a in … if a.role=="train")` (no explicit guard). |
| `cardre/nodes/build/binning.py` | `BinningNode` dispatches by `params["method"]`; delegates with `dataclasses.replace` (no context mutation); pops `method` before delegation. |
| `cardre/nodes/build/bins.py` | `FineClassingNode` + `ManualBinningNode`. `ManualBinningNode.run` is ALREADY source-agnostic (picks bin artifact by content: `"variables" in payload and "selected" not in payload`). |
| `sidecar/routes/binning.py` | `GET /binning/engines` returns optbinning + quantile engines. |
| `cardre/services/manual_binning_service.py` | Hardcoded to canonical `"fine-classing"` (11 references); staleness lookup keyed on `fc_actual_id`. |
| `cardre/services/step_topology.py` | `find_nearest_ancestor_by_canonical_step_id` raises `AmbiguousBranchAncestorError` on ties. |
| `cardre/registry.py` | Registers both `BinningNode` and `AutoBinningFitNode`. |
| `cardre/store.py:32-35` | Read-time `_LEGACY_NODE_TYPE_METHOD` map (kept as defence-in-depth). |
| `sidecar/proof_pathway.py:83` | Default `SCORECARD_PATHWAY` emits `cardre.fine_classing` with `canonical_step_id="fine-classing"`. |
| `sidecar/routes/node_types.py:133-140` | Special-cases `cardre.auto_binning_fit` in `_MODEL_FAMILIES`. |
| `cardre/audit.py:111` | `NodeType` ABC has `node_type/version/category/input_roles/output_roles`; no `is_internal` flag yet. |
| `cardre/node_parameters.py:49` | `MethodOption` has `id/label/status/params/description`; no `unavailable_reason`. |
| `tests/test_optbinning.py` | 1037 lines; already on `check-line-counts.py` allowlist. |
| `pyproject.toml` | `optimal-binning = ["optbinning==0.21.0"]` extra; `optional_binning` pytest marker registered. |
| `.github/workflows/ci.yml:95` | `check-api-contracts` = `generate-openapi-types.py` + `git diff --exit-code frontend/src/api/schema.d.ts`. |

### Key implications

- `ManualBinningNode` downstream is already source-agnostic → PR 69 blast radius
  is confined to `ManualBinningService` + DTOs + sidecar models.
- `check-api-contracts` requires `schema.d.ts` regen on EVERY sidecar model
  change. This is an explicit step in every PR below.
- `tests/test_optbinning.py` is allowlisted for line counts, so PR 68 test
  additions there will not trip `check-line-counts.py`.

---

## 6. Target architecture

### 6.1 Public node

Public modelling path: `cardre.binning`.

Supported methods:

| Method | Status |
|---|---|
| `fine_classing` | available |
| `optbinning` | available if dependency installed |
| `chi_merge` | coming_soon |
| `tree_binning` | coming_soon |

### 6.2 Internal implementation

`BinningNode.run()` dispatches internally:

```python
if method == "fine_classing":
    delegate to FineClassingNode using copied context (method stripped)
elif method == "optbinning":
    delegate to AutoBinningFitNode using copied context (method stripped)
else:
    raise validation error
```

`method` remains persisted in the outer step params and execution context. The
delegated context receives a filtered copy (already implemented via
`dataclasses.replace`); the original context is not mutated (tested at
`test_optbinning.py:645`).

### 6.3 Artifact strategy

For OptBinning, the canonical node produces:

1. **Bin definition artifact** (JSON) — used downstream.
2. **Variable summary artifact** (Parquet) — supports UI/reporting/branch comparison.
3. **Engine manifest artifact** (JSON) — secondary evidence.

---

## 7. Artifact specification

### 7.1 Bin definition artifact

Metadata:
```json
{"artifact_type": "definition", "role": "definition", "media_type": "application/json"}
```

Payload shape:
```json
{
  "schema_version": "cardre.bin_definition.v1",
  "source": {
    "method": "optbinning",
    "engine": "optbinning",
    "engine_version": "0.21.0",
    "node_id": "binning",
    "step_id": "binning",
    "fit_sample_role": "train",
    "train_artifact_id": "artifact_train_123",
    "train_physical_hash": "...",
    "train_logical_hash": "...",
    "target_column": "bad_flag",
    "good_values": ["0"],
    "bad_values": ["1"],
    "params": { "...": "..." }
  },
  "variables": [
    {
      "variable": "age",
      "dtype": "numerical",
      "kind": "numeric",
      "status": "OPTIMAL",
      "active": true,
      "metrics": {
        "iv": 0.142,
        "js": 0.018,
        "n_bins": 5,
        "row_count": 10000,
        "missing_count": 120,
        "missing_rate": 0.012,
        "monotonic_woe": true,
        "min_bin_count": 500,
        "max_bin_pct": 0.32
      },
      "bins": [
        {
          "bin_id": "age_bin_001",
          "label": "(-inf, 25.5)",
          "kind": "numeric",
          "lower": null,
          "upper": 25.5,
          "lower_inclusive": false,
          "upper_inclusive": false,
          "categories": null,
          "is_missing_bin": false,
          "is_special_bin": false,
          "row_count": 1234,
          "row_pct": 0.1234,
          "good_count": 1076,
          "bad_count": 158,
          "bad_rate": 0.128,
          "woe": -0.391,
          "iv": 0.012
        }
      ],
      "warnings": []
    }
  ],
  "rejected": [],
  "warnings": [
    {
      "code": "SPARSE_BIN",
      "severity": "warning",
      "variable": "age",
      "bin_id": "age_bin_001",
      "message": "Bin has fewer bads than configured minimum.",
      "requires_acknowledgement": true,
      "details": {"bad_count": 8, "minimum": 20}
    }
  ]
}
```

**Compatibility rule (additive only):** existing downstream code reads
`variables[*].variable`, `variables[*].kind`, `variables[*].bins`,
`bins[*].bin_id`, `bins[*].label`, `bins[*].lower`, `bins[*].upper`,
`bins[*].categories`, `bins[*].is_missing_bin`, `bins[*].row_count`,
`bins[*].good_count`, `bins[*].bad_count`. New fields (`row_pct`, `bad_rate`,
`woe`, `iv`, `metrics`, `status`, `active`, `warnings`, `source.*`) are additive.

**`rejected` standardisation:** always emit a list (`[]` when empty), never
`null`. Current `auto_binning_fit.py:325` emits `None` — fix to `[]`.

### 7.2 Variable summary artifact (Parquet — confirmed)

Metadata:
```json
{"artifact_type": "report", "role": "report", "media_type": "application/vnd.apache.parquet"}
```

**Decision: Parquet** (not JSON). Rationale: flat columnar shape is ideal for
branch comparison and the UI variable sidebar later; the column set is small but
row-oriented access patterns favour Parquet. A production Parquet writer helper
does not yet exist in `cardre/nodes` (only `tests/helpers._make_parquet_report`)
— PR 68 adds one.

Columns:

| Column | Type |
|---|---|
| `variable` | string |
| `dtype` | string |
| `kind` | string |
| `status` | string |
| `active` | boolean |
| `iv` | float |
| `js` | float \| null |
| `n_bins` | integer |
| `row_count` | integer |
| `missing_count` | integer |
| `missing_rate` | float |
| `min_bin_count` | integer |
| `max_bin_pct` | float |
| `monotonic_woe` | boolean \| null |
| `warning_count` | integer |
| `failure_reason` | string \| null |

### 7.3 Engine manifest artifact

Metadata:
```json
{"artifact_type": "report", "role": "report", "media_type": "application/json"}
```

Payload:
```json
{
  "engine": "optbinning",
  "engine_version": "0.21.0",
  "cardre_node_type": "cardre.binning",
  "method": "optbinning",
  "fit_sample_role": "train",
  "train_artifact_id": "...",
  "target_column": "bad_flag",
  "good_values": ["0"],
  "bad_values": ["1"],
  "parameters": {},
  "variable_count": 128,
  "variables_succeeded": 121,
  "variables_failed": 7,
  "succeeded": ["age", "income"],
  "failed": ["postcode_region"],
  "warnings_count": 12
}
```

---

## 8. Warning specification

### 8.1 Reshaped `BinningDiagnostic` (BREAKING internal change)

**Current** (`diagnostics.py:15`):
```python
@dataclass(frozen=True)
class BinningDiagnostic:
    variable: str
    diagnostic_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
```

**Target**:
```python
@dataclass(frozen=True)
class BinningDiagnostic:
    code: str
    severity: str            # "info" | "warning" | "error"
    variable: str | None = None
    bin_id: str | None = None
    message: str = ""
    requires_acknowledgement: bool = False
    details: dict[str, Any] = field(default_factory=dict)
```

### 8.2 `diagnostic_type` → `code` migration map

| Old `diagnostic_type` | New `code` | Severity |
|---|---|---|
| `solver_not_optimal` | `SOLVER_NOT_OPTIMAL` | warning |
| `solver_feasible_not_optimal` | `SOLVER_NOT_OPTIMAL` | info |
| `too_few_bins` | `TOO_FEW_BINS` | warning |
| `sparse_bin` | `SPARSE_BIN` | warning |
| `variable_failed` | `VARIABLE_FAILED` | error |

### 8.3 New codes for this phase

`SOLVER_NOT_OPTIMAL`, `VARIABLE_FAILED`, `TOO_FEW_BINS`, `SPARSE_BIN`,
`PURE_BIN_RISK`, `NON_MONOTONIC_WOE`, `MISSING_HIGH_RISK`, `SPECIAL_HIGH_RISK`,
`HIGH_CARDINALITY_CATEGORICAL`, `DOMINANT_BIN`, `ALL_MISSING_OR_CONSTANT`,
`UNKNOWN_CATEGORY_POLICY`.

### 8.4 Callers to update on reshape

1. All `check_*` functions in `diagnostics.py` (`check_solver_status`,
   `check_too_few_bins`, `check_sparse_bins`, `check_variable_failed`) —
   rewrite to construct with `code`/`severity` instead of `diagnostic_type`.
2. `run_all` in `diagnostics.py` — unchanged signature, but returned objects
   have new fields.
3. `auto_binning_fit.py:288-293` warning-building loop — reads `d.variable`,
   `d.message`, `d.diagnostic_type`; rewrite to read `d.code`, `d.severity`,
   `d.variable`, `d.bin_id`, `d.message`, `d.requires_acknowledgement`,
   `d.details`.
4. `test_optbinning.py:896-955` (`TestDiagnostics`) — assertions on
   `.diagnostic_type` rewrite to `.code`.

### 8.5 Acceptance

- No free-text-only warnings in OptBinning artifacts.
- Every warning has a stable `code`.
- Every variable-level warning has a `variable`.
- Every bin-level warning has a `bin_id` where possible.
- Report generation can include warnings without parsing strings.

---

## 9. Parameter specification

### 9.1 User-facing OptBinning parameters

**Basic:** `max_n_bins`, `min_bin_size`, `min_bin_n_event`, `min_bin_n_nonevent`,
`monotonic_trend`, `cat_cutoff`, `time_limit`, `exclude_columns`, `special_codes`.

**Advanced:** `solver`, `divergence`, `max_n_prebins`, `min_prebin_size`.

**Hidden/internal:** `engine`, `method`, `prebinning_method`.

For MVP: `prebinning_method = cart` only; `solver ∈ {cp, mip}`;
`divergence ∈ {iv, js, hellinger}`;
`monotonic_trend ∈ {auto, none, ascending, descending}`.

### 9.2 Defaults (conservative)

```json
{
  "method": "optbinning",
  "engine": "optbinning",
  "prebinning_method": "cart",
  "solver": "cp",
  "divergence": "iv",
  "max_n_prebins": 20,
  "min_prebin_size": 0.05,
  "max_n_bins": 6,
  "min_bin_size": 0.03,
  "min_bin_n_event": 20,
  "min_bin_n_nonevent": 20,
  "monotonic_trend": "auto",
  "cat_cutoff": 0.01,
  "time_limit": 100,
  "special_codes": {},
  "exclude_columns": []
}
```

### 9.3 Validation rules (server-side rejects)

- missing/unknown `method`
- `method != optbinning` for this method branch
- `engine != optbinning`
- `prebinning_method != cart` (quantile removed — no legacy plans)
- `solver ∉ {cp, mip}`
- `divergence ∉ {iv, js, hellinger}`
- `max_n_prebins < 1`
- `max_n_bins < 1`
- `min_prebin_size <= 0 or >= 1`
- `min_bin_size <= 0 or >= 1`
- `min_bin_n_event < 1`
- `min_bin_n_nonevent < 1`
- `cat_cutoff <= 0 or >= 1`
- `time_limit < 1`
- `special_codes` not object/dict
- `exclude_columns` not list

---

## 10. Train-only leakage guard

### Implementation

Replace `auto_binning_fit.py:234`:
```python
train_artifact = next(a for a in context.input_artifacts if a.role == "train")
```
with an explicit resolver:

```python
def _resolve_train_input(context: ExecutionContext) -> ArtifactRef:
    train_artifacts = [a for a in context.input_artifacts if a.role == "train"]
    if len(train_artifacts) != 1:
        raise ValueError(
            f"OptBinning requires exactly one train artifact, found {len(train_artifacts)}."
        )
    return train_artifacts[0]
```

### Additional checks

- Reject if only full/test/OOT artifacts are present (covered by the `!= 1` guard).
- Record `fit_sample_role = "train"` in bin definition `source`.
- Record `train_artifact_id`, `train_logical_hash`, `train_physical_hash` in `source`.
- Record `target_column`, `good_values`, `bad_values` in `source`.

### Tests

- `test_optbinning_requires_train_artifact`
- `test_optbinning_rejects_test_only_artifact`
- `test_optbinning_records_train_hash_and_target_metadata`
- `test_optbinning_manifest_records_train_artifact`
- `test_optbinning_manifest_records_target_mapping`

---

## 11. Adapter changes (`cardre/engine/binning/optbinning_adapter.py`)

### 11.1 Extend `VariableBinningResult`

From:
```python
@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str
    bins: list[dict[str, Any]]
    warnings: list[str]
```

To:
```python
@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str
    bins: list[dict[str, Any]]
    warnings: list[dict[str, Any]]   # was list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    splits: list[Any] = field(default_factory=list)
    raw_engine_payload: dict[str, Any] | None = None
    failure_reason: str | None = None
```

### 11.2 Extract richer bin metrics

From `optb.binning_table.build()`, extract per-bin:

| OptBinning column | Cardre field |
|---|---|
| `Count` | `row_count` |
| `Event` | `bad_count` |
| `Non-event` | `good_count` |
| `Event rate` | `bad_rate` |
| `WoE` | `woe` |
| `IV` | `iv` |
| `JS` (where available) | `js` |

Also compute `row_pct = row_count / total_row_count`.

### 11.3 Extract variable metrics

For each variable: `n_bins`, `iv`, `js`, `row_count`, `missing_count`,
`missing_rate`, `min_bin_count`, `max_bin_pct`, `monotonic_woe`.

### 11.4 Capture raw engine payload safely

```python
try:
    raw_engine_payload = optb.to_dict()
except Exception:
    raw_engine_payload = None
```

Do NOT rely on this payload for downstream scoring.

---

## 12. Node changes

### 12.1 `BinningNode` (`cardre/nodes/build/binning.py`)

- Remains public/canonical node.
- Exposes OptBinning through `parameter_schema()` (already done).
- Preserves `params.method` in outer context (already done + tested).
- Delegates with copied filtered context (already done via `replace`).
- No direct mutation of `context.validated_params` (already tested).
- No `quantile` in OptBinning path (already enforced: `prebinning_method` enum
  is `["cart"]` only at `binning.py:127`).

### 12.2 `AutoBinningFitNode` (`cardre/nodes/build/auto_binning_fit.py`)

- Mark `is_internal = True` (new class attr on `NodeType`).
- Remove `quantile` from `VALID_PREBINNING` (currently `{"cart", "quantile"}`)
  → `{"cart"}`.
- Remove `quantile` from `prebinning_method` schema enum (currently
  `enum_values=["cart", "quantile"]`) → `["cart"]`.
- Remove `quantile` handling from `_build_params` (it passes through
  `prebinning_method` verbatim, so no explicit branch — just the enum change).
- Replace train resolution with explicit `_resolve_train_input` helper.
- Produce three artifacts: bin definition, variable summary (Parquet), manifest.
- Write structured warnings (new `BinningDiagnostic` shape).
- Include rich bin metrics.
- Standardise `rejected` to `[]`.

### 12.3 Node registry (`cardre/registry.py`)

- Keep `AutoBinningFitNode` registered (needed for `BinningNode._run_optbinning`
  delegation).
- `NodeType` gains class attributes:

```python
class NodeType(ABC):
    is_internal: bool = False
    is_deprecated: bool = False
    replacement_node_type: str | None = None
    ...
```

- `AutoBinningFitNode` sets `is_internal = True`.

---

## 13. Manual binning compatibility (highest-risk integration point)

### 13.1 Current issue

`ManualBinningService` resolves source bins by looking for the nearest ancestor
with `canonical_step_id == "fine-classing"` (11 references at lines 84, 87, 94,
119, 136, 141, 155, 182, 185, 226, 248, 274, 291). After the default pathway
switches to `cardre.binning` with `canonical_step_id="binning"`, this lookup
fails.

### 13.2 New source resolution rule

Add a helper in `step_topology.py` (or `manual_binning_service.py`):

```python
BINNING_SOURCE_CANONICAL_IDS = ["binning", "fine-classing"]

def find_nearest_binning_source(
    steps: list[StepSpec],
    step_id: str,
    branch_step_map: list[dict],
) -> StepSpec | None:
    for canonical in BINNING_SOURCE_CANONICAL_IDS:
        try:
            spec = find_nearest_ancestor_by_canonical_step_id(
                steps, step_id, branch_step_map, canonical,
            )
            if spec is not None:
                return spec
        except AmbiguousBranchAncestorError:
            continue
    return None
```

Keeping `"fine-classing"` as a second entry is harmless safety (defence-in-depth,
mirrors the kept `_LEGACY_NODE_TYPE_METHOD` map). Catch
`AmbiguousBranchAncestorError` per-canonical and continue; surface only if all
candidates fail.

### 13.3 `ManualBinningService` generalisation

- Replace all 11 `"fine-classing"` references with `find_nearest_binning_source`.
- **Staleness path** (lines 98-106): generalise from `fc_actual_id` to the
  resolved binning source step id. Currently:
  ```python
  fc_stale = staleness.get(fc_actual_id, True)
  ```
  becomes:
  ```python
  bin_stale = staleness.get(bin_actual_id, True)
  ```
- Rename `_resolve_upstream_defs` parameters `fc_step_id`/`fc_def`/`fc_artifact_id`
  → `bin_step_id`/`bin_def`/`bin_artifact_id`.
- Update error messages (lines 94, 119, 136, 274, 291) from "fine-classing" to
  generic "binning".

### 13.4 `ManualBinningSourceInfo` rename (both DTOs)

Since no legacy plans exist, rename cleanly (no additive compat needed):

**`cardre/services/plan_dto.py:44`:**
```python
@dataclass
class ManualBinningSourceInfo:
    binning_step_id: str
    binning_artifact_id: str
    binning_method: str
    variable_selection_step_id: str
    variable_selection_artifact_id: str
```

**`sidecar/models.py:265`:** mirror the rename in the Pydantic model.

### 13.5 `ManualBinningEditorStateResponse`

Add `binning_method` to the response so the UI can show "Source method: Fine
classing / OptBinning".

### 13.6 Preview/validation

`ManualBinningNode.run` (bins.py:497-509) is already source-agnostic (picks bin
artifact by content, not canonical step). No changes needed there.
`validate_manual_binning_overrides` and `apply_manual_binning_overrides` operate
on bin dicts regardless of source. No changes needed.

### 13.7 Acceptance

- `ManualBinningService` detects `cardre.binning` as source.
- `ManualBinningService` still detects `fine-classing` as source (via the second
  canonical id in the list — defence-in-depth).
- Manual editor shows selected OptBinning variables.
- No-overrides preview works.
- Merge override preview works for numeric OptBinning bins.
- Manual editor state includes `binning_method = "optbinning"`.

---

## 14. WOE/IV compatibility

OptBinning output must remain compatible with `CalculateWoeIvNode`,
`WoeTransformTrainNode`, `ApplyWoeMappingNode`, `LogisticRegressionNode`.

Acceptance path:
```
Binning(method=optbinning) → CalculateWoeIvNode → ManualBinningNode
→ WoeTransformTrainNode → LogisticRegressionNode
```

The apply/scoring path must not import optbinning (already tested at
`test_optbinning.py:866` — extend in PR 70).

---

## 15. Default pathway switch (`sidecar/proof_pathway.py`)

### 15.1 Change

`proof_pathway.py:83`:
```python
PathwayStepSpec("fine-classing", "cardre.fine_classing", category="fit",
    params={"max_bins": 20, "min_bin_fraction": 0.05,
            "missing_policy": "separate_bin", "max_categorical_levels": 50,
            "exclude_columns": []},
    parent_step_ids=["explicit-missing-outlier-treatment", "define-metadata"]),
```
becomes:
```python
PathwayStepSpec("binning", "cardre.binning", category="fit",
    params={"method": "fine_classing", "max_bins": 20, "min_bin_fraction": 0.05,
            "missing_policy": "separate_bin", "max_categorical_levels": 50,
            "exclude_columns": []},
    parent_step_ids=["explicit-missing-outlier-treatment", "define-metadata"]),
```

`canonical_step_id` defaults to `step_id` → `"binning"`.

### 15.2 Downstream `parent_step_ids` updates

All references to `"fine-classing"` in `parent_step_ids` within
`proof_pathway.py` change to `"binning"`:
- Line 92: `initial-woe-iv` parents
- Line 104: `manual-binning` parents
- Line 152: `technical-manifest-stub` parents

### 15.3 `_MODEL_FAMILIES` cleanup

`sidecar/routes/node_types.py:133-140`: remove the `cardre.auto_binning_fit`
entry (it's hidden via `is_internal` now). Optionally add a `cardre.binning`
entry with description "Canonical binning node supporting Fine Classing and
OptBinning methods."

---

## 16. API changes

### 16.1 Binning engines endpoint

`GET /binning/engines` — current response is sufficient. Add `reason` field to
`BinningEngineInfo` for unavailable engines:

```json
{
  "engines": [
    {
      "id": "optbinning",
      "label": "Optimal binning",
      "available": false,
      "version": null,
      "target_types": ["binary"],
      "reason": "optbinning package not installed. Install with: pip install cardre[optimal-binning]"
    },
    {
      "id": "quantile",
      "label": "Quantile binning (fine classing)",
      "available": true,
      "target_types": ["binary"]
    }
  ]
}
```

`capabilities.py` already emits `reason`; `sidecar/routes/binning.py` just needs
to pass it through. Add `reason: str | None = None` to `BinningEngineInfo` in
`sidecar/models.py`.

### 16.2 Node-types endpoint

`GET /node-types` filters out `is_internal` nodes (so `AutoBinningFitNode`
disappears from the picker).

`GET /node-types/{node_type}/schema` returns `cardre.binning` with method
options `fine_classing`, `optbinning`, `chi_merge` (coming_soon),
`tree_binning` (coming_soon).

If optbinning is not installed, prefer **Option B**: expose method `status =
"unavailable"` with `unavailable_reason`. Add to `MethodOption`:
```python
unavailable_reason: str = ""
```
Do not block this phase on it unless the UI needs it; Option A (status=available,
validation fails at run with install message) is acceptable for MVP.

### 16.3 `schema.d.ts` regen (REQUIRED for every sidecar model change)

Every PR that touches `sidecar/models.py` or any Pydantic model surfaced through
OpenAPI MUST run:
```bash
python3 scripts/generate-openapi-types.py
git add frontend/src/api/schema.d.ts
```
This is the `check-api-contracts` CI gate (`.github/workflows/ci.yml:95`).
Forgetting it fails CI with `git diff --exit-code` on the generated file.

---

## 17. UI changes

### 17.1 Parameter panel

Schema-driven editor is sufficient for basic configuration. For OptBinning show
basic + advanced fields (grouping can come later if the renderer doesn't support
it).

### 17.2 Manual binning editor

Editor is source-agnostic. Add display metadata: source method, engine version,
variable solver status, warnings count.

### 17.3 Variable summary view

Not a full UI screen this phase; expose enough data for a later sidebar:
variable, IV, status, warnings, active/rejected.

---

## 18. Testing plan

### 18.1 Unit tests (`tests/test_optbinning.py` — allowlisted for line counts)

**PR 67:**
- `test_binning_node_optbinning_rejects_quantile`
- `test_autobinning_hidden_from_node_types`
- `test_optbinning_requires_train_artifact`
- `test_optbinning_rejects_test_only_artifact`
- `test_default_pathway_uses_cardre_binning`
- `test_optbinning_context_method_preserved` (already exists at line 645 — verify
  still passes)

**PR 68:**
- `test_optbinning_bin_artifact_has_rich_metrics`
- `test_optbinning_variable_summary_artifact_written`
- `test_optbinning_warnings_have_codes`
- `test_optbinning_failed_variable_goes_to_rejected`
- `test_optbinning_records_train_hash_and_target_metadata`
- `test_diagnostics_use_new_code_field` (rewrite existing `TestDiagnostics`)

**PR 70:**
- `test_optbinning_pathway_to_logistic_regression`
- `test_apply_path_has_no_optbinning_import` (already exists at line 866 — extend)

### 18.2 Manual binning tests (new file or `tests/test_manual_binning_source.py`)

**PR 69:**
- `test_manual_binning_detects_cardre_binning_source`
- `test_manual_binning_still_detects_fine_classing_source` (defence-in-depth)
- `test_manual_binning_preview_works_with_optbinning_bins`
- `test_manual_binning_validation_works_with_optbinning_bins`
- `test_manual_binning_state_includes_binning_method`
- `test_manual_binning_staleness_uses_binning_source_step`

### 18.3 Pipeline tests

`test_optbinning_pathway_to_logistic_regression`:
```
Import fixture → Validate target → Split sample → Binning(method=optbinning)
→ Calculate WOE/IV → Manual binning (no overrides) → WOE transform train
→ Logistic regression
```
Acceptance: all nodes succeed; WOE columns produced; LR model artifact
produced; no downstream node imports optbinning.

### 18.4 Existing test updates

Tests that assert `canonical_step_id == "fine-classing"` or reference the
`fine-classing` step in `proof_pathway`-derived plans must update to `"binning"`:
- `tests/test_sidecar_api.py` (lines 637, 646, 680, 686, 706, 1158, 1165, 1300,
  1307, 1309, 1312, 1317, 1405, 1468, 1470, 1495, 1504)
- `tests/test_binning.py` (lines 88, 150, 272, 517)
- `tests/test_scorecard_model.py` (lines 157, 181, 211, 246, 274, 528)
- `tests/test_audit.py` (lines 181, 212)
- `tests/test_woe.py` (line 137)
- `tests/test_acceptance_generic_pipeline.py` (lines 114, 155, 162)
- `tests/golden_scorecard/test_german_credit_statistical_pipeline.py` (line 119)

These are mechanical `fine-classing`→`binning` renames + `cardre.fine_classing`
→`cardre.binning` node_type + adding `"method": "fine_classing"` to params.

### 18.5 Optional dependency tests

CI without OptBinning installed:
- app imports successfully
- `/binning/engines` reports unavailable with reason
- OptBinning validation gives useful error
- non-OptBinning pipeline still works

CI with OptBinning installed (`pytest -m optional_binning`):
- adapter fit tests pass
- manifest has version + counts
- failed variable doesn't crash others

---

## 19. PR breakdown

### PR 67 — Canonical OptBinning cleanup

**Goal:** Make `cardre.binning(method="optbinning")` the single visible
OptBinning path; switch default pathway to `cardre.binning`.

**Changes:**
1. Add `is_internal`/`is_deprecated`/`replacement_node_type` class attrs to
   `NodeType` (`cardre/audit.py:111`).
2. Set `is_internal = True` on `AutoBinningFitNode`.
3. Filter `is_internal` nodes out of `list_node_types`
   (`sidecar/routes/node_types.py:148`).
4. Remove `cardre.auto_binning_fit` from `_MODEL_FAMILIES`
   (`sidecar/routes/node_types.py:133-140`).
5. Remove `quantile` from `AutoBinningFitNode.VALID_PREBINNING` and schema enum.
6. Add `_resolve_train_input` helper to `AutoBinningFitNode`; replace line 234.
7. Switch `proof_pathway.py:83` to `cardre.binning` with `method=fine_classing`;
   update all `parent_step_ids` (lines 92, 104, 152).
8. Update all existing tests referencing `fine-classing` step/pathway
   (§18.4 list).
9. Regen `schema.d.ts` (if `NodeTypeItem` or list response shape changes).
10. Add tests: `test_binning_node_optbinning_rejects_quantile`,
    `test_autobinning_hidden_from_node_types`,
    `test_optbinning_requires_train_artifact`,
    `test_optbinning_rejects_test_only_artifact`,
    `test_default_pathway_uses_cardre_binning`.

**Acceptance:**
- `/node-types` does not list `cardre.auto_binning_fit`.
- Default pathway uses `cardre.binning` with `canonical_step_id="binning"`.
- `quantile` rejected by OptBinning validation.
- OptBinning without train artifact raises clear error.
- CI green; `check-api-contracts` green; `check-line-counts` green.
- All existing pathway tests pass with updated step ids.

### PR 68 — Rich OptBinning artifacts

**Goal:** Make OptBinning output audit-ready and UI-friendly.

**Changes:**
1. Reshape `BinningDiagnostic` (`diagnostics.py:15`) per §8.1.
2. Update all `check_*` functions + `run_all` per §8.2.
3. Update `auto_binning_fit.py:288-293` warning builder for new diagnostic shape.
4. Extend `VariableBinningResult` with `metrics`/`splits`/`raw_engine_payload`/
   `failure_reason`.
5. Extract per-bin `woe`/`iv`/`bad_rate`/`row_pct` in `_extract_bins`.
6. Extract per-variable metrics in adapter.
7. Add production Parquet writer helper (e.g. `cardre/artifacts.py` or
   `cardre/nodes/_parquet.py`).
8. Write variable summary Parquet artifact in `AutoBinningFitNode.run`.
9. Extend engine manifest (target, train artifact, counts, warnings).
10. Record `fit_sample_role`/`train_artifact_id`/`train_*_hash`/`target_*` in
    bin definition `source`.
11. Standardise `rejected` to `[]` (fix `auto_binning_fit.py:325`).
12. Update `TestDiagnostics` in `test_optbinning.py` for new `code` field.
13. Add `reason` to `BinningEngineInfo` (`sidecar/models.py`); pass through in
    `sidecar/routes/binning.py`.
14. Regen `schema.d.ts`.
15. Add tests per §18.1 PR 68 list.

**Acceptance:**
- Bin definition has rich bin metrics (`woe`, `iv`, `bad_rate`, `row_pct`).
- Variable summary Parquet artifact exists with all §7.2 columns.
- Engine manifest includes version, params, target, counts.
- Warnings have stable `code` + `severity` (no `diagnostic_type`).
- `rejected` is always a list.
- Existing WOE/IV and WOE transform tests still pass.
- CI green; `check-api-contracts` green; `check-line-counts` green.

### PR 69 — Manual binning source generalisation

**Goal:** Manual binning consumes either `fine-classing` or `binning` (OptBinning)
source bins.

**Changes:**
1. Add `find_nearest_binning_source` to `step_topology.py` (catch
   `AmbiguousBranchAncestorError` per canonical).
2. Generalise `ManualBinningService`: replace 11 `"fine-classing"` references
   with `find_nearest_binning_source`.
3. Generalise staleness lookup from `fc_actual_id` to resolved binning source
   step id (lines 98-106).
4. Rename `_resolve_upstream_defs` params `fc_*`→`bin_*`.
5. Rename `ManualBinningSourceInfo` fields in `plan_dto.py:44` and
   `sidecar/models.py:265` to `binning_step_id`/`binning_artifact_id`/
   `binning_method`.
6. Add `binning_method` to `ManualBinningEditorStateResponse`.
7. Update error messages to generic "binning".
8. Regen `schema.d.ts`.
9. Add tests per §18.2.

**Acceptance:**
- `ManualBinningService` detects `cardre.binning` (canonical `"binning"`) as
  source.
- `ManualBinningService` still detects `"fine-classing"` as source
  (defence-in-depth).
- OptBinning source bins appear in manual binning editor state.
- No-overrides preview works with OptBinning source.
- Merge override preview works for numeric OptBinning bins.
- Manual editor state includes `binning_method = "optbinning"`.
- Staleness lookup uses resolved binning source step id.
- CI green; `check-api-contracts` green; `check-line-counts` green.

### PR 70 — End-to-end OptBinning demo path

**Goal:** Make the OptBinning path demo-ready.

**Changes:**
1. Add fixture or German Credit demo pathway variant using
   `Binning(method=optbinning)`.
2. Add integration test `test_optbinning_pathway_to_logistic_regression`.
3. Extend `test_apply_path_has_no_optbinning_import` (already at
   `test_optbinning.py:866`).
4. Add method-specific summary in run/report artifacts if easy.

**Acceptance:**
- One command/test runs OptBinning to logistic regression.
- Output artifacts are inspectable.
- Fine-classing and OptBinning branches can be compared later.
- No optbinning import in apply/scoring/export paths.
- CI green; `check-api-contracts` green; `check-line-counts` green.

---

## 20. Definition of done

Cardre can:

1. Show OptBinning as a selectable Binning method.
2. Report whether the OptBinning dependency is available (with reason).
3. Fit numerical and categorical variables on train only.
4. Persist Cardre-native bin definitions.
5. Capture solver status, event/non-event counts, bad rates, WOE, IV, warnings,
   and failures.
6. Produce a variable summary artifact (Parquet).
7. Allow manual binning to consume OptBinning source bins.
8. Continue through WOE/IV, WOE transform, and logistic regression.
9. Avoid any optbinning dependency in apply/scoring/export paths.
10. Provide enough metadata for audit report generation.

---

## 21. Non-negotiable acceptance gates

Before merging the final PR in this sequence:

- CI green.
- `check-api-contracts` green (`schema.d.ts` regenerated + committed).
- `check-line-counts` green.
- Default pathway uses `cardre.binning`.
- `AutoBinningFitNode` hidden from `/node-types`.
- Optional OptBinning tests skip cleanly when dependency absent.
- Optional OptBinning tests pass when dependency installed.
- No new execution abstraction.
- No new BinningEngine protocol.
- No `FrozenBinningSpec`.
- No use of OptBinning Scorecard.
- No `quantile` option in the canonical OptBinning method.
- `_LEGACY_NODE_TYPE_METHOD` map retained in `store.py` (defence-in-depth).
- Variable summary artifact is Parquet (`application/vnd.apache.parquet`).

---

## 22. Highest-risk items (ranked)

1. **PR 69 manual-binning generalisation** — 11 `"fine-classing"` references in
   `ManualBinningService` + DTO rename in two files + staleness path
   generalisation + `AmbiguousBranchAncestorError` handling. Confirmed blast
   radius: `ManualBinningService` + `plan_dto.py` + `sidecar/models.py` only
   (downstream `ManualBinningNode` is already source-agnostic via content
   sniffing at `bins.py:497-509`).

2. **PR 68 `BinningDiagnostic` reshape** — breaks internal callers in
   `diagnostics.py` (4 `check_*` functions) and `auto_binning_fit.py`
   (warning-building loop) simultaneously. Easy to miss one caller. Mitigated by
   the explicit migration map in §8.2 and caller list in §8.4.

3. **`schema.d.ts` regen discipline** — easy to forget on PR 67/68/69; fails
   `check-api-contracts` silently with `git diff --exit-code`. Mitigated by
   listing it as an explicit step in every PR.

4. **Default pathway switch** (PR 67) — touches `proof_pathway.py` + ~25 test
   files with `fine-classing` references. Mechanical but broad. Mitigated by the
   exhaustive test list in §18.4.

---

## 23. Decisions applied (from review)

1. **`_LEGACY_NODE_TYPE_METHOD` map in `store.py:32-35`:** KEPT as
   defence-in-depth. One-line cost; harmless; provides a safety net if any
   out-of-band plan ever appears.

2. **Variable summary artifact media type:** Parquet
   (`application/vnd.apache.parquet`). Chosen over JSON for branch-comparison
   and UI-sidebar access patterns. Requires adding a production Parquet writer
   helper in PR 68.

---

## 24. Recommended immediate next task

Start with **PR 67** (Canonical OptBinning cleanup). It is deliberately narrow:
default pathway switch + `AutoBinningFitNode` hiding + `quantile` removal +
train-only guard + tests. This gives PR 68 a clean foundation for richer
artifacts.
