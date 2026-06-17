# Automated Verification Gates — Implementation Plan

> Part of: Phase 3 of the algo-risk-credit skill (Verification).
> Aligned with Cardre's blocker/warning readiness system in `reporting/readiness.py`.

## 1. Problem

The algo-risk-credit skill requires verification gates:

- **AUC > 0.70**: minimum discriminative power
- **Calibration acceptable**: predicted PD matches actual default rates
- **No discriminatory bias**: parity across protected groups

Currently `ValidationMetricsNode` computes these metrics but **never blocks** a model from proceeding. A model with AUC=0.55 or massive calibration deviation still passes to champion assignment and audit pack export. The skill explicitly treats these as **gates** — the model must pass to be deployable.

Cardre already has a blocker/warning system in `reporting/readiness.py` for report generation. This plan extends that pattern to the **execution layer**: a new node type that checks metrics against thresholds and produces structured pass/fail evidence.

## 2. Design Decision: Node vs Readiness-Only

**Chosen: Node in the pathway** (not just a readiness check).

Rationale:
- Gating at report time (readiness checks) is too late — the user has already invested compute in fitting the model
- A node produces persistent evidence artifacts that are part of the audit trail
- The gate can be configured per-project (different thresholds for different portfolios)
- Readiness checks are redundant with node evidence — if the gate node passed, readiness passes

## 3. Pipeline Position

Placed after all metrics are computed, before the model is accepted:

```
... → validation-metrics → cutoff-analysis → model-governance-gate → build-summary-report → ...
                                                    ^ NEW
```

The gate node consumes all metric/cutoff/fairness report artifacts and either:
- **Passes**: allows downstream steps to proceed (build-summary-report, audit export, champion)
- **Fails with blockers**: downstream steps receive warnings or are blocked entirely
- **Fails with warnings**: downstream steps proceed but reports flag the issue

## 4. Node Specification

### `ModelGovernanceGateNode`

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.model_governance_gate` |
| `version` | `1` |
| `category` | `report` |
| `input_roles` | `["train", "test", "oot", "definition", "report"]` |
| `output_roles` | `["report"]` |

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `min_auc` | float | `0.70` | Minimum AUC on test role. `None` = skip |
| `min_auc_train` | float | `None` | Minimum AUC on train (optional, `None` = skip) |
| `max_calibration_error` | float | `0.05` | Maximum calibration error (10-bin). `None` = skip |
| `min_ps_threshold` | float | `0.05` | P-value threshold for Hosmer-Lemeshow test. `None` = skip |
| `max_approval_rate_disparity` | float | `0.10` | Max absolute approval rate difference across sensitive groups. `None` = skip |
| `max_fpr_disparity` | float | `0.10` | Max false positive rate difference across groups. `None` = skip |
| `min_group_size` | int | `30` | Minimum group size for fairness metrics |
| `sensitive_columns` | list[str] | `[]` | Column names for fairness checks. Required if fairness checks enabled |
| `gate_on` | str | `"test"` | Primary role for gate evaluation: `"test"`, `"oot"`, or `"train"` |
| `action_on_block` | str | `"warn"` | `"block"` (fail the node) or `"warn"` (produce warnings, allow downstream) |

**Behavior:**

1. Read all metric/fairness artifacts from input artifacts:
   - `VALIDATION_METRICS` — AUC, Gini, KS, calibration bins
   - `CUTOFF_ANALYSIS` — approval rates per band
   - `CALIBRATION_REPORT` — calibration error, HL test (if calibration node exists)
   - `FAIRNESS_REPORT` — group parity metrics
   - `MODELLING_METADATA` — target definition context
2. Evaluate each configured gate:

   **AUC gate** (`min_auc`):
   ```python
   if min_auc is not None:
       test_auc = metrics["metrics"][gate_on].get("auc")
       if test_auc is None:
           checks.append(Check("auc", "fail", f"No AUC available for role {gate_on!r}"))
       elif test_auc < min_auc:
           checks.append(Check("auc", "block" if action_on_block == "block" else "warn",
               f"AUC on {gate_on}={test_auc:.4f} < min_auc={min_auc}"))
       else:
           checks.append(Check("auc", "pass", f"AUC on {gate_on}={test_auc:.4f}"))
   ```

   **Calibration gate** (`max_calibration_error`):
   ```python
   # Try calibration report first, fall back to validation metrics 10-bin
   cal_artifacts = [a for a in input_artifacts if is_calibration_report]
   if cal_artifacts:
       cal_error = cal_report["calibration_error"]
   else:
       cal_bins = metrics["metrics"][gate_on]["calibration"]["bins"]
       cal_error = mean(|bin.avg_predicted - bin.actual_bad_rate|)
   if cal_error > max_calibration_error:
       checks.append(...)
   ```

   **Fairness parity gates** (`max_approval_rate_disparity`, `max_fpr_disparity`):
   Checks against fairness report group-level metrics by sensitive column.

3. Build structured gate evidence artifact

4. Determine overall status:
   - All checks pass → `status = "pass"`
   - Any block checks fail → `status = "blocked"`, node raises `GateBlockedError`
   - Only warnings → `status = "warning"`, node succeeds with warnings

5. Write gate evidence artifact (role: `"report"`)

6. Return `NodeOutput` with gate status in metrics

**Error handling:**

If `action_on_block = "block"` and any check fails:
```python
raise GateBlockedError(checks=[
    {"check": "auc", "status": "block", "message": "AUC on test=0.65 < min_auc=0.70"},
    ...
])
```

This causes the executor to record the step as `failed` with structured error details, preventing downstream steps from running.

## 5. Evidence

### New `EvidenceKind` entry

```python
MODEL_GOVERNANCE_GATE = "model_governance_gate"
```

### New schema constant

```python
SCHEMA_MODEL_GOVERNANCE_GATE = "cardre.model_governance_gate.v1"
```

### Gate evidence artifact shape

```json
{
  "schema_version": "cardre.model_governance_gate.v1",
  "overall_status": "pass",
  "gated_on_role": "test",
  "action_on_block": "warn",
  "checks": [
    {
      "check_name": "auc",
      "status": "pass",
      "message": "AUC on test=0.78 >= min_auc=0.70",
      "value": 0.78,
      "threshold": 0.70
    },
    {
      "check_name": "calibration_error",
      "status": "pass",
      "message": "Calibration error on test=0.023 <= max=0.05",
      "value": 0.023,
      "threshold": 0.05
    },
    {
      "check_name": "approval_rate_disparity",
      "status": "warn",
      "message": "Max approval rate disparity=0.08 <= max=0.10",
      "value": 0.08,
      "threshold": 0.10,
      "note": "Approaching threshold, monitor in production"
    }
  ],
  "summary": {
    "total_checks": 3,
    "passed": 2,
    "warnings": 1,
    "blocks": 0
  }
}
```

### Evidence profile

```python
EvidenceKind.MODEL_GOVERNANCE_GATE: _Profile(
    expected_roles={"report"},
    expected_artifact_types={"report"},
    schema_version=SCHEMA_MODEL_GOVERNANCE_GATE,
    required_keys={"overall_status", "checks"},
),
```

## 6. Readiness Checks Integration

In `reporting/readiness.py`, add:

- **Blocker**: Branch has `model-governance-gate` step but no run evidence → "Run the model governance gate before generating a report"
- **Warning**: Gate passed with warnings (check the gate evidence) → auto-populated from gate artifact

## 7. Report Bundle Integration

In `reporting/schema.py`, add:

```python
class GovernanceGateCheck(BaseModel):
    check_name: str
    status: str  # "pass" | "warn" | "block"
    message: str
    value: float | None = None
    threshold: float | None = None

class GovernanceGateInfo(BaseModel):
    overall_status: str
    gated_on_role: str
    checks: list[GovernanceGateCheck]
    summary: dict[str, int]

# In ReportBundle:
governance_gate: GovernanceGateInfo | None = None
```

In `reporting/collector.py`, add `_collect_governance_gate()` method.

## 8. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/governance.py` | **CREATE** | `ModelGovernanceGateNode` + `GateBlockedError` (~300 lines) |
| `cardre/nodes/__init__.py` | **MODIFY** | Import + re-export |
| `cardre/registry.py` | **MODIFY** | Register node |
| `cardre/evidence.py` | **MODIFY** | +1 EvidenceKind, +1 schema constant, +1 profile |
| `cardre/reporting/schema.py` | **MODIFY** | +2 Pydantic models |
| `cardre/reporting/collector.py` | **MODIFY** | +1 collector method |
| `cardre/reporting/readiness.py` | **MODIFY** | +governance gate checker |
| `sidecar/proof_pathway.py` | **MODIFY** | Insert step after cutoff-analysis |
| `tests/test_governance_gate.py` | **CREATE** | Unit + integration tests |

## 9. Testing Strategy

### Unit tests (8 tests)

1. `test_auc_gate_passes`: AUC=0.75, min_auc=0.70 → pass
2. `test_auc_gate_blocks`: AUC=0.65, min_auc=0.70, action_on_block="block" → raises GateBlockedError
3. `test_auc_gate_warns`: AUC=0.65, min_auc=0.70, action_on_block="warn" → warning, pass
4. `test_calibration_gate`: High calibration error → blocks/warns
5. `test_fairness_parity_gate`: Large approval rate disparity → blocks
6. `test_missing_metrics_graceful`: Metrics not available for a role → produces "fail" check, not crash
7. `test_all_gates_skipped`: All thresholds set to None → all checks pass trivially
8. `test_gate_artifact_schema`: Written artifact validates against expected schema

### Integration tests (3 tests)

9. `test_gate_blocks_downstream`: Gate node fails → downstream steps not executed (executor blocks DAG)
10. `test_gate_with_calibration_and_fairness`: Full pipeline with calibration + fairness reports consumed by gate
11. `test_gate_evidence_in_report_bundle`: Generated report includes GovernanceGateInfo section

## 10. Implementation Sequence

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Evidence type + schema constant | Tiny | — |
| 2 | `ModelGovernanceGateNode` core (AUC + calibration gates) | Medium | Phase 1 |
| 3 | Fairness parity gate integration | Small | Phase 2 + existing `FairnessReportNode` |
| 4 | `GateBlockedError` + executor integration | Small | Phase 2 |
| 5 | Reporting integration (collector, schema, readiness) | Small | Phase 2-3 |
| 6 | Pathway + registry | Tiny | Phase 2 |
| 7 | Tests | Medium | Phase 2-6 |

**MVP:** AUC + calibration gates only, `action_on_block="warn"` (non-blocking by default). Ships as optional step.
