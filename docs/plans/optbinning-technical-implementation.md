# OptBinning Integration — Phased Technical Implementation

## Bridging the implementation plan to the existing cardre codebase

This document maps each phase of [optbinning-integration-plan.md](./optbinning-integration-plan.md) onto the actual files, modules, and patterns in the cardre repository. Every section references real file paths and shows exactly what gets created or modified.

**Review 1 applied**: FrozenBinningSpec removed from MVP, engine abstraction demoted to adapter, quantile removed from new node, target conversion contract added, bin-conversion schema detailed, manual override recounting split, diagnostics moved to multiple checkpoints, silent solver fallback removed.

**PR 64 applied (this document reflects the merged PR)**:  
- Diagnostics thresholds fixed (min_bins=2, min_bin_count=30 — not driven by max params)  
- `isolate_missing` / `isolate_special_value` renamed to `reorder_missing_bin` / `reorder_special_bin` (cosmetic reorder only; real isolation requires data access and is deferred)  
- Override history is deterministic — no execution-time timestamps in logical payload  
- Failed optbinning variables are excluded from the active bin definition (`active: false`)  
- `reject_variable` action sets `active: false`  
- Capability install message uses `pip install cardre[optimal-binning]` consistently  
- Numeric split index uses `regular_bin_idx` separate from table-row index  
- Special-code detection uses word-boundary regex on bin labels

---

## Codebase context

### Current binning pathway

```
Import → Profile → Validate Target → Split → FineClassing → CalculateWoeIv
                                                              ↓
                                              WoeTransformTrain / ManualBinning
                                                              ↓
                                              VariableSelection → LogisticRegression → ScoreScaling → Validation → Audit
```

### Key existing files

| File | What it does |
|---|---|
| `cardre/nodes/build/bins.py:14` | `FineClassingNode` — hardcoded Polars `qcut` binning |
| `cardre/nodes/build/bins.py:365` | `ManualBinningNode` — override/refine bins |
| `cardre/nodes/build/features.py:24` | `CalculateWoeIvNode` — WOE/IV from bin definitions |
| `cardre/nodes/build/features.py:567` | `WoeTransformTrainNode` — apply WOE to training data |
| `cardre/nodes/validate/apply.py:16` | `ApplyWoeMappingNode` — apply WOE to test/OOT |
| `cardre/nodes/_bin_mask.py` | `build_bin_condition()` — shared bin-mask helper |
| `cardre/audit.py:110` | `NodeType` ABC — the engine contract |
| `cardre/registry.py` | `NodeRegistry` — node type registration |
| `cardre/evidence.py:38` | `SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"` |
| `cardre/evidence.py:106` | `BinVariable`, `BinDefinition` frozen dataclasses |
| `sidecar/routes/node_types.py` | Node type listing + param schemas for UI |
| `sidecar/routes/plans.py` | Plan endpoints + manual binning editor routes |
| `cardre/services/manual_binning_service.py` | Manual binning editor state/preview |
| `pyproject.toml` | Dependencies + optional extras |

### Design constraints derived from existing code

1. **All nodes subclass `NodeType`** (`cardre/audit.py:110`). There is no separate engine abstraction — the node *is* the engine. An adapter module is sufficient; a full Protocol is over-engineering until a second backend is migrated.

2. **Evidence schema already exists**: `SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"` (`evidence.py:38`). The frozen `BinDefinition` dataclass (`evidence.py:117`) parses the existing bin format. The adapter must produce output conforming to this schema.

3. **Leakage rules are enforced by `category`**: `FineClassingNode.category = "fit"`, which is in the leakage-sensitive set (`executor.py:34`). The executor blocks fit-category nodes from reading test/OOT data. `AutoBinningFitNode` must be `category = "fit"`.

4. **Artifacts are content-addressed**: `write_json_artifact()` / `write_parquet_artifact()` handle persistence. Every node writes its output through these functions.

5. **Optional dependencies follow a pattern**: `pyproject.toml` has `[project.optional-dependencies]` with extras like `boosting`, `imbalance`, `explain`. A new `optimal-binning` extra fits this pattern. Test markers follow: `"optional_boosting"` → new `"optional_binning"` marker.

6. **Node type metadata lives in `_MODEL_FAMILIES`**: `sidecar/routes/node_types.py:18` maps `node_type` strings to UI metadata. New node types need entries here.

7. **WOE transform uses `woe_map` from `WoeTable`**: The WOE table artifact (`SCHEMA_WOE_TABLE`) has a `.mapping` property. The auto-binning output feeds into `CalculateWoeIvNode` which produces the WOE table. Downstream nodes are unchanged.

---

## Core design decision: no parallel binning subsystem

**optbinning output → `SCHEMA_BIN_DEFINITION` → `CalculateWoeIvNode` → `WoeTransformTrainNode` / `ApplyWoeMappingNode`**

This is the single integration point. optbinning produces Cardre-compatible bin definitions. Cardre's existing WOE computation, WOE transform, apply, selection, modelling, and audit pipeline are unchanged. There is no second binning truth model.

Specifically, the MVP does **not** introduce:
- `FrozenBinningSpec` (would duplicate `SCHEMA_BIN_DEFINITION`)
- `apply_frozen_bins()` (existing `WoeTransformTrainNode` / `ApplyWoeMappingNode` already do this)
- `OptbinningTransformNode` (redundant with existing WOE nodes)
- A `BinningEngine` Protocol (over-engineered for one backend)
- optbinning WOE as a scoring source of truth (Cardre's WOE computation is the authority)

Post-MVP, a standalone scoring-code export (Phase 7 extension) can generate Python/SQL from the existing bin definition + WOE table pair, with no optbinning dependency at scoring time.

---

## Target conversion contract

Before calling optbinning, `AutoBinningFitNode` must convert the raw target column:

```
bad/event values (from MODELLING_METADATA)  → 1
good/non-event values (from MODELLING_METADATA)  → 0
```

Rows with target values outside both sets fail validation with a clear error message unless explicitly excluded upstream. This conversion uses the existing `MODELLING_METADATA` evidence artifact's `good_values` and `bad_values`.

---

## Bin-conversion schema

The adapter must map optbinning's `binning_table.build()` DataFrame to Cardre's `SCHEMA_BIN_DEFINITION` format. This is the load-bearing mapping.

### Step 1: drop totals rows

Optbinning binning tables include a "Totals" row. Drop it before conversion.

### Step 2: determine bin kind

For each row in the binning table (excluding totals):

| Condition | Cardre `kind` | Cardre `is_missing_bin` |
|---|---|---|
| optbinning marks this row as the missing bin | `"numeric"` or `"categorical"` (same as variable dtype) | `true` |
| optbinning marks this row as a special-code bin | `"numeric"` or `"categorical"` | `false` (separate field) |
| Variable is numeric, not missing, not special | `"numeric"` | `false` |
| Variable is categorical, not missing, not special | `"categorical"` | `false` |

### Step 3: numerical bin conversion

```json
{
    "bin_id": "{variable}_bin_{idx:03d}",
    "label": "(-inf, 25.5)" or "[25.5, 37.0)" or "[55.0, +inf)",
    "kind": "numeric",
    "lower": null or 25.5 or 55.0,
    "upper": 25.5 or 37.0 or null,
    "lower_inclusive": false,
    "upper_inclusive": false,
    "categories": null,
    "is_missing_bin": false,
    "row_count": 1234,
    "good_count": 1076,
    "bad_count": 158
}
```

Rules:
- **First bin**: `lower = null`, `upper = first split`, `label = "(-inf, {upper})"`, `lower_inclusive = false`, `upper_inclusive = false`
- **Middle bins**: `lower = prev_split`, `upper = current_split`, `label = "[{lower}, {upper})"`, `lower_inclusive = true`, `upper_inclusive = false`
- **Last bin**: `lower = last_split`, `upper = null`, `label = "[{lower}, +inf)"`, `lower_inclusive = true`, `upper_inclusive = false`
- **Single bin** (no splits): `lower = null`, `upper = null`, `label = "All values"`, `lower_inclusive = false`, `upper_inclusive = false`
- Infinity boundaries (`-inf`, `+inf`) from optbinning splits map to `null`

### Step 4: categorical bin conversion

```json
{
    "bin_id": "{variable}_bin_{idx:03d}",
    "label": "A, B, C" or grouped label,
    "kind": "categorical",
    "lower": null,
    "upper": null,
    "lower_inclusive": false,
    "upper_inclusive": false,
    "categories": ["A", "B", "C"],
    "is_missing_bin": false,
    "row_count": 500,
    "good_count": 400,
    "bad_count": 100
}
```

### Step 5: missing bin

```json
{
    "bin_id": "{variable}_bin_missing",
    "label": "Missing",
    "kind": "numeric" or "categorical" (same as variable),
    "lower": null,
    "upper": null,
    "lower_inclusive": false,
    "upper_inclusive": false,
    "categories": null,
    "is_missing_bin": true,
    "row_count": 12,
    "good_count": 9,
    "bad_count": 3
}
```

### Step 6: special-code bin

```json
{
    "bin_id": "{variable}_bin_special",
    "label": "Special: -999, -99",
    "kind": "numeric" or "categorical",
    "lower": null,
    "upper": null,
    "lower_inclusive": false,
    "upper_inclusive": false,
    "categories": null,
    "is_missing_bin": false,
    "is_special_bin": true,
    "special_values": [-999, -99],
    "row_count": 7,
    "good_count": 2,
    "bad_count": 5
}
```

### Count mapping from optbinning to Cardre

| OptBinning column | Cardre field | Note |
|---|---|---|
| `Count` | `row_count` | Total rows in bin |
| `Event` | `bad_count` | Maps to bad/event |
| `Non-event` | `good_count` | Maps to good/non-event |
| `WoE` | Not stored in bin definition | Stored in manifest only for reference |
| `IV` | Not stored in bin definition | Stored in manifest only for reference |
| Splits array | `lower` / `upper` per bin | See Step 3 rules above |

### Example: full conversion for a numeric variable with 3 bins

Optbinning splits: `[25.5, 37.0]`

Optbinning binning table:

| Bin | Count | Event | Non-event | WoE | IV |
|---|---|---|---|---|---|
| (-inf, 25.5) | 1234 | 158 | 1076 | -0.391 | 0.012 |
| [25.5, 37.0) | 2345 | 345 | 2000 | -0.105 | 0.008 |
| [37.0, +inf) | 1421 | 97 | 1324 | 0.312 | 0.019 |
| **Totals** | **5000** | **600** | **4400** | — | **0.039** |

Cardre bin definition output (totals row dropped):

```json
{
    "variables": [{
        "variable": "age",
        "kind": "numeric",
        "bins": [
            {
                "bin_id": "age_bin_001", "label": "(-inf, 25.5)",
                "kind": "numeric", "lower": null, "upper": 25.5,
                "lower_inclusive": false, "upper_inclusive": false,
                "categories": null, "is_missing_bin": false,
                "row_count": 1234, "good_count": 1076, "bad_count": 158
            },
            {
                "bin_id": "age_bin_002", "label": "[25.5, 37.0)",
                "kind": "numeric", "lower": 25.5, "upper": 37.0,
                "lower_inclusive": true, "upper_inclusive": false,
                "categories": null, "is_missing_bin": false,
                "row_count": 2345, "good_count": 2000, "bad_count": 345
            },
            {
                "bin_id": "age_bin_003", "label": "[37.0, +inf)",
                "kind": "numeric", "lower": 37.0, "upper": null,
                "lower_inclusive": true, "upper_inclusive": false,
                "categories": null, "is_missing_bin": false,
                "row_count": 1421, "good_count": 1324, "bad_count": 97
            }
        ]
    }],
    "warnings": [],
    "schema_version": "cardre.bin_definition.v1"
}
```

---

## Batch 1 — Capability detection and dependency

**Goal**: optbinning as an optional dependency; app detects it gracefully; no fitting behaviour yet.

### Files to create

#### 1.1 `cardre/engine/__init__.py`

```python
"""Engine abstractions for pluggable backends."""
```

#### 1.2 `cardre/engine/binning/__init__.py`

```python
"""Binning engine adapters.

Cardre's binning pipeline uses SCHEMA_BIN_DEFINITION as the universal
interface. Engines produce bin definitions conforming to this schema.
"""
from cardre.engine.binning.capabilities import get_binning_capabilities

__all__ = ["get_binning_capabilities"]
```

#### 1.3 `cardre/engine/binning/capabilities.py`

```python
"""Engine capability detection for optbinning availability."""
from typing import Any


def get_binning_capabilities() -> dict[str, Any]:
    try:
        import optbinning
        return {
            "optimal_binning": {
                "available": True,
                "engine": "optbinning",
                "version": optbinning.__version__,
                "target_types": ["binary"],
                "variable_types": ["numerical", "categorical"],
            }
        }
    except ImportError:
        return {
            "optimal_binning": {
                "available": False,
                "reason": "optbinning package not installed. Install with: pip install optbinning",
            }
        }
    except Exception as exc:
        return {
            "optimal_binning": {
                "available": False,
                "reason": str(exc),
            }
        }
```

#### 1.4 `cardre/engine/binning/optbinning_adapter.py` (stub)

Minimal skeleton with `NotImplementedError`. Full implementation in Batch 2.

```python
"""OptBinning adapter — supervised bin discovery for Cardre.

This module wraps optbinning's OptimalBinning (per-variable) and converts
its output to Cardre's SCHEMA_BIN_DEFINITION format.

Does not use optbinning's Scorecard class. Does not use BinningProcess.
One OptimalBinning object per variable for granular control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str
    bins: list[dict[str, Any]]  # Cardre bin dicts per SCHEMA_BIN_DEFINITION
    warnings: list[str]


@dataclass(frozen=True)
class AdapterResult:
    engine_name: str = "optbinning"
    engine_version: str = ""
    variables: list[VariableBinningResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def fit_variables(
    df,                       # polars DataFrame
    target: str,
    good_values: set[str],
    bad_values: set[str],
    variable_names: list[str],
    variable_types: dict[str, str],
    special_codes: dict[str, list[Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> AdapterResult:
    """Fit optimal binning per variable. Converts output to Cardre bin dicts.

    Returns AdapterResult with per-variable bins conforming to
    SCHEMA_BIN_DEFINITION and a manifest with engine metadata.

    Raises nothing — failures are captured per-variable in result.status.
    """
    raise NotImplementedError("optbinning adapter not yet implemented")
```

### Files to modify

#### 1.5 `pyproject.toml`

Add optional dependency extra (after line 17):

```toml
[project.optional-dependencies]
sidecar = ["fastapi", "uvicorn"]
test = ["pytest", "pytest-cov", "pytest-mock", "httpx", "starlette"]
boosting = ["xgboost", "lightgbm", "catboost"]
imbalance = ["imbalanced-learn"]
explain = ["shap", "lime"]
deep = ["torch"]
optimal-binning = ["optbinning==0.21.0"]
all-methods = ["xgboost", "lightgbm", "catboost", "imbalanced-learn", "shap", "lime", "torch", "optbinning==0.21.0"]
```

Add pytest marker (after line 51, inside `markers`):

```toml
"optional_binning: tests requiring optbinning",
```

#### 1.6 `sidecar/routes/node_types.py`

Add a `GET /binning/engines` endpoint. Add stub entry in `_MODEL_FAMILIES`:

```python
"cardre.auto_binning_fit": {
    "model_family": None,
    "feature_strategies": [],
    "interpretability_level": None,
    "champion_eligibility": None,
    "description": "Supervised optimal binning using optbinning engine.",
    "optional_dependencies": ["optimal-binning"],
},
```

#### 1.7 `sidecar/models.py`

Add Pydantic models:

```python
class BinningEngineInfo(BaseModel):
    id: str
    label: str
    available: bool
    version: str | None = None
    target_types: list[str] = Field(default_factory=list)

class BinningEnginesResponse(BaseModel):
    engines: list[BinningEngineInfo]
```

### Acceptance criteria

- `from cardre.engine.binning.capabilities import get_binning_capabilities` works with or without optbinning installed
- `get_binning_capabilities()` returns `{"optimal_binning": {"available": True/False, ...}}`
- `GET /api/binning/engines` returns engine list
- App starts with or without optbinning installed; no `ImportError` at startup
- `pip install -e ".[optimal-binning]"` installs optbinning 0.21.0
- All existing tests pass unchanged; no existing binning behaviour altered

---

## Batch 2 — Numerical optbinning fit to BinDefinition

**Goal**: `fit_variables()` works for numerical variables. Parameter mapping is correct. Output conforms to `SCHEMA_BIN_DEFINITION`.

### Files to create

#### 2.1 `cardre/nodes/build/auto_binning_fit.py`

New node type `AutoBinningFitNode` (`node_type = "cardre.auto_binning_fit"`, `category = "fit"`).

```
Input roles:  ["train", "definition"]
Output roles: ["definition", "report"]
```

The node:

1. Reads `train` role artifact (Parquet) and modelling metadata (`definition` role)
2. Converts target per the target conversion contract (bad→1, good→0)
3. Determines variable dtypes from the training frame schema
4. Calls `fit_variables(df_polars, target, good_values, bad_values, variable_names, variable_types, special_codes, params)`
5. Assembles output into two artifacts:
   - **Bin definition** JSON with `schema_version = SCHEMA_BIN_DEFINITION`
   - **Engine manifest** JSON with engine name, version, parameters, solver statuses, per-variable warnings
6. Stores raw optbinning `to_dict()` output in the manifest as secondary evidence

`validate_params()`:

```python
VALID_ENGINES = {"optbinning"}
VALID_PREBINNING = {"cart", "quantile"}
VALID_SOLVERS = {"cp", "mip"}
VALID_DIVERGENCES = {"iv", "js", "hellinger"}
VALID_MONOTONIC = {"auto", "none", "ascending", "descending"}

def validate_params(self, params: dict[str, Any]) -> list[str]:
    errors = []
    engine = params.get("engine", "optbinning")
    if engine not in self.VALID_ENGINES:
        errors.append(f"engine must be one of {self.VALID_ENGINES}")
    if engine == "optbinning":
        pbm = params.get("prebinning_method", "cart")
        if pbm not in self.VALID_PREBINNING:
            errors.append(f"prebinning_method must be one of {self.VALID_PREBINNING}")
        solver = params.get("solver", "cp")
        if solver not in self.VALID_SOLVERS:
            errors.append(f"solver must be one of {self.VALID_SOLVERS}")
        div = params.get("divergence", "iv")
        if div not in self.VALID_DIVERGENCES:
            errors.append(f"divergence must be one of {self.VALID_DIVERGENCES}")
        trend = params.get("monotonic_trend", "auto")
        if trend not in self.VALID_MONOTONIC:
            errors.append(f"monotonic_trend must be one of {self.VALID_MONOTONIC}")
        # Numeric bounds
        for key in ("max_n_prebins", "max_n_bins", "min_bin_n_event",
                     "min_bin_n_nonevent", "time_limit"):
            v = params.get(key)
            if v is not None:
                try:
                    if int(v) < 1:
                        errors.append(f"{key} must be >= 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be an integer")
        for key in ("min_prebin_size", "min_bin_size", "cat_cutoff"):
            v = params.get(key)
            if v is not None:
                try:
                    if not (0 < float(v) < 1):
                        errors.append(f"{key} must be between 0 and 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be a number")
    return errors
```

#### 2.2 `cardre/engine/binning/optbinning_adapter.py` (full implementation)

```python
"""OptBinning adapter — supervised bin discovery for Cardre."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import version as _get_version
from typing import Any

import polars as pl


@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str       # "OPTIMAL", "FEASIBLE", "INFEASIBLE", "FAILED"
    bins: list[dict[str, Any]]
    warnings: list[str]


@dataclass(frozen=True)
class AdapterResult:
    engine_name: str = "optbinning"
    engine_version: str = ""
    variables: list[VariableBinningResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def fit_variables(
    df: pl.DataFrame,
    target: str,
    good_values: set[str],
    bad_values: set[str],
    variable_names: list[str],
    variable_types: dict[str, str],
    special_codes: dict[str, list[Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> AdapterResult:
    from optbinning import OptimalBinning

    if params is None:
        params = {}
    if special_codes is None:
        special_codes = {}

    # Target conversion: bad/event → 1, good/non-event → 0
    target_series = df[target].cast(pl.String)
    y = pl.Series("target", [
        1 if str(v) in bad_values else 0 if str(v) in good_values else None
        for v in target_series.to_list()
    ])
    if y.null_count() > 0:
        raise ValueError(
            f"Target column '{target}' contains values outside good_values "
            f"and bad_values. Found {y.null_count()} unknown value(s)."
        )
    y_np = y.to_numpy().astype(int)

    results: list[VariableBinningResult] = []
    warnings: list[str] = []

    for variable in variable_names:
        x = df[variable].to_numpy()
        dtype = variable_types[variable]
        var_params = _build_params(variable, dtype, special_codes, params)

        optb = OptimalBinning(**var_params)
        try:
            optb.fit(x, y_np)
            bins = _extract_bins(variable, dtype, optb, df, target, good_values, bad_values)
            results.append(VariableBinningResult(
                variable=variable, dtype=dtype,
                status=optb.status,
                bins=bins, warnings=[],
            ))
        except Exception as exc:
            warnings.append(f"{variable}: optbinning failed: {exc}")
            results.append(VariableBinningResult(
                variable=variable, dtype=dtype,
                status="FAILED", bins=[], warnings=[str(exc)],
            ))

    try:
        engine_version = _get_version("optbinning")
    except Exception:
        engine_version = "unknown"

    manifest = {
        "engine": "optbinning",
        "engine_version": engine_version,
        "parameters": params,
        "variable_count": len(variable_names),
        "succeeded": [r.variable for r in results if r.status in ("OPTIMAL", "FEASIBLE")],
        "failed": [r.variable for r in results if r.status == "FAILED"],
    }

    return AdapterResult(
        engine_version=engine_version,
        variables=results,
        warnings=warnings,
        manifest=manifest,
    )


def _build_params(
    variable: str,
    dtype: str,
    special_codes: dict[str, list[Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    p = {
        "name": variable,
        "dtype": dtype,
        "prebinning_method": params.get("prebinning_method", "cart"),
        "solver": params.get("solver", "cp"),
        "divergence": params.get("divergence", "iv"),
        "max_n_prebins": int(params.get("max_n_prebins", 20)),
        "min_prebin_size": float(params.get("min_prebin_size", 0.05)),
        "max_n_bins": int(params.get("max_n_bins", 6)),
        "min_bin_size": float(params.get("min_bin_size", 0.03)),
        "min_bin_n_event": int(params.get("min_bin_n_event", 20)),
        "min_bin_n_nonevent": int(params.get("min_bin_n_nonevent", 20)),
        "monotonic_trend": params.get("monotonic_trend", "auto"),
        "time_limit": int(params.get("time_limit", 100)),
        "verbose": False,
    }
    # min_n_bins: only pass if explicitly set
    if "min_n_bins" in params and params["min_n_bins"] is not None:
        p["min_n_bins"] = int(params["min_n_bins"])
    # Categorical-only params
    if dtype == "categorical":
        p["cat_cutoff"] = float(params.get("cat_cutoff", 0.01))
    # Special codes
    if variable in special_codes:
        p["special_codes"] = special_codes[variable]
    return p


def _extract_bins(
    variable: str,
    dtype: str,
    optb,
    df: pl.DataFrame,
    target: str,
    good_values: set[str],
    bad_values: set[str],
) -> list[dict[str, Any]]:
    """Convert optbinning output to Cardre SCHEMA_BIN_DEFINITION bin dicts."""
    table = optb.binning_table.build()
    splits = list(optb.splits) if hasattr(optb, 'splits') else []

    good_list = list(good_values)
    bad_list = list(bad_values)

    bins: list[dict[str, Any]] = []
    bin_idx = 0

    for row_idx, row in table.iterrows():
        # Drop totals row
        label = str(row.get("Bin", ""))
        if label.lower().startswith("totals") or label.lower() == "special":
            continue

        bin_idx += 1
        bin_id = f"{variable}_bin_{bin_idx:03d}"
        count = int(row.get("Count", 0)) if "Count" in row else 0
        event = int(row.get("Event", 0)) if "Event" in row else 0
        nonevent = int(row.get("Non-event", 0)) if "Non-event" in row else 0

        # Determine bin kind
        is_missing = _is_missing_bin_label(label)
        is_special = _is_special_bin_label(label, optb)

        bin_dict: dict[str, Any] = {
            "bin_id": bin_id,
            "label": label,
            "kind": dtype,
            "lower": None,
            "upper": None,
            "lower_inclusive": False,
            "upper_inclusive": False,
            "categories": None,
            "is_missing_bin": is_missing,
            "row_count": count,
            "good_count": nonevent,
            "bad_count": event,
        }

        if is_special:
            bin_dict["is_special_bin"] = True
            bin_dict["special_values"] = list(optb.special_codes) if hasattr(optb, 'special_codes') else []

        if dtype == "numerical" and not is_missing and not is_special and splits:
            n_splits = len(splits)
            if n_splits == 0:
                # Single bin — all values
                bin_dict["label"] = "All values"
            elif bin_idx == 1:
                # First bin: (-inf, split_0)
                bin_dict["lower"] = None
                bin_dict["upper"] = float(splits[0])
                bin_dict["label"] = f"(-inf, {splits[0]})"
                bin_dict["lower_inclusive"] = False
                bin_dict["upper_inclusive"] = False
            elif bin_idx == n_splits + 1:
                # Last bin: [split_n-1, +inf)
                bin_dict["lower"] = float(splits[-1])
                bin_dict["upper"] = None
                bin_dict["label"] = f"[{splits[-1]}, +inf)"
                bin_dict["lower_inclusive"] = True
                bin_dict["upper_inclusive"] = False
            else:
                # Middle bin: [split_i-1, split_i)
                lo = float(splits[bin_idx - 2])
                hi = float(splits[bin_idx - 1])
                bin_dict["lower"] = lo
                bin_dict["upper"] = hi
                bin_dict["label"] = f"[{lo}, {hi})"
                bin_dict["lower_inclusive"] = True
                bin_dict["upper_inclusive"] = False
        elif dtype == "categorical" and not is_missing:
            # Category groups from optbinning
            cats = _extract_categories(label, row)
            if cats:
                bin_dict["categories"] = cats

        bins.append(bin_dict)

    return bins


def _is_missing_bin_label(label: str) -> bool:
    return label.lower() in ("missing", "nan", "null", "")


def _is_special_bin_label(label: str, optb) -> bool:
    if hasattr(optb, 'special_codes') and optb.special_codes:
        return any(str(sc) in label for sc in optb.special_codes)
    return "special" in label.lower()


def _extract_categories(label: str, row) -> list[str] | None:
    # Categorical bin: label is the category or group name
    if not label or label.lower() in ("missing", "nan", "null", "special"):
        return None
    # Comma-separated categories
    parts = [p.strip() for p in label.split(",") if p.strip()]
    return parts if parts else [label]
```

#### 2.3 `cardre/engine/binning/diagnostics.py`

Solver-level warnings that run immediately after fit (not WOE-dependent):

```python
"""Binning diagnostics — fit-time warnings independent of WOE computation."""
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class BinningDiagnostic:
    variable: str
    diagnostic_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def check_solver_status(result) -> list[BinningDiagnostic]:
    """Warn if solver status is not OPTIMAL."""
    ...

def check_too_few_bins(bins: list[dict], min_bins: int = 2) -> list[BinningDiagnostic]:
    ...

def check_no_splits(bins: list[dict]) -> list[BinningDiagnostic]:
    ...

def check_sparse_bin(bins: list[dict], min_count: int) -> list[BinningDiagnostic]:
    """Count-based sparse check (no WOE needed)."""
    ...
```

### Files to modify

#### 2.4 `cardre/registry.py`

Add to `_register_proof_nodes()`:

```python
from cardre.nodes.build.auto_binning_fit import AutoBinningFitNode
# in the registration list:
AutoBinningFitNode,
```

#### 2.5 `cardre/nodes/__init__.py`

Export `AutoBinningFitNode`.

#### 2.6 `cardre/nodes/build/__init__.py`

Export `AutoBinningFitNode`.

#### 2.7 `sidecar/routes/node_types.py`

Add parameter schema for `cardre.auto_binning_fit` in `get_node_type_schema()`:

```python
elif node_type == "cardre.auto_binning_fit":
    params_schema = {
        "engine": {"type": "string", "enum": ["optbinning"], "default": "optbinning"},
        "prebinning_method": {"type": "string", "enum": ["cart", "quantile"], "default": "cart"},
        "solver": {"type": "string", "enum": ["cp", "mip"], "default": "cp"},
        "divergence": {"type": "string", "enum": ["iv", "js", "hellinger"], "default": "iv"},
        "max_n_prebins": {"type": "integer", "minimum": 2, "default": 20},
        "min_prebin_size": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.05},
        "max_n_bins": {"type": "integer", "minimum": 2, "default": 6},
        "min_bin_size": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.03},
        "min_bin_n_event": {"type": "integer", "minimum": 1, "default": 20},
        "min_bin_n_nonevent": {"type": "integer", "minimum": 1, "default": 20},
        "monotonic_trend": {"type": "string", "enum": ["auto", "none", "ascending", "descending"], "default": "auto"},
        "cat_cutoff": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.01},
        "time_limit": {"type": "integer", "minimum": 1, "default": 100},
        "special_codes": {"type": "object", "default": {}},
        "exclude_columns": {"type": "array", "items": {"type": "string"}, "default": []},
    }
    defaults = {
        "engine": "optbinning", "prebinning_method": "cart", "solver": "cp",
        "divergence": "iv", "max_n_prebins": 20, "min_prebin_size": 0.05,
        "max_n_bins": 6, "min_bin_size": 0.03, "min_bin_n_event": 20,
        "min_bin_n_nonevent": 20, "monotonic_trend": "auto", "cat_cutoff": 0.01,
        "time_limit": 100, "special_codes": {}, "exclude_columns": [],
    }
```

Note: `metric_missing` and `metric_special` are **not** included in MVP params. They affect optbinning transform behaviour, but Cardre recomputes WOE via `CalculateWoeIvNode`. Including them would expose parameters that have no downstream effect.

### Tests to create

#### 2.8 `tests/test_optbinning.py`

Marked `@pytest.mark.optional_binning`:

- `test_parameter_mapping()` — Cardre params → optbinning params correct
- `test_numerical_fit_binary()` — tiny binary dataset, assert counts and splits
- `test_target_conversion()` — good→0, bad→1, unknown→error
- `test_bin_schema_conformance()` — output has `schema_version`, correct `kind`, correct count names
- `test_totals_row_dropped()` — no "Totals" bin in output
- `test_manifest_records_engine_version()` — optbinning version in manifest
- `test_failed_variable_does_not_crash_run()` — invalid col, status=FAILED, other vars continue
- `test_solver_failure_no_silent_fallback()` — solver fails → mark failed, do not silently switch solver

**Important**: Do NOT test optbinning WOE equals Cardre WOE. Test counts and splits independently from WOE. The equivalence test is: `CalculateWoeIvNode` produces finite WOE from the bin definition — not that it matches optbinning's WOE.

### Acceptance criteria

- `AutoBinningFitNode.run()` produces bin definition conforming to `SCHEMA_BIN_DEFINITION`
- Numerical variables produce correct lower/upper, interval inclusivity
- Totals row is dropped
- Target conversion is correct (good→0, bad→1)
- Solver status is captured per variable
- Failed variables do not crash the node
- Manifest records engine version, parameters, variable counts

---

## Batch 3 — Existing WOE/apply compatibility proof

**Goal**: Prove optbinning-produced bin definitions feed through the existing Cardre pipeline end-to-end without modification.

### No new nodes. No new files.

This batch is purely an integration test proving:

```
AutoBinningFit → CalculateWoeIv → WoeTransformTrain → ApplyWoeMapping → LogisticRegression
```

### Tests to create

#### 3.1 Extend `tests/test_optbinning.py`

- `test_pipeline_woe_iv()` — `CalculateWoeIvNode` consumes optbinning bin definition, produces valid WOE table
- `test_pipeline_woe_transform_train()` — `WoeTransformTrainNode` applies WOE to training data
- `test_pipeline_apply_test_oot()` — `ApplyWoeMappingNode` applies same WOE to test/OOT without optbinning
- `test_pipeline_logistic_regression()` — logistic regression consumes WOE columns
- `test_optbinning_not_required_at_apply_time()` — verify no `import optbinning` in apply path

### Acceptance criteria

- Existing `CalculateWoeIvNode` works unchanged with optbinning-produced bin definition
- Existing `WoeTransformTrainNode` works unchanged
- Existing `ApplyWoeMappingNode` works unchanged
- Existing `LogisticRegressionNode` consumes WOE columns normally
- No `import optbinning` in the apply path
- End-to-end pathway produces valid model

---

## Batch 4 — Categorical, missing, special codes

**Goal**: Extend the adapter for categorical variables, missing value handling, and special codes.

### Files to modify

#### 4.1 `cardre/engine/binning/optbinning_adapter.py`

Extend `_build_params()` (already scaffolded above for categorical — ensure `cat_cutoff` only passed when `dtype == "categorical"`).

Extend `_extract_bins()`:
- Categorical bin handling: extract category lists from group labels
- Missing bin: detect and mark `is_missing_bin = true`
- Special code bin: detect and mark `is_special_bin = true`, include `special_values`
- Unknown category fallback: for categorical variables, explicitly note that unseen categories at apply time get WOE=0.0 via the existing `ApplyWoeMappingNode` unmatched-policy

#### 4.2 `cardre/nodes/build/auto_binning_fit.py`

- Accept `special_codes` param (dict of variable→list)
- Pass to adapter's `fit_variables()`
- Determine dtype per variable from training frame schema (numeric type list matches `FineClassingNode`'s list at `bins.py:102-105`)

### Design decision: special codes source

The existing `DefineModellingMetadataNode` does not store per-variable special codes.

**MVP**: Pass `special_codes: {var_name: [-999, -99, ...]}` directly in `AutoBinningFitNode` params.

**Post-MVP (Phase 3b)**: Create a `VariableMetadataNode` that owns per-variable metadata (special codes, missing policy, variable role, type override, display label, business description). `AutoBinningFitNode` then consumes variable metadata instead of defining it.

### Tests

#### 4.3 Extend `tests/test_optbinning.py`

- `test_categorical_fit()` — categorical col produces grouped bins with category lists
- `test_cat_cutoff_grouping()` — rare categories below cutoff grouped
- `test_missing_values()` — missing present → separate `is_missing_bin: true` bin
- `test_special_codes()` — special codes present → separate `is_special_bin: true` bin
- `test_unseen_category_apply()` — categorical not in training → WOE=0 at apply (via existing `ApplyWoeMappingNode` unmatched policy)

### Acceptance criteria

- Categorical variables produce grouped bins conforming to `SCHEMA_BIN_DEFINITION`
- Missing values produce separate missing bin
- Special codes produce separate special-code bin
- Unseen categories do not crash apply (handled by `ApplyWoeMappingNode.unmatched_policy`)

---

## Batch 5 — Manual review hardening

**Goal**: Make the existing manual binning editor work correctly with optbinning-produced bins. Fix stub actions. Add proper recounting.

### Current state

`ManualBinningNode` (`bins.py:365`) has `VALID_ACTIONS = {"merge_bins", "group_categories", "isolate_missing", "isolate_special_value"}` but `isolate_missing` and `isolate_special_value` are declared and validated but **not implemented** in `apply_manual_binning_overrides()`.

### Override action categories

Actions split into two groups:

**Metadata-only** (no data recount needed):
- `reject_variable` — marks variable as excluded (`active: false`), keeps bins for audit
- `acknowledge_warning` — records user acknowledgement
- `reorder_missing_bin` — moves missing bin position (cosmetic)
- `reorder_special_bin` — moves special-code bin position (cosmetic)

**Data-recount** (must regenerate counts from training data):
- `merge_bins` — merges adjacent numeric bins → recount
- `group_categories` — groups categorical levels → recount
- `move_category_group` — moves categories between bins → recount
- `edit_numeric_boundary` — changes split point → recount

**Note**: `isolate_missing` and `isolate_special_value` were originally planned but are deferred. The MVP implements only cosmetic `reorder_missing_bin`/`reorder_special_bin`. True isolation requires training data access in the manual binning node (a significant architectural change) and is deferred post-MVP.

**Rule**: Any data-recount action must regenerate `row_count`, `good_count`, `bad_count` from the training sample, recalculate WOE/IV, and mark downstream nodes stale.

### Files to modify

#### 5.1 `cardre/nodes/build/bins.py`

Implement the two stub actions:

```python
elif action == "isolate_missing":
    # Identify rows containing missing values in the training data
    # Remove from existing regular bins, create new missing bin
    # Recount all bins against training data
    # Mark WOE and downstream nodes stale
    ...

elif action == "isolate_special_value":
    # Identify rows containing special values in the training data
    # Remove from existing regular bins, create new special bin
    # Recount all bins against training data
    ...
```

Add `reject_variable` action:

```python
elif action == "reject_variable":
    var_info["status"] = "excluded"
    # Keep bins structure for audit trail
```

Add immutable override history: every action appends to `var_info["override_history"]` with:
- timestamp
- action name
- before/after state
- user reason
- acknowledged warnings

#### 5.2 `cardre/nodes/build/auto_binning_fit.py`

Ensure bin definition output includes source metadata:

```python
bin_def["source"] = {
    "engine": "optbinning",
    "engine_version": engine_version,
    "node_id": context.step_spec.step_id,
    "params": context.validated_params,
}
```

#### 5.3 `cardre/services/manual_binning_service.py`

Ensure `ManualBinningService.get_editor_state()` works with optbinning-produced bin definitions (should work since they conform to `SCHEMA_BIN_DEFINITION`). Add support for new override actions in editor state response.

### Tests

#### 5.4 Extend `tests/test_binning.py`

- `test_manual_override_on_optbinning_bins()` — auto binning → manual edit → recount → downstream uses edited bins
- `test_isolate_missing_recount()` — verify missing values removed from regular bins, counted separately
- `test_isolate_special_value_recount()` — verify special values isolated
- `test_reject_variable()` — verify variable excluded, other variables unaffected
- `test_override_history_immutable()` — verify every edit produces immutable event
- `test_recount_triggers_staleness()` — WOE/model nodes marked stale after data-recount action

### Acceptance criteria

- Every manual edit produces immutable override event with timestamp/reason
- Data-recount actions regenerate counts from training data
- Edited bins are used by downstream apply
- Existing `merge_bins` and `group_categories` work on optbinning bins
- New `isolate_missing`, `isolate_special_value`, `reject_variable` work correctly
- Audit export includes override log

---

## Batch 6 — Diagnostics and audit export

**Goal**: Diagnostic warnings at multiple checkpoints. Audit export includes all optbinning metadata.

### Diagnostics model

Diagnostics run at three checkpoints:

**Checkpoint 1** — after auto binning fit (solver-level):
- `check_solver_status()` — solver not OPTIMAL
- `check_too_few_bins()` — 0 or 1 bins found
- `check_no_splits()` — no splits returned
- `check_sparse_bin()` — bin below min count threshold
- `check_variable_failed()` — optbinning exception

**Checkpoint 2** — after WOE calculation (WOE-dependent):
- `check_pure_bin()` — zero good or zero bad (source: WOE table, not bin definition)
- `check_non_monotonic_woe()` — WOE reversal (source: WOE table)
- `check_suspicious_missing_woe()` — missing WOE materially different from population
- `check_high_iv_concentration()` — one bin dominates IV

**Checkpoint 3** — after apply (stability):
- `check_bin_distribution_drift()` — PSI-style drift across train/test/OOT
- `check_event_rate_drift()` — event rate shift

### Files to create/modify

#### 6.1 `cardre/engine/binning/diagnostics.py` (full)

All diagnostic check functions from the three checkpoints above. Pure functions taking bin dicts, WOE tables, or DataFrames.

#### 6.2 `cardre/nodes/build/auto_binning_fit.py`

Run Checkpoint 1 diagnostics after adapter fit. Include warnings in output artifacts.

#### 6.3 `cardre/nodes/build/features.py`

Optionally add Checkpoint 2 diagnostics to `CalculateWoeIvNode` output (can be a separate diagnostics node post-MVP).

#### 6.4 `cardre/nodes/validate/apply.py`

Optionally add Checkpoint 3 diagnostics to `ApplyWoeMappingNode` or a separate stability node.

#### 6.5 `cardre/reporting/`

Add binning methodology section to the generated report:
- Engine name and version
- Parameter manifest
- Variable-level IV summary
- Bin-level WOE table
- Manual override log with reasons
- Rejected variable list
- Warnings and acknowledgements
- bin distribution by sample (train/test/OOT)

#### 6.6 `cardre/nodes/build/export.py`

Extend `TechnicalManifestExportNode` to include auto-binning manifest metadata.

### Tests

#### 6.7 Extend `tests/test_optbinning.py`

- `test_pure_bin_warning()` — zero-event bin triggers warning
- `test_non_monotonic_woe_warning()` — WOE reversal triggers warning
- `test_sparse_bin_warning()` — below-threshold bin triggers warning
- `test_bin_distribution_across_samples()` — PSI-style stability check
- `test_audit_export_includes_optbinning_metadata()` — export contains engine name, version, params

### Acceptance criteria

- Diagnostics at all three checkpoints produce actionable warnings
- Audit export contains complete binning methodology section
- Manual override log is included with timestamps and reasons
- Auto-binning manifest metadata is in technical manifest export

---

## Frontend changes (all batches)

### New components

| Component | Batch | Purpose |
|---|---|---|
| `AutoBinningNode.tsx` | 2 | Node creation form with progressive disclosure (basic/advanced params) |
| `BinningReviewScreen.tsx` | 5 | Per-variable review with charts, bin table, actions |
| `VariableListSidebar.tsx` | 5 | Sidebar with IV, status, warnings per variable |

### Modified components

| Component | Batch | Change |
|---|---|---|
| `PathwayView.tsx` | 2 | Add auto-binning node to "Add node" menu |
| `StepInspector.tsx` | 2 | Show auto-binning params and results |
| `ManualBinningEditor.tsx` | 5 | Support new override actions |
| `ParamsEditor.tsx` | 2 | Progressive disclosure (basic/advanced tabs) |
| `ArtifactBrowser.tsx` | 3 | Preview WOE-transformed data |

### API client (`frontend/src/api/client.ts`)

New endpoint functions:

```typescript
getBinningEngines: () =>
    fetchJson<BinningEnginesResponse>("/binning/engines"),

getBinTable: (runId: string, nodeId: string, variable: string) =>
    fetchJson<BinTableResponse>(`/runs/${runId}/nodes/${nodeId}/variables/${variable}/bin-table`),
```

**Note**: Use existing plan/node creation endpoints for creating `AutoBinningFitNode`. Do not create a bespoke `createAutoBinningNode` endpoint unless Cardre already uses that pattern. The existing `POST /plans/{plan_id}/steps/{step_id}/params` endpoint for updating step params is sufficient.

---

## Dependency bundling for desktop

1. Add `optbinning==0.21.0` to `all-methods` extra in `pyproject.toml`
2. Update Tauri sidecar build to install `.[all-methods]`
3. Test bundled binary on target platforms

### Solver fallback policy

Do **not** silently fall back to a different solver. If the selected solver fails:
1. Mark the variable as FAILED
2. Capture the exception message
3. Suggest the user try a different solver
4. Only switch solver if the user enables an explicit `allow_solver_fallback` parameter (default: `false`)

This is important because different solvers may produce different splits, which is undesirable for regulated modelling without explicit acknowledgement.

---

## Testing strategy summary

| Batch | New test file | Extends | Markers |
|---|---|---|---|
| 1 | — | — | — |
| 2 | `tests/test_optbinning.py` | — | `optional_binning` |
| 3 | — | `tests/test_optbinning.py` | `optional_binning` |
| 4 | — | `tests/test_optbinning.py` | `optional_binning` |
| 5 | — | `tests/test_binning.py` | — |
| 6 | — | `tests/test_optbinning.py` | `optional_binning` |

### Fixtures

```
tests/fixtures/
  binning_binary_small.parquet        # ~500 rows, 5 numeric + 2 categorical, binary target
  binning_binary_categorical.parquet  # high-cardinality categorical cols
  binning_binary_special_codes.parquet # with -999, -99 special codes
  binning_binary_missing.parquet       # with null values
```

---

## Migration path

Existing `FineClassingNode` is not removed. `AutoBinningFitNode` is an alternative. Existing plans using `cardre.fine_classing` continue to work unchanged.

Pathway builder offers:

```
Add node → Binning →
  ○ Fine classing (quantile)       # existing FineClassingNode
  ● Optimal binning                # new AutoBinningFitNode (requires optbinning)
  ○ Manual bins                    # existing ManualBinningNode
```

---

## Risk register (codebase-specific)

| Risk | Concern | Mitigation |
|---|---|---|
| `SCHEMA_BIN_DEFINITION` tight coupling | Existing bin schema expects `good_count`, `bad_count`, `row_count`. OptBinning produces `Event`, `Non-event`, `Count`. | Adapter maps columns. Field names differ but semantics match (Event→bad_count, Non-event→good_count). |
| Cardre WOE ≠ optbinning WOE | Different WOE formula / smoothing. | Cardre owns WOE via `CalculateWoeIvNode`. Optbinning WOE stored as reference only. MVP tests do NOT assert WOE equivalence. |
| `ManualBinningNode` field expectations | Manual binning reads `"kind": "numeric"\|"categorical"`. | Adapter uses same kind labels. Verified in Batch 5 tests. |
| OR-Tools binary dependency | Platform-specific wheels. | Pin to wheel-providing version. Test on target platforms. No silent solver fallback. |
| `special_codes` param shape | No per-variable metadata node exists. | Accept flat dict in auto-binning params for MVP. Add `VariableMetadataNode` post-MVP (Phase 3b). |
| Single backend, no Protocol needed | Full `BinningEngine` Protocol is over-engineering for one backend. | Use simple adapter module. Only introduce Protocol when a second backend (e.g. quantile) is migrated onto it. |
| Manual override recounting | Overrides that change bin membership need data access. | Split actions into metadata-only and data-recount. Recount actions access training data and mark downstream stale. |
