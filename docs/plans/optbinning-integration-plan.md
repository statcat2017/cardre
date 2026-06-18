# Implementation plan: add optbinning to Cardre

## 1. Product decision

### Goal

Add Optimal Binning as a selectable binning method in Cardre's scorecard pathway.

The user should be able to:

1. import data;
2. define target and sample splits;
3. select variables;
4. choose Optimal Binning as an auto-binning method;
5. configure sensible scorecard-style constraints;
6. run the binning fit on train only;
7. inspect WOE/IV/event-rate tables;
8. manually override bins where required;
9. apply frozen bin definitions to train/test/OOT;
10. continue into variable selection, logistic regression, score scaling, validation, and audit export.

### Key principle

Use optbinning for bin discovery and WOE/statistical artefacts, not for owning Cardre's whole scorecard workflow.

OptBinning has a Scorecard class that combines a BinningProcess, estimator, and score scaling, but Cardre should not use that as the primary launch path because Cardre's value is visible, branchable, manually editable, reproducible modelling. The optbinning Scorecard class can be a future advanced/backend option, but the MVP should keep model fitting and score scaling as separate Cardre nodes. OptBinning's Scorecard expects a BinningProcess and an estimator with methods such as fit, predict, predict_proba, and coef\_, and supports scaling methods such as pdo_odds and min_max; useful later, but too opaque for Cardre's first implementation.

## 2. Scope

### MVP scope

Implement:

| Area | MVP decision |
|---|---|
| Target type | Binary only |
| Variable types | Numerical and categorical |
| Binning engine | optbinning OptimalBinning per variable, optionally wrapped into a Cardre-level multi-variable runner |
| Transform metric | WOE, with optional event rate / bin index / bin label outputs |
| Train/test/OOT | Fit on train only, apply frozen bins to train/test/OOT |
| Manual editing | Cardre-native manual bin review after optbinning fit |
| Special codes | Supported |
| Missing values | Supported |
| Monotonicity | None / auto / ascending / descending initially |
| Pre-binning | CART and quantile initially |
| Variable selection | Produce IV/quality metrics, but keep formal variable selection as a separate Cardre node |
| Scorecard class | Not used for MVP |
| Export | Include optbinning version, parameters, splits, WOE table, override history, and hashes |

OptBinning supports binary, continuous, and multiclass targets, but binary should be the Cardre MVP because that matches standard application scorecard development and keeps the UX coherent.

### Post-MVP placeholders

Add "coming soon" placeholders for:

| Feature | Reason to defer |
|---|---|
| Continuous target binning | Useful for LGD/EAD-type modelling but not core first scorecard path |
| Multiclass target binning | Less central to standard binary default scorecards |
| MDLP pre-binning | Supported by optbinning but not needed on day one |
| Uniform pre-binning | Easy later option |
| Peak/valley/concave/convex monotonic trends | Powerful but too much UI complexity initially |
| P-value constraints | Add after basic binning is stable |
| Event-rate difference constraints | Same |
| 2D optimal binning | Interesting challenger/interaction feature later |
| Streaming / sketch binning | Future large-data mode |
| optbinning Scorecard node | Possible advanced "library scorecard" branch later |

OptBinning's binary OptimalBinning API already includes CART, MDLP, quantile, and uniform pre-binning, several solvers, IV/JS/Hellinger/triangular divergence objectives, min/max bin constraints, monotonic trends, p-value constraints, special codes, categorical cutoffs, unknown-category handling, and solver time limits. Cardre should expose only the safest subset first.

## 3. Architecture

### 3.1 Add a binning engine abstraction

Do not scatter optbinning imports through the engine.

Create a generic backend interface:

```python
# cardre/engine/binning/base.py
from dataclasses import dataclass
from typing import Protocol, Sequence, Mapping, Any
import pandas as pd

@dataclass(frozen=True)
class BinningFitRequest:
    dataset_id: str
    train_frame_path: str
    target: str
    variables: list[str]
    variable_types: dict[str, str]  # "numerical" | "categorical"
    special_codes: dict[str, list[Any]]
    sample_weight: str | None
    params: Mapping[str, Any]

@dataclass(frozen=True)
class BinningFitResult:
    engine_name: str
    engine_version: str
    variable_results: dict[str, "VariableBinningResult"]
    warnings: list[str]
    artefact_paths: dict[str, str]
    manifest: dict[str, Any]

class BinningEngine(Protocol):
    name: str
    def fit(self, request: BinningFitRequest) -> BinningFitResult:
        ...
    def apply(self, frozen_spec: "FrozenBinningSpec", frame: pd.DataFrame) -> "BinningApplyResult":
        ...
```

Then implement:

```
cardre/engine/binning/
  base.py
  quantile.py
  optbinning_engine.py
  manual.py
```

This gives Cardre:

- one UI model for binning methods;
- one node contract;
- one persistence format;
- freedom to replace or supplement optbinning later.

### 3.2 Use per-variable OptimalBinning first

Although optbinning has BinningProcess, the first Cardre implementation should use one OptimalBinning object per variable.

Reason:

- easier to store per-variable solver status;
- easier to parallelise later;
- easier to let users rerun one variable;
- easier to explain failure/warning states;
- easier to convert optbinning output into Cardre-native editable bin specs;
- easier to avoid tight coupling to optbinning's full multi-variable object lifecycle.

OptBinning's BinningProcess is still useful later for batch fitting, variable-selection criteria, and pipeline-style transforms. It can fit all variables and transform using WOE/event-rate/bin metrics, and it supports variable-selection criteria. But for Cardre's manual review model, a per-variable adapter gives more control.

### 3.3 Node model changes

Add these node types:

- `auto_binning_fit`
- `binning_review`
- `binning_apply`

Cardre's pathway becomes:

```
Import
  ↓
Profile
  ↓
Validate Target
  ↓
Split Sample
  ↓
Auto Binning Fit
  ↓
Binning Review / Manual Overrides
  ↓
Apply Binning
  ↓
WOE Dataset
  ↓
Variable Selection
  ↓
Logistic Regression
  ↓
Score Scaling
  ↓
Validation
  ↓
Audit Export
```

The important distinction:

- `auto_binning_fit` is an estimation node.
- `binning_review` is a refinement node.
- `binning_apply` is a deterministic transform node.

That distinction is crucial for audit.

## 4. Dependency and packaging plan

### 4.1 Add optional dependency

PyPI currently lists optbinning 0.21.0, released October 26, 2025, under Apache 2.0. It is small itself, but it depends on numerical/scientific packages and OR-Tools; the GitHub README lists dependencies including numpy, pandas, scipy, scikit-learn, ropwr, matplotlib, and OR-Tools.

Add it as an optional engine dependency:

```toml
[project.optional-dependencies]
optimal-binning = [
  "optbinning==0.21.0"
]
```

For the desktop distribution, I would bundle it by default once tested. For developer installs, allow:

```
pip install -e ".[optimal-binning]"
```

### 4.2 Engine capability detection

At app startup, expose engine availability:

```python
def get_binning_capabilities() -> dict:
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
    except Exception as exc:
        return {
            "optimal_binning": {
                "available": False,
                "reason": str(exc),
            }
        }
```

In the UI:

- show Optimal Binning as available if installed;
- otherwise show it disabled with a useful message;
- never fail the whole app because optbinning is unavailable.

## 5. Backend implementation

### 5.1 Parameter schema

Create a Cardre-native parameter schema. Do not mirror every optbinning option in the UI.

```json
{
  "method": "optimal_binning",
  "engine": "optbinning",
  "target_type": "binary",
  "prebinning_method": "cart",
  "solver": "cp",
  "divergence": "iv",
  "max_n_prebins": 20,
  "min_prebin_size": 0.05,
  "min_n_bins": null,
  "max_n_bins": 6,
  "min_bin_size": 0.03,
  "min_bin_n_event": 20,
  "min_bin_n_nonevent": 20,
  "monotonic_trend": "auto",
  "special_codes_policy": "from_variable_metadata",
  "cat_cutoff": 0.01,
  "cat_unknown": null,
  "metric": "woe",
  "metric_missing": "empirical",
  "metric_special": "empirical",
  "time_limit": 100
}
```

#### MVP UI parameters

Show these in the main panel:

| UI label | Internal parameter | Default |
|---|---|---|
| Pre-binning method | prebinning_method | cart |
| Maximum pre-bins | max_n_prebins | 20 |
| Minimum pre-bin size | min_prebin_size | 0.05 |
| Maximum final bins | max_n_bins | 6 |
| Minimum bin size | min_bin_size | 0.03 |
| Minimum events per bin | min_bin_n_event | 20 |
| Minimum non-events per bin | min_bin_n_nonevent | 20 |
| Monotonic trend | monotonic_trend | auto |
| Rare-category cutoff | cat_cutoff | 0.01 |
| Missing WOE treatment | metric_missing | empirical |
| Special-code WOE treatment | metric_special | empirical |
| Time limit per variable | time_limit | 100 |

Hide these under "Advanced":

- solver;
- divergence;
- p-value constraint;
- event-rate difference;
- gamma;
- split digits;
- class weight;
- user splits;
- fixed splits.

OptBinning's binary transform supports WOE, event rate, indices, and bin labels, and supports metric_missing and metric_special values including empirical treatment.

### 5.2 Engine adapter

Initial adapter:

```python
# cardre/engine/binning/optbinning_engine.py
from __future__ import annotations
from dataclasses import asdict
from importlib.metadata import version
from typing import Any
import pandas as pd
from cardre.engine.binning.base import (
    BinningFitRequest,
    BinningFitResult,
    VariableBinningResult,
)

class OptBinningEngine:
    name = "optbinning"

    def fit(self, request: BinningFitRequest) -> BinningFitResult:
        from optbinning import OptimalBinning

        df = pd.read_parquet(request.train_frame_path)
        y = df[request.target]
        sample_weight = (
            df[request.sample_weight]
            if request.sample_weight is not None
            else None
        )

        variable_results: dict[str, VariableBinningResult] = {}
        warnings: list[str] = []

        for variable in request.variables:
            x = df[variable]
            dtype = request.variable_types[variable]
            params = self._build_variable_params(
                variable=variable,
                dtype=dtype,
                request=request,
            )
            optb = OptimalBinning(**params)
            try:
                optb.fit(x.values, y.values, sample_weight=sample_weight)
                result = self._extract_variable_result(variable, dtype, optb)
                variable_results[variable] = result
            except Exception as exc:
                warnings.append(f"{variable}: optbinning failed: {exc}")
                variable_results[variable] = self._failed_result(variable, dtype, exc)

        manifest = {
            "engine": "optbinning",
            "engine_version": version("optbinning"),
            "request": asdict(request),
            "variable_count": len(request.variables),
            "succeeded": [
                k for k, v in variable_results.items()
                if v.status in {"OPTIMAL", "FEASIBLE"}
            ],
            "failed": [
                k for k, v in variable_results.items()
                if v.status == "FAILED"
            ],
        }

        return BinningFitResult(
            engine_name="optbinning",
            engine_version=version("optbinning"),
            variable_results=variable_results,
            warnings=warnings,
            artefact_paths={},
            manifest=manifest,
        )

    def _build_variable_params(
        self,
        variable: str,
        dtype: str,
        request: BinningFitRequest,
    ) -> dict[str, Any]:
        p = dict(request.params)
        return {
            "name": variable,
            "dtype": dtype,
            "prebinning_method": p.get("prebinning_method", "cart"),
            "solver": p.get("solver", "cp"),
            "divergence": p.get("divergence", "iv"),
            "max_n_prebins": p.get("max_n_prebins", 20),
            "min_prebin_size": p.get("min_prebin_size", 0.05),
            "min_n_bins": p.get("min_n_bins"),
            "max_n_bins": p.get("max_n_bins"),
            "min_bin_size": p.get("min_bin_size"),
            "min_bin_n_event": p.get("min_bin_n_event"),
            "min_bin_n_nonevent": p.get("min_bin_n_nonevent"),
            "monotonic_trend": p.get("monotonic_trend", "auto"),
            "cat_cutoff": p.get("cat_cutoff") if dtype == "categorical" else None,
            "cat_unknown": p.get("cat_unknown") if dtype == "categorical" else None,
            "special_codes": request.special_codes.get(variable),
            "time_limit": p.get("time_limit", 100),
            "verbose": False,
        }
```

### 5.3 Extract variable result

Define a Cardre result independent of optbinning:

```python
@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str
    splits: list[Any]
    bins: list["BinningBin"]
    totals: dict[str, float]
    metrics: dict[str, float]
    warnings: list[str]
    raw_engine_payload: dict[str, Any] | None

@dataclass(frozen=True)
class BinningBin:
    bin_id: str
    label: str
    kind: str  # regular | missing | special | unknown
    lower: float | None
    upper: float | None
    categories: list[str] | None
    count: int
    count_event: int
    count_nonevent: int
    event_rate: float
    woe: float
    iv: float
```

Extraction method:

```python
def _extract_variable_result(self, variable: str, dtype: str, optb) -> VariableBinningResult:
    table = optb.binning_table.build()
    splits = optb.splits.tolist() if hasattr(optb.splits, "tolist") else list(optb.splits)
    bins = convert_optbinning_table_to_cardre_bins(
        variable=variable,
        dtype=dtype,
        table=table,
        splits=splits,
    )
    totals = {
        "count": int(table["Count"].sum()) if "Count" in table else None,
    }
    metrics = extract_iv_gini_js_from_table(table)
    return VariableBinningResult(
        variable=variable,
        dtype=dtype,
        status=optb.status,
        splits=splits,
        bins=bins,
        totals=totals,
        metrics=metrics,
        warnings=[],
        raw_engine_payload=optb.to_dict(),
    )
```

OptBinning exposes solver status, splits, binning_table, to_dict, to_json, and transform, which makes it practical to convert its fitted result into a Cardre-owned artefact.

## 6. Persistence model

### 6.1 Store Cardre-native bin specs

Do not persist only a pickled optbinning object.

Persist:

```
runs/
  {run_id}/
    manifest.json
    nodes/
      {node_id}/
        params.json
        optbinning_manifest.json
        variable_summary.parquet
        bin_table.parquet
        frozen_binning_spec.json
        warnings.json
```

The important artefact is:

```json
{
  "schema_version": "cardre.binning_spec.v1",
  "source_node_id": "node_auto_bin_001",
  "review_node_id": "node_review_001",
  "engine": {
    "name": "optbinning",
    "version": "0.21.0"
  },
  "target": {
    "name": "bad_flag",
    "event_value": 1,
    "nonevent_value": 0
  },
  "fit_sample": {
    "sample_role": "train",
    "dataset_snapshot_hash": "..."
  },
  "variables": {
    "age": {
      "dtype": "numerical",
      "status": "accepted",
      "monotonic_trend": "auto",
      "bins": [
        {
          "bin_id": "age_001",
          "kind": "regular",
          "lower": null,
          "upper": 25.5,
          "label": "(-inf, 25.5)",
          "woe": -0.391,
          "event_rate": 0.128,
          "count": 1234,
          "count_event": 158,
          "count_nonevent": 1076,
          "iv": 0.012
        }
      ],
      "missing_bin": {
        "kind": "missing",
        "woe": 0.0,
        "event_rate": 0.095
      },
      "special_bins": [],
      "override_history": []
    }
  }
}
```

### 6.2 Store original optbinning output as secondary evidence

Persist the raw optbinning to_dict() output separately, because release notes say JSON save support was added for optimal binning objects in v0.19.0. But Cardre's scoring/apply path should use the Cardre-native frozen spec, not rely on rehydrating optbinning internals.

Reason:

- audit stability;
- future-proofing if optbinning changes;
- easier SQL/Python scoring export;
- easier manual edits;
- easier cross-language scoring.

## 7. Apply transform design

### 7.1 Cardre-owned transform

Even though optbinning can transform directly to WOE, Cardre should implement its own deterministic apply function from FrozenBinningSpec.

OptBinning's transform is useful for comparison and tests, but the production Cardre apply node should use the frozen JSON spec.

Why:

- manual edits may not map cleanly back into optbinning objects;
- SQL export needs explicit boundaries;
- audit pack should be explainable without Python object state;
- scoring code should not require optbinning installed;
- train/test/OOT transformations must be replayable exactly.

### 7.2 Apply outputs

For each selected variable, output:

```
{variable}__bin_id
{variable}__bin_label
{variable}__woe
{variable}__event_rate
```

Example:

```
age__bin_id
age__bin_label
age__woe
age__event_rate
```

The downstream logistic regression node should consume `__woe` columns by default.

### 7.3 Unknown category handling

For categorical variables:

- known categories map to frozen category groups;
- missing maps to missing bin;
- special code maps to special bin;
- unseen category maps to unknown bin.

Default MVP behaviour:

```
unknown categorical value -> WOE 0.0, bin label "Unknown"
```

This matches optbinning's default behaviour for unseen categories under WOE, where unknown category WOE follows the mean-event-rate rule and returns zero WOE when metric is WOE.

## 8. Manual review and override workflow

### 8.1 Add BinningReviewNode

The review node takes auto_binning_fit output and creates a frozen Cardre bin spec.

The user can:

- accept a variable unchanged;
- reject a variable;
- merge adjacent numerical bins;
- adjust numerical split points;
- group or ungroup categorical levels;
- isolate missing;
- isolate special codes;
- override WOE treatment for missing/special/unknown;
- mark a variable as "policy excluded";
- enter override reasons.

Every manual change must produce an immutable override event:

```json
{
  "timestamp": "2026-06-18T12:00:00-03:00",
  "user_action": "merge_bins",
  "variable": "age",
  "before": ["(-inf, 25.5)", "[25.5, 37.0)"],
  "after": ["(-inf, 37.0)"],
  "reason": "Sparse event count in youngest bin; merged to satisfy minimum event-count standard.",
  "warnings_acknowledged": [
    "Monotonicity changed from ascending to non-monotonic"
  ]
}
```

### 8.2 Warnings

Show warnings prominently:

| Warning | Trigger |
|---|---|
| Pure bin risk | zero events or zero non-events |
| Sparse bin | below configured minimum count |
| Non-monotonic WOE | WOE pattern reverses |
| Missing high risk | missing bin event rate materially different |
| Special-code high risk | special code materially different |
| Solver not optimal | status not OPTIMAL |
| Variable failed | optbinning exception |
| High cardinality categorical | many categories or large "other" bin |
| Train/test drift | bin distribution shifts across samples |

OptBinning notes that pure bins produce infinite WOE/IV and that its pre-binning refinement merges pure prebins to avoid zero event or non-event counts, which is useful but should not remove Cardre's own warning layer.

## 9. API endpoints

Assuming Cardre's local FastAPI sidecar:

### 9.1 Capabilities

```
GET /api/binning/engines
```

Response:

```json
{
  "engines": [
    {
      "id": "quantile",
      "label": "Quantile binning",
      "available": true
    },
    {
      "id": "optbinning",
      "label": "Optimal binning",
      "available": true,
      "version": "0.21.0",
      "target_types": ["binary"]
    }
  ]
}
```

### 9.2 Fit node

```
POST /api/runs/{run_id}/nodes/auto-binning-fit
```

Request:

```json
{
  "input_node_id": "split_001",
  "target": "bad_flag",
  "sample": "train",
  "variables": ["age", "income", "arrears_count", "employment_status"],
  "engine": "optbinning",
  "params": {
    "prebinning_method": "cart",
    "max_n_prebins": 20,
    "max_n_bins": 6,
    "min_bin_size": 0.03,
    "monotonic_trend": "auto"
  }
}
```

Response:

```json
{
  "node_id": "auto_bin_001",
  "status": "queued"
}
```

### 9.3 Variable bin table

```
GET /api/runs/{run_id}/nodes/{node_id}/variables/{variable}/bin-table
```

Response:

```json
{
  "variable": "age",
  "status": "OPTIMAL",
  "iv": 0.142,
  "bins": [
    {
      "label": "(-inf, 25.5)",
      "count": 1234,
      "event_rate": 0.128,
      "woe": -0.391,
      "iv": 0.012
    }
  ]
}
```

### 9.4 Save review

```
POST /api/runs/{run_id}/nodes/binning-review
```

Request:

```json
{
  "source_node_id": "auto_bin_001",
  "actions": [
    {
      "variable": "age",
      "action": "merge_bins",
      "bin_ids": ["age_001", "age_002"],
      "reason": "Sparse event count"
    }
  ]
}
```

### 9.5 Apply bins

```
POST /api/runs/{run_id}/nodes/binning-apply
```

Request:

```json
{
  "review_node_id": "bin_review_001",
  "samples": ["train", "test", "oot"],
  "outputs": ["woe", "bin_id", "bin_label", "event_rate"]
}
```

## 10. UI implementation

### 10.1 Node creation UI

In the pathway builder:

```
Add node -> Binning -> Auto binning
```

Options:

```
Method
  ○ Quantile binning
  ● Optimal binning
  ○ Manual bins
  ○ Decision tree binning         Coming soon
  ○ MDLP                          Coming soon
```

### 10.2 Optimal binning configuration panel

Use progressive disclosure:

**Basic**

| Field | Options |
|---|---|
| Pre-binning method | CART / Quantile |
| Maximum final bins | 6 |
| Minimum bin size | 3% |
| Minimum events/bin | 20 |
| Minimum non-events/bin | 20 |
| Monotonic trend | Auto / None / Ascending / Descending |
| Rare category cutoff | 1% |

**Advanced**

| Field | Options |
|---|---|
| Solver | CP |
| Divergence | IV |
| Maximum pre-bins | 20 |
| Minimum pre-bin size | 5% |
| Time limit | 100 sec / variable |
| Missing WOE | Empirical / 0 / custom |
| Special-code WOE | Empirical / 0 / custom |

### 10.3 Review screen

For each variable:

```
Variable: age
Status: OPTIMAL
IV: 0.142
Trend: ascending
Warnings: sparse first bin
[chart: event rate by bin]
[chart: WOE by bin]
Table:
Bin | Count | % | Events | Non-events | Event rate | WOE | IV | Actions
```

Actions:

- Accept variable;
- Exclude variable;
- Merge selected bins;
- Edit split;
- Mark as special;
- Add override reason;
- Compare train/test/OOT distribution once apply is available.

### 10.4 Variable list sidebar

Show:

```
age                 IV 0.142   OPTIMAL   Accepted
income              IV 0.087   OPTIMAL   Needs review
postcode_region     IV 0.044   FAILED    Review
employment_status   IV 0.031   OPTIMAL   Accepted
```

Filter by:

- failed;
- high IV;
- warnings;
- needs review;
- accepted;
- excluded.

## 11. Validation and governance

### 11.1 Leakage control

Enforce:

`auto_binning_fit` may only use train sample

The node should fail if the user tries to fit on full data while a train/test split exists.

The apply node can transform train/test/OOT, but it must use frozen train-fitted bins.

### 11.2 Run manifest

Every optbinning fit node stores:

```json
{
  "node_type": "auto_binning_fit",
  "engine": "optbinning",
  "engine_version": "0.21.0",
  "python_version": "3.12.x",
  "package_lock_hash": "...",
  "input_dataset_hash": "...",
  "train_sample_hash": "...",
  "target": "bad_flag",
  "event_value": 1,
  "parameters": {
    "prebinning_method": "cart",
    "solver": "cp",
    "divergence": "iv",
    "max_n_prebins": 20,
    "max_n_bins": 6,
    "min_bin_size": 0.03,
    "monotonic_trend": "auto",
    "time_limit": 100
  },
  "variables_attempted": 128,
  "variables_succeeded": 121,
  "variables_failed": 7,
  "created_artifacts": [
    "variable_summary.parquet",
    "bin_table.parquet",
    "frozen_binning_spec.json"
  ]
}
```

### 11.3 Audit export section

The model development report should include:

> **Binning Methodology**
>
> Automated binning was performed using the optbinning engine through Cardre's
> Auto Binning node. The algorithm was run on the training sample only. The
> resulting bin definitions were reviewed in Cardre's Binning Review node, where
> manual overrides were recorded with reason codes. Frozen bin definitions were
> then applied without refitting to train, test, and out-of-time samples.

Include tables:

- variable-level IV summary;
- bin-level WOE table;
- manual override log;
- rejected variable list;
- warnings and acknowledgements;
- sample distribution by bin across train/test/OOT.

## 12. Testing plan

### 12.1 Unit tests

**Parameter mapping**

Test that Cardre parameters map correctly to optbinning:

- prebinning_method
- max_n_prebins
- min_prebin_size
- min_n_bins
- max_n_bins
- min_bin_size
- min_bin_n_event
- min_bin_n_nonevent
- monotonic_trend
- special_codes
- cat_cutoff
- cat_unknown
- time_limit

**Numerical variable fit**

Use a tiny binary dataset and assert:

- status captured;
- splits captured;
- bin table exists;
- WOE values finite;
- manifest records version and params.

**Categorical variable fit**

Assert:

- category groups captured;
- rare categories handled;
- unseen category maps to unknown during Cardre apply.

**Missing/special values**

Assert:

- missing bin exists;
- special-code bin exists;
- metric_missing and metric_special behaviour is recorded.

**Failed variable**

Feed an invalid variable and assert:

- node does not crash whole run;
- variable result status is FAILED;
- warning is shown;
- other variables continue.

### 12.2 Golden tests

Create fixed fixture datasets:

```
fixtures/
  binning_binary_small.parquet
  binning_binary_categorical.parquet
  binning_binary_special_codes.parquet
```

Expected artefacts:

```
expected/
  binning_binary_small_variable_summary.json
  binning_binary_small_bin_table.json
```

Golden tests should compare:

- number of bins;
- split values within tolerance;
- monotonicity flag;
- WOE transform results;
- exported JSON schema.

### 12.3 Apply equivalence tests

For unedited bins:

1. fit with optbinning;
2. transform using optbinning;
3. transform using Cardre frozen spec;
4. compare WOE outputs.

This proves the Cardre-owned apply logic matches optbinning for the initial unedited case.

### 12.4 Manual override tests

Test:

- merge adjacent numeric bins;
- move numeric split;
- group categorical levels;
- isolate missing;
- reject variable;
- require override reason;
- recalculate WOE/IV after override;
- downstream apply uses edited bins, not original optbinning bins.

### 12.5 Integration tests

Full pathway:

```
Import -> Split -> Optimal Binning -> Review -> Apply -> Logistic Regression -> Score Scaling -> Validation -> Audit Export
```

Assert:

- all artefacts are produced;
- downstream node detects staleness if binning params change;
- audit export includes optbinning metadata;
- replay reproduces same frozen bin spec from same data and params.

## 13. Performance plan

### 13.1 MVP

Run variables sequentially first. Keep the UI responsive through existing background worker status.

Per-variable statuses:

- queued
- running
- succeeded
- failed
- cancelled

### 13.2 Later parallelisation

Add n_jobs at the Cardre runner level, not necessarily via optbinning initially.

Reason:

- easier progress reporting;
- easier cancellation;
- easier per-variable error handling;
- easier memory limits.

### 13.3 Large data

OptBinning has disk-based BinningProcess methods for fitting from CSV or Parquet and transforming in chunks, which could be useful later for large local datasets. But for MVP, keep Cardre's existing Parquet snapshot flow and load the selected training columns only.

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Risk 1:** dependency heaviness (scientific packages + OR-Tools) | optional dependency in dev; bundled and pinned in desktop builds; capability detection; clear error if unavailable |
| **Risk 2:** too many parameters | small "Basic" UI; advanced drawer; presets; safe defaults; parameter manifest for audit |
| **Risk 3:** manual edits break optbinning object semantics | convert optbinning output into Cardre-native frozen bin specs; Cardre owns edited bin definitions; optbinning object is evidence, not the scoring source of truth |
| **Risk 4:** solver statuses vary by variable | store status per variable; allow failed variables to be excluded or rerun; expose "solver not optimal" warnings; do not block the whole node unless all variables fail |
| **Risk 5:** reproducibility | pin optbinning version; record Python/package lock; record dataset hash; record train sample hash; record params; persist frozen bins; use Cardre-owned apply logic |

## 15. Suggested delivery phases

### Phase 1 — engine skeleton

**Deliverables:**

- BinningEngine interface;
- QuantileBinningEngine migrated to interface if it already exists;
- OptBinningEngine stub;
- /api/binning/engines;
- UI shows "Optimal binning" as available/unavailable.

**Acceptance criteria:**

- app starts with or without optbinning installed;
- capabilities endpoint reports availability and version.

### Phase 2 — fit numerical variables

**Deliverables:**

- fit numerical variables using OptimalBinning;
- parameter mapping;
- solver status capture;
- splits capture;
- bin table extraction;
- variable summary artefact.

**Acceptance criteria:**

- user can run optimal binning on numerical variables;
- bin table appears in UI;
- manifest records engine version and params.

### Phase 3 — categorical, missing, special codes

**Deliverables:**

- categorical dtype support;
- cat_cutoff;
- unknown-category policy;
- missing bin support;
- special code mapping from Cardre variable metadata.

**Acceptance criteria:**

- categorical variables produce grouped bins;
- missing/special values appear separately;
- unseen categories do not crash apply.

### Phase 4 — Cardre frozen spec and apply

**Deliverables:**

- FrozenBinningSpec schema;
- Cardre-native WOE transform;
- apply node for train/test/OOT;
- output Parquet with WOE/bin columns;
- equivalence tests against optbinning for unedited bins.

**Acceptance criteria:**

- downstream logistic regression can consume WOE columns;
- apply uses train-fitted bins only;
- test/OOT are transformed without refitting.

### Phase 5 — manual review

**Deliverables:**

- review node;
- accept/reject variable;
- merge bins;
- group categorical levels;
- override reason logging;
- WOE/IV recalculation after edits.

**Acceptance criteria:**

- every manual edit creates immutable override history;
- edited bins are used by apply;
- audit export includes override log.

### Phase 6 — validation and monitoring tables

**Deliverables:**

- bin distribution by sample;
- event rate by sample;
- PSI-style bin stability;
- WOE monotonicity check;
- sparse-bin warning;
- train/test/OOT comparison panel.

**Acceptance criteria:**

- user can see whether bins are stable outside train;
- warnings appear before model fitting.

### Phase 7 — audit export

**Deliverables:**

- methodology text;
- parameter manifest;
- variable summary;
- bin tables;
- override log;
- rejected variable list;
- scoring transform spec;
- Python/SQL WOE scoring export.

**Acceptance criteria:**

- audit pack contains enough information to reproduce binning without re-running optbinning;
- exported scoring code does not require optbinning.

## 16. Recommended presets

### Conservative scorecard preset

```json
{
  "prebinning_method": "cart",
  "solver": "cp",
  "divergence": "iv",
  "max_n_prebins": 20,
  "max_n_bins": 6,
  "min_prebin_size": 0.05,
  "min_bin_size": 0.03,
  "min_bin_n_event": 30,
  "min_bin_n_nonevent": 30,
  "monotonic_trend": "auto_asc_desc",
  "cat_cutoff": 0.01,
  "metric_missing": "empirical",
  "metric_special": "empirical",
  "time_limit": 100
}
```

### Exploratory preset

```json
{
  "prebinning_method": "cart",
  "solver": "cp",
  "divergence": "iv",
  "max_n_prebins": 30,
  "max_n_bins": 8,
  "min_prebin_size": 0.03,
  "min_bin_size": 0.02,
  "min_bin_n_event": 10,
  "min_bin_n_nonevent": 10,
  "monotonic_trend": "auto",
  "cat_cutoff": 0.005,
  "metric_missing": "empirical",
  "metric_special": "empirical",
  "time_limit": 100
}
```

### Simple demo preset

```json
{
  "prebinning_method": "quantile",
  "solver": "cp",
  "divergence": "iv",
  "max_n_prebins": 10,
  "max_n_bins": 5,
  "min_prebin_size": 0.05,
  "min_bin_size": 0.05,
  "monotonic_trend": "auto",
  "cat_cutoff": 0.02,
  "time_limit": 30
}
```

## 17. Definition of done

Optbinning support is "done" for MVP when Cardre can:

1. detect optbinning availability;
2. expose Optimal Binning in the binning node UI;
3. fit numerical and categorical variables on train only;
4. capture solver status, splits, WOE, IV, event rates, counts, missing/special bins, and warnings;
5. persist Cardre-native frozen bin specs;
6. allow manual review and override with reason logging;
7. apply bins deterministically to train/test/OOT;
8. feed WOE columns into logistic regression;
9. include all binning details in the audit export;
10. replay the pathway from the same input snapshot and reproduce equivalent binning artefacts.

The strongest implementation shape is therefore:

**optbinning as Cardre's first serious supervised-binning engine, Cardre as the governed scorecard workflow around it.**
