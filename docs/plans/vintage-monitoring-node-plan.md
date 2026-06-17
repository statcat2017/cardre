# Vintage / Time-Series Performance Monitoring — Implementation Plan

> Derived from: Anderson Ch. 26 (Portfolio Monitoring), Basel IFRS 9 requirements.
> Aligned with Cardre's existing PSI computation in `ValidationMetricsNode` and the audit pack export.

## 1. Problem

The algo-risk-credit skill states:
> "Vintage analysis: Default rates vary by economic conditions. A 2019-trained model may not predict well in a recession. Track model performance by vintage."

Cardre currently computes PSI (population stability index) as a single snapshot — comparing score distributions between train, test, and OOT at model build time. There is no:
- **Time-series tracking**: PSI over successive time periods after deployment
- **Vintage segmentation**: group accounts by origination period, track performance per vintage
- **Drift alerting**: automatic flagging when PSI exceeds thresholds over time
- **Performance degradation**: AUC/Gini trending downward over calendar time

This is fundamentally about **post-deployment monitoring**, not build-time validation. The design must account for data arriving over time, not just a static holdout sample.

## 2. Design Decision: Separate Monitoring Store

Post-deployment monitoring operates on data that arrives *after* the model is deployed. This data has a different lifecycle than build-time artifacts:

- Build-time: train/test/oot are static, immutable, hashed
- Monitoring: new batches arrive periodically (monthly/quarterly), are scored, and compared against the build baseline

**Chosen: Monitor as a new run concept within the existing project.**

Each monitoring period is a `Run` attached to the deployed plan version. It uses a special monitoring node that:
1. Consumes a new batch of scored data (with actual outcomes if available)
2. Computes period-specific metrics
3. Compares against the build-time baseline
4. Accumulates into vintage cohorts

This reuses the existing `Run` / `RunStepRecord` / artifact infrastructure without a separate database.

## 3. Pipeline Position

Monitoring is **not a step in the build pathway**. It's a separate workflow that runs repeatedly against the same plan version:

```
Deployment:
  ... → score-scaling → build-summary-report → [deploy]

Monitoring (monthly, not a pathway step):
  Monitor Node ← (new scored batch + new outcomes)
     → reports PSI, AUC drift, vintage curves
     → writes monitoring-run artifacts under the same plan
```

## 4. Node Specification

### `ModelPerformanceMonitorNode`

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.model_performance_monitor` |
| `version` | `1` |
| `category` | `apply` |
| `input_roles` | `["model", "scorecard", "report"]` |
| `output_roles` | `["report"]` |

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `period_label` | str | (required) | E.g. "2025-Q1", "2025-03". Free-text, but should be sortable |
| `period_start` | str | (required) | ISO date of monitoring period start |
| `period_end` | str | (required) | ISO date of monitoring period end |
| `origination_column` | str | `None` | Column with origination/vintage date. Used for vintage segmentation |
| `baseline_period_label` | str | `"build"` | Label for the build-time baseline period |
| `psi_threshold_warn` | float | `0.10` | PSI > this → warning |
| `psi_threshold_block` | float | `0.25` | PSI > this → critical (model may need recalibration) |
| `auc_drop_threshold` | float | `0.05` | AUC drop > this from baseline → warning |
| `min_period_observations` | int | `1000` | Minimum rows for reliable period metrics |
| `vintage_months` | int | `12` | Months to track per vintage (performance window) |

**Input artifacts:** The node must receive as input artifacts:
- Model artifact (for baseline coefficients and calibration)
- Score scaling artifact (for baseline score mapping)
- Scored datasets from previous monitoring periods (for trend computation — optional)

This is fed through a special monitoring run, not through the standard pathway. The `ProjectStore` needs a new method to create monitoring runs attached to the deployed plan version.

**Behavior:**

### 4.1 Period Metrics

For the new batch of scored data (must contain `score`, `predicted_bad_probability`, and optionally actual target):

1. Compute score distribution (mean, median, min, max, std, percentiles)
2. Compute PSI vs baseline train score distribution
3. Compute PSI vs previous monitoring period (sequential drift)
4. If actual outcomes available:
   - Compute AUC, Gini, KS
   - Compute calibration (10-bin)
   - Compare these against build-time validation metrics

### 4.2 Vintage Segmentation

If `origination_column` is provided:

1. Group observations by vintage (year-month of origination)
2. For each vintage, track:
   - Volume (number of accounts)
   - Current bad rate
   - Cumulative bad rate by months-on-books
3. Build vintage curves: bad rate vs months on book, one curve per vintage
4. Compare vintages: are newer vintages performing worse than older ones at the same age?

### 4.3 Trend Analysis

1. If prior monitoring artifacts exist, extract AUC, Gini, PSI over time
2. Fit a linear trend to AUC over time
3. Flag if negative slope is significant (p < 0.05)

### 4.4 Output Artifact

```json
{
  "schema_version": "cardre.performance_monitor.v1",
  "period": {
    "label": "2025-Q1",
    "start": "2025-01-01",
    "end": "2025-03-31"
  },
  "baseline_period": "build",
  "row_count": 15000,
  "period_metrics": {
    "score_distribution": { "mean": 620, "std": 45, ... },
    "psi_vs_baseline": 0.08,
    "psi_vs_previous": 0.03,
    "auc": 0.76,
    "auc_vs_baseline": -0.02,
    "gini": 0.52,
    "calibration_error": 0.031
  },
  "vintages": {
    "2024-Q1": {
      "volume": 3000,
      "months_on_books": 12,
      "current_bad_rate": 0.035,
      "cumulative_bad_rate_by_month": [0.005, 0.012, 0.020, ...]
    },
    "2024-Q2": {
      "volume": 2800,
      "months_on_books": 9,
      "current_bad_rate": 0.038,
      ...
    }
  },
  "flags": [
    {
      "severity": "warning",
      "code": "PSI_ELEVATED",
      "message": "PSI vs baseline = 0.08 (threshold 0.10)",
      "value": 0.08,
      "threshold": 0.10
    }
  ]
}
```

## 5. Evidence Kinds

### New EvidenceKind entries

```python
PERFORMANCE_MONITOR = "performance_monitor"
VINTAGE_CURVE = "vintage_curve"
```

### New schema constants

```python
SCHEMA_PERFORMANCE_MONITOR = "cardre.performance_monitor.v1"
SCHEMA_VINTAGE_CURVE = "cardre.vintage_curve.v1"
```

### Evidence profiles

```python
EvidenceKind.PERFORMANCE_MONITOR: _Profile(
    expected_roles={"report"},
    expected_artifact_types={"report"},
    schema_version=SCHEMA_PERFORMANCE_MONITOR,
    required_keys={"period", "period_metrics"},
),

EvidenceKind.VINTAGE_CURVE: _Profile(
    expected_roles={"report"},
    expected_artifact_types={"report"},
    schema_version=SCHEMA_VINTAGE_CURVE,
    expected_media_types={"application/vnd.apache.parquet"},
    required_columns={"vintage", "months_on_books", "bad_rate"},
),
```

## 6. Store / Run Changes

The monitoring run uses a different creation path than build runs:

```python
store.create_monitoring_run(
    plan_id=plan_id,
    plan_version_id=plan_version_id,
    period_label="2025-Q1",
    description="Q1 2025 performance monitoring",
)
```

This creates a `Run` with `run_type = "monitoring"` (new column on the `runs` table).

**Schema migration** — `runs` table:

```sql
ALTER TABLE runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'build';
```

Existing rows get `run_type = 'build'`. Monitoring runs get `run_type = 'monitoring'`.

## 7. Monitoring Workflow

The end-to-end monitoring workflow:

1. User has scored data from a new period (e.g. Q1 2025)
2. User creates a monitoring run via API:
   ```
   POST /projects/{id}/plans/{plan_id}/monitor
   {
     "period_label": "2025-Q1",
     "period_start": "2025-01-01",
     "period_end": "2025-03-31",
     "scored_dataset": { "artifact_id": "art_xxx" },
     "origination_column": "origination_date"
   }
   ```
3. Store creates the monitoring run, registers the scored dataset as input artifact
4. Executor runs `ModelPerformanceMonitorNode`:
   - Computes period metrics
   - Reads previous monitoring runs for trend
   - Writes monitor report artifact
5. API returns monitor report with flags
6. User views monitoring dashboard (frontend)

## 8. Report Bundle Integration

In `reporting/schema.py`, add:

```python
class PerformanceMonitorPeriod(BaseModel):
    label: str
    start: str
    end: str

class PerformanceMonitorMetrics(BaseModel):
    psi_vs_baseline: float | None
    auc: float | None
    auc_vs_baseline: float | None
    calibration_error: float | None

class VintageInfo(BaseModel):
    vintage_label: str
    volume: int
    bad_rate: float

class PerformanceMonitorInfo(BaseModel):
    period: PerformanceMonitorPeriod
    period_metrics: PerformanceMonitorMetrics
    flags: list[dict]
    vintages: list[VintageInfo] | None

# In ReportBundle:
performance_monitors: list[PerformanceMonitorInfo] | None = None
```

## 9. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/monitoring.py` | **CREATE** | `ModelPerformanceMonitorNode` + vintage analysis (~400 lines) |
| `cardre/nodes/__init__.py` | **MODIFY** | Import + re-export |
| `cardre/registry.py` | **MODIFY** | Register node |
| `cardre/evidence.py` | **MODIFY** | +2 EvidenceKind, +2 schema constants, +2 profiles |
| `cardre/store.py` | **MODIFY** | +`create_monitoring_run()`, +`get_monitoring_runs()` |
| `cardre/store_schema.py` | **MODIFY** | +`run_type` column on `runs` table, migration |
| `cardre/audit.py` | **MODIFY** | Optional: add `run_type` to Run-related dataclasses |
| `cardre/reporting/schema.py` | **MODIFY** | +3 Pydantic models |
| `cardre/reporting/collector.py` | **MODIFY** | +`_collect_monitoring_reports()` |
| `sidecar/routes/` | **MODIFY** | +POST endpoint for monitoring runs|
| `sidecar/models.py` | **MODIFY** | + monitoring request/response models |
| `tests/test_monitoring.py` | **CREATE** | Unit + integration tests |

## 10. Testing Strategy

### Unit tests (6 tests)

1. `test_period_psi_vs_baseline`: Two score distributions -> PSI computed correctly
2. `test_period_auc_with_actuals`: Scored data with actual outcomes -> AUC computed
3. `test_vintage_segmentation`: Data with origination dates -> grouped into correct vintage buckets
4. `test_drift_flagging`: PSI > threshold -> flag generated
5. `test_trend_detection`: Multiple prior monitor artifacts -> AUC slope computed, flagged if negative
6. `test_insufficient_data`: Fewer rows than min_period_observations -> warning, no metrics

### Integration tests (3 tests)

7. `test_monitoring_run_lifecycle`: Create plan -> run build -> deploy -> create monitoring run -> verify artifacts
8. `test_vintage_curve_output`: Vintage segmentation produces expected curve artifact
9. `test_monitoring_report_in_bundle`: Report bundle includes monitoring section when periods exist

## 11. Implementation Sequence

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Evidence types + schema constants | Tiny | — |
| 2 | Period metrics (PSI, AUC, calibration) | Medium | Phase 1 |
| 3 | Vintage segmentation | Medium | Phase 1 |
| 4 | Drift flagging + trend analysis | Small | Phase 2 |
| 5 | Store + run_type schema migration | Small | Phase 1 |
| 6 | Monitoring run API | Small | Phase 5 |
| 7 | Reporting integration | Small | Phase 2-3 |
| 8 | Tests | Medium | Phase 2-7 |

**MVP:** Period metrics (PSI + AUC) only, no vintage segmentation, no trend analysis. Manual monitoring runs via API. Ships as optional workflow separate from build pathway.
