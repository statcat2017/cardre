# Probability Calibration - TDD Execution Guide

> **Derived from:** `docs/plans/platt-calibration-node-plan.md` (incomplete/aspirational)
> **Repo-grounded at:** commit range containing ScoreScalingNode v1, ApplyModelNode v2, adapters.py, evidence module, proof_pathway.py
> **Target audience:** An LLM or junior engineer executing TDD without architectural guesswork.

---

## Read This First

**Do not start by writing implementation code.** This guide is structured as TDD phases. For each phase you must:

1. Write tests first (they will fail - red).
2. Write the minimum implementation to pass tests (green).
3. Refactor if needed (refactor).

If you skip tests and write production code directly, you will miss edge cases and break existing pathway dependencies. This document tells you exactly what to test, what to write, and where.

**The old plan (`platt-calibration-node-plan.md`) embedded a critical mistake:** it assumed calibration could be inserted between `logistic-regression` and `score-scaling` in the build stream. This does not work because:

- Calibration requires scored holdout probabilities (test/OOT predictions from `ApplyModelNode`).
- In the current `SCORECARD_PATHWAY`, `apply-woe` runs in Phase 2C, *after* `score-scaling` in Phase 2B.
- Score scaling consumes `intercept` and `coefficients` from the uncalibrated model artifact. Adding calibration *before* score scaling would break the scorecard attribute math unless the calibrator is folded into the log-odds.

**The correct approach (enforced by this guide):** Insert an `apply-woe-raw` step (or reuse `apply-woe` as a dependency) plus a new `apply-model-raw` step *before* calibration. The calibration node lives in the build stream but depends on scored holdout data. Downstream score scaling must consume the calibrated model artifact. Folded Platt is additive-scorecard-compatible; isotonic is not and must fail hard in `ScoreScalingNode`.

Follow the phases in order. Do not skip.

---

## Execution Checklist

- [ ] Phase 0: Read existing code, verify test runner, bootstrap test file
- [ ] Phase 1: Evidence kind + schema constant + profile entry (backend + frontend)
- [ ] Phase 2: CalibrateProbabilitiesNode core - Platt method, no CV
- [ ] Phase 3: Isotonic method + cross-validation
- [ ] Phase 4: ApplyModelNode calibration detection + adapter changes
- [ ] Phase 5: Pathway registration + score-scaling compatibility rules
- [ ] Verification gates (final)

---

## Phase 0 - Bootstrap and Contextualise

**Purpose:** Ensure you can run tests, understand the current contract coverage pattern, and create the test file skeleton that all subsequent phases will fill.

**Files to read (do not edit):**

| File | What to look for |
|------|------------------|
| `cardre/nodes/build/models.py` | `ScoreScalingNode.run()` - consumes `model.intercept`, `model.coefficients_dict` (lines 463-464). Model artifact is read via `reader.read_optional()` using `EvidenceKind.MODEL_ARTIFACT`. |
| `cardre/modeling/adapters.py` | `apply_logistic()` (lines 108-182), `apply_sklearn_estimator()` (lines 190-278). Both compute `predicted_bad_probability`. Adapter registry at lines 397-403. |
| `cardre/nodes/validate/apply.py` | `ApplyModelNode.run()` - reads model artifact evidence, parses scorecard evidence, delegates to `_apply_model_adapter` (line 362). |
| `cardre/modeling/schema.py` | `ModelArtifactV1` dataclass - has `calibration_artifact_id: str = ""` at line 213 but no rich `calibration` block. |
| `cardre/_evidence/schemas.py` | All schema version constants. You will add `SCHEMA_CALIBRATION_REPORT`. |
| `cardre/_evidence/kinds.py` | `EvidenceKind` enum. You will add `CALIBRATION_REPORT`. |
| `cardre/_evidence/profiles.py` | `EVIDENCE_PROFILES` dict. You will add a `_Profile` entry. |
| `cardre/_evidence/models.py` | `ModelArtifact` dataclass (line 361) - note `_raw: JsonDict` field used to pass through unknown keys. |
| `cardre/evidence.py` | Re-exports everything from `_evidence` submodules. You must re-export new types. |
| `cardre/registry.py` | `_register_launch_nodes()` (line 171) and `_register_deferred_nodes()` (line 248). |
| `sidecar/proof_pathway.py` | `SCORECARD_PATHWAY` - Phase 2B (line 129), Phase 2C (line 148). |
| `tests/contracts/test_node_contracts.py` | Pattern for contract tests. Each node class gets a `Test*Contract` class. Every registered public node must be in `_COVERED_NODE_TYPES` (line 730). |
| `cardre/nodes/__init__.py` | Import/re-export pattern for new node classes. |
| `frontend/src/config/stepDisplayMetadata.ts` | `STEP_DISPLAY_METADATA` - how steps are registered for the UI. |
| `frontend/src/utils/evidenceLabels.ts` | `KIND_LABELS` - display labels for evidence kinds. |
| `frontend/src/components/inspector/EvidenceCard.tsx` | `formatSummary()` - how evidence summaries render. |

**Test to write first:**

Create `tests/test_calibrate.py` with a placeholder that proves the test suite loads:

```python
"""Tests for CalibrateProbabilitiesNode."""

from __future__ import annotations


def test_calibration_test_suite_loads():
    """Trivial smoke test: the test module itself imports cleanly."""
    assert True
```

**Run:**
```bash
pytest tests/test_calibrate.py -v
```

Expected output: 1 passed.

---

## Phase 1 - Evidence Kind, Schema Constant, and Profile Entry

**Purpose:** Register the `CALIBRATION_REPORT` evidence kind so the evidence system can discover calibration report artifacts. This is the smallest possible phase and must be done first because Phase 2 will write calibration report artifacts.

### Tests to write first (in `tests/test_calibrate.py`):

```python
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.schemas import SCHEMA_CALIBRATION_REPORT
from cardre._evidence.profiles import EVIDENCE_PROFILES


class TestCalibrationEvidence:
    """Evidence kind registration for calibration_report."""

    def test_calibration_report_kind_exists(self):
        assert hasattr(EvidenceKind, "CALIBRATION_REPORT")
        assert EvidenceKind.CALIBRATION_REPORT.value == "calibration_report"

    def test_calibration_report_schema_constant(self):
        assert SCHEMA_CALIBRATION_REPORT == "cardre.calibration_report.v1"

    def test_calibration_report_profile_registered(self):
        profile = EVIDENCE_PROFILES.get(EvidenceKind.CALIBRATION_REPORT)
        assert profile is not None, "Missing profile for CALIBRATION_REPORT"
        assert "report" in profile.expected_roles
        assert profile.schema_version == SCHEMA_CALIBRATION_REPORT
        assert "method" in profile.required_keys
        assert "calibration_error" in profile.required_keys

    def test_calibration_report_re_exported(self):
        """Verify the public cardre.evidence module re-exports."""
        from cardre.evidence import SCHEMA_CALIBRATION_REPORT
        assert SCHEMA_CALIBRATION_REPORT == "cardre.calibration_report.v1"
```

### Files to edit:

| File | Change |
|------|--------|
| `cardre/_evidence/schemas.py` | Add `SCHEMA_CALIBRATION_REPORT = "cardre.calibration_report.v1"` |
| `cardre/_evidence/kinds.py` | Add `CALIBRATION_REPORT = "calibration_report"` to `EvidenceKind` |
| `cardre/_evidence/profiles.py` | Add `_Profile` entry for `EvidenceKind.CALIBRATION_REPORT` |
| `cardre/evidence.py` | Import and re-export `SCHEMA_CALIBRATION_REPORT` |
| `frontend/src/utils/evidenceLabels.ts` | Add `"calibration-report": "Calibration Report",` to `KIND_LABELS` |
| `frontend/src/components/inspector/EvidenceCard.tsx` | Add a `"calibration-report"` branch in `formatSummary()` |

### Implementation steps:

**1a. `cardre/_evidence/schemas.py` - add constant after line 36:**

```python
SCHEMA_CALIBRATION_REPORT = "cardre.calibration_report.v1"
```

**1b. `cardre/_evidence/kinds.py` - add enum member (alphabetical position, around line 25):**

```python
    CALIBRATION_REPORT = "calibration_report"
```

**1c. `cardre/_evidence/profiles.py` - add profile entry (alphabetical, near line 153):**

```python
    EvidenceKind.CALIBRATION_REPORT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_CALIBRATION_REPORT,
        required_keys={"method", "calibration_error", "bins"},
    ),
```

**1d. `cardre/evidence.py` - add import/export:**
- Add `SCHEMA_CALIBRATION_REPORT` to the import block from `cardre._evidence.schemas`
- Add `"SCHEMA_CALIBRATION_REPORT"` to `__all__`

**1e. `frontend/src/utils/evidenceLabels.ts` - add label:**

```typescript
  "calibration-report": "Calibration Report",
```

**1f. `frontend/src/components/inspector/EvidenceCard.tsx` - add branch in `formatSummary()` after the `"validation-metrics"` branch (around line 73):**

```typescript
  } else if (kind === "calibration-report") {
    const method = s.method as string | undefined;
    const calErr = s.calibration_error as number | undefined;
    const binCount = s.bins as unknown[] | undefined;
    if (method) parts.push(`method: ${method}`);
    if (calErr !== undefined) parts.push(`cal error: ${(calErr * 100).toFixed(2)}%`);
    if (binCount) parts.push(`${binCount.length} bins`);
```

### Fail-hard vs warn rules:

- If the profile is missing `required_keys`, evidence reader raises `EvidenceSchemaError` at read time - this is correct fail-hard.
- The `expected_roles={"report"}` means only artifacts with role `"report"` will match. This is correct.
- Frontend: if the kind label is missing, `evidenceKindLabel()` returns the raw kind string - acceptable fallback.

### Run:

```bash
pytest tests/test_calibrate.py::TestCalibrationEvidence -v
```

Expected: 4 passed. Frontend verification is handled later with the frontend test command.

---

## Phase 2 - CalibrateProbabilitiesNode Core (Platt)

**Purpose:** Implement `CalibrateProbabilitiesNode` using Platt scaling (logistic sigmoid calibration). This is the MVP. No cross-validation, no isotonic yet.

The node:
- Reads a scored dataset (must contain `predicted_bad_probability` and the target column).
- Fits Platt scaling with public `sklearn.linear_model.LogisticRegression` on the raw model log-odds.
- Wraps the original ModelArtifact with a new `calibration` block, preserving all original fields.
- Writes a calibration report artifact.
- Writes the updated model artifact (role `"model"`).

### Tests to write first (in `tests/test_calibrate.py`):

```python
import io
import json
import joblib
import numpy as np
import polars as pl
import pytest
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression

from cardre.audit import ExecutionContext, StepSpec
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.evidence import EvidenceKind, SCHEMA_CALIBRATION_REPORT
from cardre.nodes.calibrate import CalibrateProbabilitiesNode
from cardre.store import ProjectStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "test.cardre")
    store.initialize()
    return store


@pytest.fixture
def miscalibrated_data():
    """Create synthetic data where raw LR probabilities are miscalibrated
    due to class imbalance, then apply a known offset."""
    rng = np.random.RandomState(42)
    n = 2000
    # Generate probabilities that are systematically off
    raw_probs = np.clip(rng.beta(2, 5, size=n), 0.001, 0.999)
    # Actual labels follow a different pattern (simulate miscalibration)
    true_probs = np.clip(raw_probs * 0.5 + 0.05, 0.001, 0.999)
    y = (rng.uniform(size=n) < true_probs).astype(int)
    df = pl.DataFrame({
        "predicted_bad_probability": raw_probs,
        "target": pl.Series(y, dtype=pl.Int64),
    })
    return df


@pytest.fixture
def simple_model_artifact(store: ProjectStore) -> str:
    """Write a minimal logistic model artifact and return its artifact_id."""
    model = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "features": ["x1_woe"],
        "intercept": -1.0,
        "coefficients": {"x1_woe": 0.5},
        "target_column": "target",
        "class_mapping": {"0": "good", "1": "bad"},
    }
    art = write_json_artifact(
        store, artifact_type="model", role="model",
        stem="test-model",
        payload=model,
        metadata={"schema_version": "cardre.model_artifact.v1"},
    )
    return art.artifact_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCalibrateProbabilitiesNode:
    """Unit tests for CalibrateProbabilitiesNode."""

    def test_platt_calibration_improves_calibration_error(
        self, store: ProjectStore, miscalibrated_data: pl.DataFrame,
    ):
        """Platt scaling should reduce mean calibration error."""
        node = CalibrateProbabilitiesNode()
        # Arrange: write scored dataset, model artifact, definition artifact
        raise NotImplementedError("Phase 2: implement this test")

    def test_validation_errors_missing_column(self, store: ProjectStore):
        """Missing predicted_bad_probability raises ValueError."""
        node = CalibrateProbabilitiesNode()
        raise NotImplementedError("Phase 2: implement this test")

    def test_validation_errors_too_few_rows(self, store: ProjectStore):
        """Fewer than 100 calibration rows raises ValueError."""
        node = CalibrateProbabilitiesNode()
        raise NotImplementedError("Phase 2: implement this test")

    def test_calibrated_model_artifact_has_calibration_block(
        self, store: ProjectStore, miscalibrated_data: pl.DataFrame,
    ):
        """Output model artifact must contain a 'calibration' block."""
        raise NotImplementedError("Phase 2: implement this test")

    def test_calibrated_model_artifact_preserves_original_fields(
        self, store: ProjectStore, miscalibrated_data: pl.DataFrame,
        simple_model_artifact: str,
    ):
        """All original model artifact fields must survive calibration."""
        raise NotImplementedError("Phase 2: implement this test")

    def test_calibration_report_artifact_schema(
        self, store: ProjectStore, miscalibrated_data: pl.DataFrame,
    ):
        """Calibration report must match SCHEMA_CALIBRATION_REPORT."""
        raise NotImplementedError("Phase 2: implement this test")
```

### Files to edit/create:

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/calibrate.py` | **CREATE** | Core node (~200 lines) |
| `cardre/nodes/__init__.py` | **MODIFY** | Import + re-export `CalibrateProbabilitiesNode` |
| `cardre/registry.py` | **MODIFY** | Register as launch-tier node in `_register_launch_nodes()` |
| `tests/contracts/test_node_contracts.py` | **MODIFY** | Add `TestCalibrateProbabilitiesContract` class + add to `_COVERED_NODE_TYPES` |

### Implementation steps:

**2a. Create `cardre/nodes/calibrate.py`:**

```python
"""CalibrateProbabilitiesNode - Platt and isotonic calibration for probability outputs.

Fits a calibrator on scored holdout data and wraps the original ModelArtifact
with a calibration block. The calibrator is serialised separately as a joblib
artifact and referenced by artifact_id.
"""

from __future__ import annotations

import io
import joblib
from typing import Any

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, JsonDict, NodeOutput, NodeType
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_CALIBRATION_REPORT,
    SCHEMA_MODEL_ARTIFACT,
)
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.modeling.serialization import write_estimator_artifact


class CalibrateProbabilitiesNode(NodeType):
    node_type = "cardre.calibrate_probabilities"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "test", "oot", "definition", "model"]
    output_roles: list[str] = ["model", "report"]

    MIN_CALIBRATION_ROWS = 100

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Calibrate Probabilities",
            methods=[
                MethodOption(
                    id="platt",
                    label="Platt Scaling",
                    status="available",
                    description="Logistic sigmoid calibration (recommended for credit scoring).",
                    params=[
                        ParameterDefinition(
                            name="calibration_sample",
                            label="Calibration Sample",
                            kind="enum",
                            default="test",
                            constraint=ParameterConstraint(
                                enum_values=["test", "oot", "train"]
                            ),
                            help_text="Which data role to use for fitting the calibrator.",
                        ),
                        ParameterDefinition(
                            name="min_probability",
                            label="Min Probability",
                            kind="float",
                            default=0.001,
                            constraint=ParameterConstraint(min_value=0.0, exclusive_min=0.0),
                        ),
                        ParameterDefinition(
                            name="max_probability",
                            label="Max Probability",
                            kind="float",
                            default=0.999,
                            constraint=ParameterConstraint(max_value=1.0, exclusive_max=1.0),
                        ),
                    ],
                ),
                MethodOption(
                    id="isotonic",
                    label="Isotonic Regression",
                    status="coming_soon",
                    description="Non-parametric step-function calibration.",
                    params=[],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sample = params.get("calibration_sample", "test")
        if sample not in ("test", "oot", "train"):
            errors.append(f"calibration_sample must be 'test', 'oot', or 'train', got {sample!r}")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        method = params.get("method", "platt")
        calibration_sample = params.get("calibration_sample", "test")
        min_prob = float(params.get("min_probability", 0.001))
        max_prob = float(params.get("max_probability", 0.999))

        # 1. Read modelling metadata for target definition
        meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_column = meta.target_column

        # 2. Read the scored calibration sample
        calib_art = next(
            (a for a in context.input_artifacts if a.role == calibration_sample),
            None,
        )
        if calib_art is None:
            raise ValueError(
                f"Calibration requires a dataset with role={calibration_sample!r}, "
                f"none found in input artifacts"
            )

        df = pl.read_parquet(
            store.artifact_path(calib_art)
        )  # cardre-allow-artifact-read: dataset-frame-input

        if "predicted_bad_probability" not in df.columns:
            raise ValueError(
                f"Calibration sample role={calibration_sample!r} is missing "
                f"column 'predicted_bad_probability'. Run apply-model first."
            )
        if target_column not in df.columns:
            raise ValueError(
                f"Calibration sample role={calibration_sample!r} is missing "
                f"target column {target_column!r}"
            )

        if df.height < self.MIN_CALIBRATION_ROWS:
            raise ValueError(
                f"Calibration sample ({calibration_sample}) has {df.height} rows, "
                f"minimum is {self.MIN_CALIBRATION_ROWS}"
            )

        # 3. Extract raw probabilities and binary target
        y_prob_raw = df["predicted_bad_probability"].to_numpy()
        good_values = {str(v) for v in meta.good_values}
        bad_values = {str(v) for v in meta.bad_values}
        if not good_values or not bad_values:
            raise ValueError("Calibration requires modelling metadata with good_values and bad_values")
        target_str = df[target_column].cast(pl.String)
        unknown = df.filter(~target_str.is_in(good_values | bad_values))
        if unknown.height:
            raise ValueError(
                f"Calibration target column {target_column!r} contains values not declared as good or bad"
            )
        y_binary = target_str.is_in(bad_values).cast(pl.Int64).to_numpy()

        # Clip extreme values
        y_prob_raw = np.clip(y_prob_raw, min_prob, max_prob)

        # 4. Fit calibrator
        if method == "platt":
            raw_log_odds = _safe_logit(y_prob_raw).reshape(-1, 1)
            calibrator = LogisticRegression(solver="lbfgs")
            calibrator.fit(raw_log_odds, y_binary)
            slope = float(calibrator.coef_[0][0])
            intercept_shift = float(calibrator.intercept_[0])
            if slope <= 0:
                raise ValueError("Platt calibration produced non-positive slope; score ordering would invert")
        else:
            raise ValueError(f"Unknown calibration method {method!r}")

        # 5. Compute calibrated probabilities for diagnostics
        y_prob_cal = calibrator.predict_proba(raw_log_odds)[:, 1]

        # 6. Compute calibration metrics (10-bin)
        bins = _compute_calibration_bins(y_binary, y_prob_raw, y_prob_cal)

        calibration_error = float(np.mean([b["abs_deviation"] for b in bins]))
        max_bin_deviation = float(np.max([b["abs_deviation"] for b in bins]))

        warnings_list: list[JsonDict] = []
        if calibration_error > 0.05:
            warnings_list.append({
                "code": "HIGH_CALIBRATION_ERROR",
                "message": f"Post-calibration calibration error {calibration_error:.4f} exceeds 0.05",
            })

        # 7. Serialize calibrator
        calibrator_bytes = io.BytesIO()
        joblib.dump(calibrator, calibrator_bytes)
        calibrator_bytes.seek(0)

        calibrator_art = write_estimator_artifact(
            store,
            estimator_bytes=calibrator_bytes.read(),
            estimator_format="joblib",
            stem=f"calibrator-{context.step_spec.step_id}",
            creating_run_id=context.run_id,
            creating_run_step_id=context.step_spec.step_id,
            metadata={"artifact_subtype": "probability_calibrator", "method": method},
        )

        # 8. Read current model artifact
        model_art = next(a for a in context.input_artifacts if a.role == "model")
        typed_model = reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)
        model: dict[str, Any] = dict(getattr(typed_model, "_raw", {}))
        model.update(typed_model.as_legacy_dict())

        # 9. Write calibration report artifact
        cal_report: JsonDict = {
            "schema_version": SCHEMA_CALIBRATION_REPORT,
            "method": method,
            "calibrated_on": calibration_sample,
            "cross_validated": False,
            "calibration_error": round(calibration_error, 6),
            "max_bin_deviation": round(max_bin_deviation, 6),
            "bins": bins,
            "warnings": warnings_list,
        }
        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"calibration-report-{context.step_spec.step_id}",
            payload=cal_report,
            metadata={"schema_version": SCHEMA_CALIBRATION_REPORT},
        )

        # 10. Update model artifact with calibration block
        model["calibration"] = {
            "method": method,
            "application_mode": "folded_linear_log_odds",
            "score_scaling_compatible": True,
            "cross_validated": False,
            "calibrator_artifact_id": calibrator_art.artifact_id,
            "calibrator_logical_hash": calibrator_art.logical_hash,
            "calibration_report_artifact_id": report_art.artifact_id,
            "calibration_error": round(calibration_error, 6),
            "max_bin_deviation": round(max_bin_deviation, 6),
            "calibrator_format": "joblib",
        }
        # Fold Platt's linear log-odds transform into the scorecard-compatible
        # logistic artifact. ScoreScalingNode will now consume calibrated
        # intercept/coefficients from this new immutable model artifact.
        if model.get("model_family") == "logistic_regression":
            model["intercept"] = round(float(model.get("intercept", 0.0)) * slope + intercept_shift, 6)
            model["coefficients"] = {
                name: round(float(value) * slope, 6)
                for name, value in dict(model.get("coefficients", {})).items()
            }
        model["schema_version"] = SCHEMA_MODEL_ARTIFACT

        updated_model_art = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"calibrated-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "schema_version": SCHEMA_MODEL_ARTIFACT,
                "calibrated": True,
                "calibration_method": method,
            },
        )

        return NodeOutput(
            artifacts=[updated_model_art, report_art, calibrator_art],
            metrics={
                "method": method,
                "calibration_sample": calibration_sample,
                "calibration_error": round(calibration_error, 6),
                "cross_validated": False,
            },
        )


def _compute_calibration_bins(
    y_true: np.ndarray,
    y_prob_raw: np.ndarray,
    y_prob_cal: np.ndarray,
    n_bins: int = 10,
) -> list[JsonDict]:
    """Compute 10-bin calibration diagnostics (pre and post)."""
    bins: list[JsonDict] = []
    quantiles = np.linspace(0, 100, n_bins + 1)
    percentiles = np.percentile(y_prob_cal, quantiles)

    for i in range(n_bins):
        lo = percentiles[i]
        hi = percentiles[i + 1]
        if i == n_bins - 1:
            mask = (y_prob_cal >= lo) & (y_prob_cal <= hi)
        else:
            mask = (y_prob_cal >= lo) & (y_prob_cal < hi)

        count = int(np.sum(mask))
        if count == 0:
            continue
        avg_pred_cal = float(np.mean(y_prob_cal[mask]))
        avg_pred_raw = float(np.mean(y_prob_raw[mask]))
        actual_rate = float(np.mean(y_true[mask]))
        bins.append({
            "bin": i,
            "count": count,
            "avg_predicted": round(avg_pred_cal, 6),
            "actual_bad_rate": round(actual_rate, 6),
            "avg_predicted_raw": round(avg_pred_raw, 6),
            "abs_deviation": round(abs(avg_pred_cal - actual_rate), 6),
        })
    return bins


def _safe_logit(probability: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Convert probabilities to log-odds with clipping for numerical safety."""
    p = np.clip(np.asarray(probability, dtype=float), eps, 1.0 - eps)
    return np.log(p / (1.0 - p))
```

**2b. `cardre/nodes/__init__.py` - add import and re-export:**

In the import block from `cardre.nodes.build` (line 28), `cardre.nodes.build` is the build nodes module. But calibrate.py is a standalone file like `cardre/nodes/calibrate.py`. Add:

```python
from cardre.nodes.calibrate import (
    CalibrateProbabilitiesNode,
)
```

And add `"CalibrateProbabilitiesNode"` to `__all__`.

**2c. `cardre/registry.py` - register as a launch-tier node:**

In `_register_launch_nodes()`, add import and registration:

```python
from cardre.nodes import (
    ...
    CalibrateProbabilitiesNode,
    ...
)
```

Add to the registration list:

```python
    for n in [
        ...
        CalibrateProbabilitiesNode,
        ...
    ]:
        reg.register(n)
```

**2d. `tests/contracts/test_node_contracts.py` - add contract test:**

```python
class TestCalibrateProbabilitiesContract(NodeContractTestBase):
    node_cls = CalibrateProbabilitiesNode
    bad_params: dict[str, Any] = {"calibration_sample": "invalid"}
    expected_output_roles = {"model", "report"}
    expected_category = "fit"

    def get_good_params(self, tmp_path: Path) -> dict[str, Any]:
        return {"calibration_sample": "test"}
```

Also add `CalibrateProbabilitiesNode` to the import block and `_COVERED_NODE_TYPES`.

### Fail-hard vs warn rules:

- Missing `predicted_bad_probability` column: **fail hard** (ValueError)
- Missing target column: **fail hard** (ValueError)
- Fewer than 100 rows: **fail hard** (ValueError)
- Calibration sample role not found in input artifacts: **fail hard** (ValueError)
- Calibration error > 0.05: **warn only** (appended to `warnings` list in report and model artifact)

### Run:

```bash
pytest tests/test_calibrate.py -v -x
pytest tests/contracts/test_node_contracts.py::TestCalibrateProbabilitiesContract -v
```

---

## Phase 3 - Isotonic Method + Cross-Validation

**Purpose:** Add isotonic regression support and cross-validation for both Platt and isotonic methods.

### Tests to write first:

```python
class TestIsotonicCalibration(TestCalibrateProbabilitiesNode):
    def test_isotonic_calibration_non_decreasing(self, store, miscalibrated_data):
        """Isotonic fit must produce non-decreasing function."""
        raise NotImplementedError("Phase 3")

    def test_cross_validation_differs_from_no_cv(self, store, miscalibrated_data):
        """CV ensemble produces different calibrator than non-CV."""
        raise NotImplementedError("Phase 3")

    def test_isotonic_small_sample_warning(self, store):
        """Isotonic on <1000 rows should produce a warning, not fail."""
        raise NotImplementedError("Phase 3")
```

### Files to edit:

| File | Change |
|------|--------|
| `cardre/nodes/calibrate.py` | Add isotonic method branch, add CV loop, add `cross_validation` param |

### Implementation steps:

**3a. Update `parameter_schema()` to make isotonic available and add CV params:**

```python
                MethodOption(
                    id="isotonic",
                    label="Isotonic Regression",
                    status="available",
                    description="Non-parametric step-function calibration.",
                    params=[
                        ParameterDefinition(
                            name="calibration_sample",
                            label="Calibration Sample",
                            kind="enum",
                            default="test",
                            constraint=ParameterConstraint(
                                enum_values=["test", "oot"]
                            ),
                        ),
                        ParameterDefinition(
                            name="cross_validation",
                            label="Cross-Validation",
                            kind="boolean",
                            default=True,
                        ),
                        ParameterDefinition(
                            name="cv_folds",
                            label="CV Folds",
                            kind="integer",
                            default=5,
                            constraint=ParameterConstraint(min_value=2, max_value=20),
                        ),
                    ],
                ),
```

**3b. In `run()`, after extracting params, add CV handling:**

```python
        cross_validated = bool(params.get("cross_validation", True))
        cv_folds = int(params.get("cv_folds", 5))

        # ... after extracting y_prob_raw, y_binary ...

        if method == "platt":
            if cross_validated and cv_folds > 1:
                calibrator = _fit_platt_cv(y_prob_raw, y_binary, cv_folds)
                application_mode = "runtime_probability_transform"
                score_scaling_compatible = False
            else:
                raw_log_odds = _safe_logit(y_prob_raw).reshape(-1, 1)
                calibrator = LogisticRegression(solver="lbfgs")
                calibrator.fit(raw_log_odds, y_binary)
                application_mode = "folded_linear_log_odds"
                score_scaling_compatible = True
        elif method == "isotonic":
            from sklearn.isotonic import IsotonicRegression
            if cross_validated and cv_folds > 1:
                calibrator = _fit_isotonic_cv(y_prob_raw, y_binary, cv_folds)
            else:
                calibrator = IsotonicRegression(out_of_bounds="clip")
                calibrator.fit(y_prob_raw, y_binary)
            application_mode = "runtime_probability_transform"
            score_scaling_compatible = False
            # Warn if small sample for isotonic
            if len(y_prob_raw) < 1000:
                warnings_list.append({
                    "code": "SMALL_ISOTONIC_SAMPLE",
                    "message": f"Isotonic regression on {len(y_prob_raw)} rows "
                               f"(<1000): non-parametric calibration may overfit",
                })
        else:
            raise ValueError(f"Unknown calibration method {method!r}")
```

**3c. Add CV helper functions (before the class or as module-level):**

```python
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import StratifiedKFold


def _fit_platt_cv(
    y_prob: np.ndarray,
    y_true: np.ndarray,
    n_folds: int = 5,
) -> _CalibratorEnsemble:
    """Fit Platt calibrator via CV, averaging calibrator probabilities."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    all_calibrators = []
    for train_idx, _ in skf.split(np.zeros(len(y_true)), y_true):
        cal = LogisticRegression(solver="lbfgs")
        X_fold = _safe_logit(y_prob[train_idx]).reshape(-1, 1)
        cal.fit(X_fold, y_true[train_idx])
        all_calibrators.append(cal)
    # Return an ensemble wrapper
    return _CalibratorEnsemble(all_calibrators, method="platt")


def _fit_isotonic_cv(
    y_prob: np.ndarray,
    y_true: np.ndarray,
    n_folds: int = 5,
) -> IsotonicRegression:
    """Fit isotonic calibrator via CV, averaging predictions."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    all_calibrators = []
    for train_idx, _ in skf.split(np.zeros(len(y_true)), y_true):
        cal = IsotonicRegression(out_of_bounds="clip")
        cal.fit(y_prob[train_idx], y_true[train_idx])
        all_calibrators.append(cal)
    return _CalibratorEnsemble(all_calibrators, method="isotonic")


class _CalibratorEnsemble:
    """Ensemble of calibrators fitted on CV folds.

    Averages predict_proba (Platt) or predict (isotonic) across folds.
    This is a runtime probability transform and is not additive-scorecard-compatible.
    """

    def __init__(self, calibrators: list, method: str):
        self._calibrators = calibrators
        self._method = method

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Average calibrated probabilities across all fold calibrators."""
        all_probs = []
        for cal in self._calibrators:
            if self._method == "platt":
                raw_prob = X[:, 1] if X.ndim == 2 and X.shape[1] == 2 else X.ravel()
                p = cal.predict_proba(_safe_logit(raw_prob).reshape(-1, 1))
                all_probs.append(p)
            else:
                # IsotonicRegression.predict
                p = cal.predict(X[:, 1] if X.ndim == 2 else X)
                all_probs.append(np.column_stack([1 - p, p]))
        return np.mean(all_probs, axis=0)
```

### Fail-hard vs warn rules:

- `cross_validation=True` with `cv_folds` < 2: clamp to 1 (no CV) - no error.
- `cv_folds` > 20: fail hard (param constraint).
- Isotonic on < 1000 rows: **warn** (not fail).
- If CV fold has < 2 positive samples: StratifiedKFold will raise - allow sklearn exception to propagate (fail hard).

### Run:

```bash
pytest tests/test_calibrate.py -v -x
```

---

## Phase 4 - ApplyModelNode Calibration Detection + Adapter Changes

**Purpose:** Make `ApplyModelNode` detect the `calibration` block on the model artifact and route probabilities through the calibrator. This affects both the `apply_logistic` and `apply_sklearn_estimator` adapters.

**Critical design rule:** The adapters compute `predicted_bad_probability`. The calibration transform must happen *after* the adapter computes raw probabilities but *before* score scaling transforms log-odds to points.

Since score scaling currently uses `raw_model_output` (log-odds), the calibration detection must happen in the adapter so the score computation uses *calibrated* log-odds (Platt) or fail for isotonic.

### Score Scaling Compatibility Rules

| Method | Scorecard compatible? | Rule |
|--------|---------------------|------|
| Platt (single calibrator, folded) | YES | Platt's linear transform of raw log-odds is folded into the calibrated model artifact's top-level intercept and coefficients. Score scaling consumes the calibrated artifact transparently. |
| Platt CV ensemble | NO | Averaging multiple sigmoid calibrators is no longer one linear log-odds transform. Score scaling must fail hard unless a later non-additive score design is added. |
| Isotonic | NO | Isotonic is a non-parametric step function. It cannot be expressed as additive scorecard points. Score scaling must fail hard with a clear error message. |

For folded Platt: `calibrated_log_odds = slope * raw_log_odds + intercept_shift`. Because raw logistic scorecards already use `raw_log_odds = model_intercept + sum(coef * feature)`, the calibration node writes a new calibrated model artifact with `intercept = slope * old_intercept + intercept_shift` and each `coefficient = slope * old_coefficient`. Adapters must not apply the calibrator again for this mode.

### Tests to write first:

```python
class TestApplyModelCalibrated:
    """ApplyModelNode with calibrated model artifacts."""

    def test_applies_platt_calibrator_to_probabilities(self, store, miscalibrated_data):
        """ApplyModelNode with calibration block should return calibrated probs."""
        raise NotImplementedError("Phase 4")

    def test_uncalibrated_model_unchanged(self, store):
        """Model artifact without calibration block behaves as before."""
        raise NotImplementedError("Phase 4")

    def test_score_scaling_with_platt_calibration(self, store):
        """Score scaling must produce scorecard from Platt-calibrated model."""
        raise NotImplementedError("Phase 4")

    def test_score_scaling_fails_hard_with_isotonic(self, store):
        """Score scaling on isotonic-calibrated model raises ValueError."""
        raise NotImplementedError("Phase 4")

    def test_calibrated_model_with_ensemble(self, store):
        """Voting/weighted ensemble with calibrated base models."""
        raise NotImplementedError("Phase 4")
```

### Files to edit:

| File | Change |
|------|--------|
| `cardre/modeling/adapters.py` | Add `_apply_calibration()` helper; call in `apply_logistic()` and `apply_sklearn_estimator()` |

### Implementation steps:

**4a. Add calibration helper to `adapters.py`:**

Add this import near the existing `read_estimator_artifact` import if it is not already present:

```python
from cardre.modeling.serialization import read_estimator_artifact
```

```python
def _apply_calibration(
    model: dict[str, Any],
    store: ProjectStore,
    y_prob: np.ndarray,
) -> np.ndarray:
    """If the model artifact has a calibration block, load and apply the calibrator.

    Args:
        model: The parsed model artifact dict.
        store: The project store.
        y_prob: Raw predicted_bad_probability array (shape (n,)).

    Returns:
        Calibrated probability array (shape (n,)).

    Raises:
        ValueError: If calibration block references a missing calibrator.
    """
    calibration = model.get("calibration")
    if not calibration:
        return y_prob  # no-op

    application_mode = calibration.get("application_mode", "runtime_probability_transform")
    if application_mode == "folded_linear_log_odds":
        # The model artifact's intercept/coefficients are already calibrated.
        # Applying the calibrator again would double-calibrate probabilities.
        return y_prob

    calibrator_id = calibration.get("calibrator_artifact_id")
    if not calibrator_id:
        raise ValueError("Model has calibration block but no calibrator_artifact_id")

    calibrator_art = store.get_artifact(calibrator_id)
    if calibrator_art is None:
        raise ValueError(
            f"Calibrator artifact {calibrator_id!r} not found in store"
        )

    calibrator_bytes = read_estimator_artifact(
        store,
        calibrator_art,
        expected_logical_hash=calibration.get("calibrator_logical_hash"),
    )
    calibrator = joblib.load(io.BytesIO(calibrator_bytes))

    # Package raw probs as shape (n, 2) for runtime calibrators that expect it.
    X_cal = np.column_stack([1.0 - y_prob, y_prob])

    if hasattr(calibrator, "predict_proba"):
        cal_probs = calibrator.predict_proba(X_cal)
        calibrated = cal_probs[:, 1] if cal_probs.shape[1] > 1 else cal_probs[:, 0]
    else:
        calibrated = calibrator.predict(y_prob)

    return np.asarray(calibrated, dtype=np.float64)
```

**4b. Modify `apply_logistic()` in `adapters.py`:**

After line 144 (where `prob_expr` is computed as the Polars expression), insert calibration logic. The cleanest approach: compute raw probabilities with Polars, convert to numpy, apply calibration, insert calibrated column back.

Replace lines 143-166 with:

```python
        # Compute raw log-odds and probabilities
        log_odds_expr = pl.lit(intercept)
        for feat in features:
            log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefficients.get(feat, 0)))

        prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
        raw_expr = log_odds_expr.alias("raw_model_output")

        # Compute raw probability column
        df = df.with_columns([
            prob_expr,
            raw_expr,
        ])

        # Apply runtime calibration if present. Folded Platt is a no-op here
        # because this model artifact's coefficients are already calibrated.
        if model.get("calibration"):
            raw_probs = df["predicted_bad_probability"].to_numpy()
            cal_probs = _apply_calibration(model, store, raw_probs)
            df = df.with_columns([
                pl.Series("predicted_bad_probability", cal_probs, dtype=pl.Float64),
            ])
            # Recompute raw_model_output as calibrated log-odds
            cal_log_odds = np.log(np.clip(cal_probs / np.maximum(1 - cal_probs, 1e-15), 1e-15, None))
            df = df.with_columns([
                pl.Series("raw_model_output", cal_log_odds, dtype=pl.Float64),
            ])

        base_metadata: JsonDict = { ... }
        # ... rest of the function unchanged from line 147 onward
```

**4c. Modify `apply_sklearn_estimator()` in `adapters.py`:**

After line 237 (`pred_bad = ...`), insert:

```python
        # Apply calibration if present
        if model.get("calibration"):
            pred_bad = _apply_calibration(model, store, pred_bad)
```

And after the score computation (lines 251-256), ensure the log-odds used for scoring are derived from calibrated probabilities when calibration is present.

**4d. Modify `ScoreScalingNode` in `cardre/nodes/build/models.py`:**

In `ScoreScalingNode.run()`, after loading the model (line 430-438), add:

```python
        # Detect calibration compatibility before building additive scorecard points.
        model_raw = getattr(model, "_raw", {})
        calibration = model_raw.get("calibration", {})
        if calibration:
            application_mode = calibration.get("application_mode", "")
            score_scaling_compatible = bool(calibration.get("score_scaling_compatible", False))
            if application_mode != "folded_linear_log_odds" or not score_scaling_compatible:
                raise ValueError(
                    "Score scaling requires calibration.application_mode="
                    "'folded_linear_log_odds'. Runtime probability calibration "
                    "(including isotonic and CV Platt ensembles) is not compatible "
                    "with additive scorecard points."
                )
```

In practice, `model.intercept` and `model.coefficients_dict` come from the `ModelArtifact` evidence reader. For score-scaling-compatible folded Platt, those fields must already be calibrated in the new model artifact. Do not reach back to the original uncalibrated model for score scaling.

### Fail-hard vs warn rules:

- Calibration block present but calibrator artifact missing: **fail hard** (ValueError)
- Isotonic calibration + score scaling: **fail hard** (ValueError)
- Calibration block with unknown method: **fail hard** (ValueError)
- No calibration block: **silent no-op** (current behavior)
- Calibrator predict_proba returns unexpected shape: let numpy propagate error (fail hard)

### Run:

```bash
pytest tests/test_calibrate.py -v -x
pytest tests/contracts/test_node_contracts.py::TestApplyModelContract -v
pytest tests/contracts/test_node_contracts.py::TestScoreScalingContract -v
```

---

## Phase 5 - Pathway Registration + Apply-Model-Raw Insertion

**Purpose:** Add the `apply-woe-raw` / `apply-model-raw` / `calibrate-probabilities` steps to the scorecard pathway and fix the lifecycle tension.

**The problem in detail:**

Current Phase 2B: `logistic-regression -> score-scaling -> build-summary-report -> freeze-scorecard-bundle`
Current Phase 2C: `apply-woe -> apply-model -> validation-metrics -> cutoff-analysis`

Calibration needs scored holdout probabilities. `apply-model` produces them, but it currently depends on `score-scaling` (line 152 of proof_pathway.py). This creates a cycle if we try to insert `calibrate-probabilities` before `score-scaling`.

**Solution:** Add a parallel `apply-woe-raw` -> `apply-model-raw` path in Phase 2B that runs WOE + model apply *without* score scaling, producing the scored holdout data that `calibrate-probabilities` needs. Then `calibrate-probabilities` feeds back into the model artifact, and `validate-stream` re-applies with the calibrated model.

**Updated Phase 2B (schematic):**

```
logistic-regression -> apply-woe-raw -> apply-model-raw -> calibrate-probabilities
                                                              -> score-scaling
                                                              -> build-summary-report
                                                              -> freeze-scorecard-bundle
```

Note: `apply-woe-raw` reuses `cardre.apply_woe_mapping` (the same node as `apply-woe`). `apply-model-raw` uses `cardre.apply_model` without a scorecard artifact. `calibrate-probabilities` writes a new calibrated model artifact. `score-scaling` must consume that calibrated model artifact, not the original `logistic-regression` artifact.

**Updated Phase 2C:**

```
apply-woe -> apply-model (with calibrated model and scorecard) -> validation-metrics -> cutoff-analysis
```

Where `apply-model` now receives both the (updated) model and the scorecard, producing calibrated scores.

### Tests to write first:

```python
class TestPathwayCalibration:
    """End-to-end pathway tests."""

    def test_apply_model_raw_produces_holdout_scores(self):
        """apply-model-raw step produces predicted_bad_probability without scorecard."""
        raise NotImplementedError("Phase 5 - integration test")

    def test_calibrate_probabilities_follows_apply_model_raw(self):
        """CalibrateProbabilitiesNode receives scored holdout from apply-model-raw."""
        raise NotImplementedError("Phase 5 - integration test")

    def test_full_calibrated_scorecard_pathway_runs(self):
        """Full pathway: LR -> apply-woe-raw -> apply-model-raw -> calibrate -> apply-model -> validation."""
        raise NotImplementedError("Phase 5 - integration test")
```

### Files to edit:

| File | Change |
|------|--------|
| `sidecar/proof_pathway.py` | Add `apply-woe-raw`, `apply-model-raw`, `calibrate-probabilities` in Phase 2B; ensure Phase 2C `apply-model` depends on calibrated model |
| `cardre/registry.py` | Ensure `CalibrateProbabilitiesNode` is registered in `_register_launch_nodes()` |
| `frontend/src/config/stepDisplayMetadata.ts` | Add metadata entries for new steps |

### Implementation steps:

**5a. Modify `sidecar/proof_pathway.py` - Phase 2B:**

Insert after `logistic-regression` (line 134):

```python
            # Raw apply path for calibration - produces holdout probabilities
            # without score scaling, so calibrate-probabilities can consume them.
            PathwayStepSpec("apply-woe-raw", "cardre.apply_woe_mapping", category="apply",
                            params={"woe_unmatched_policy": "fail"},
                            parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "final-woe-iv", "variable-selection"]),
            PathwayStepSpec("apply-model-raw", "cardre.apply_model", category="apply",
                            parent_step_ids=["apply-woe-raw", "logistic-regression"]),
            PathwayStepSpec("calibrate-probabilities", "cardre.calibrate_probabilities", category="fit",
                            params={"calibration_sample": "test"},
                            parent_step_ids=["apply-model-raw", "logistic-regression", "define-metadata"]),
```

Then change the existing `score-scaling`, `build-summary-report`, and `freeze-scorecard-bundle` dependencies so they consume the calibrated model artifact:

```python
            PathwayStepSpec("score-scaling", "cardre.score_scaling", category="fit",
                            params={
                                "base_score": 600, "base_odds": 50.0,
                                "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
                            },
                            parent_step_ids=["calibrate-probabilities", "manual-binning", "final-woe-iv"]),
            PathwayStepSpec("build-summary-report", "cardre.build_summary_report", category="fit",
                            parent_step_ids=["score-scaling", "calibrate-probabilities", "final-woe-iv"]),
            PathwayStepSpec("freeze-scorecard-bundle", "cardre.freeze_scorecard_bundle", category="fit",
                            parent_step_ids=["calibrate-probabilities", "score-scaling", "manual-binning", "final-woe-iv", "define-metadata", "variable-selection"]),
```

The calibration node depends on `apply-model-raw` for holdout scores and `logistic-regression` for the original model artifact. After calibration, all downstream build/apply steps use the calibrated model artifact.

**5b. Modify Phase 2C `apply-model` dependencies:**

Change from:

```python
            PathwayStepSpec("apply-model", "cardre.apply_model", category="apply",
                            parent_step_ids=["apply-woe", "logistic-regression", "score-scaling", "freeze-scorecard-bundle"]),
```

To:

```python
            PathwayStepSpec("apply-model", "cardre.apply_model", category="apply",
                            parent_step_ids=["apply-woe", "calibrate-probabilities", "score-scaling", "freeze-scorecard-bundle"]),
```

This way `apply-model` receives only the calibrated model artifact as its `role="model"` input. Do not include `logistic-regression` as a parent here, or `ApplyModelNode` may pick the raw model artifact before the calibrated one.

**5c. `frontend/src/config/stepDisplayMetadata.ts` - add entries:**

```typescript
  "apply-woe-raw": {
    stepId: "apply-woe-raw",
    expectedBackendPosition: 18,  // same position as apply-woe conceptually
    displayOrder: 17.5,
    section: "Model Build",
    label: "Apply WOE (Raw)",
    shortDescription: "Apply WOE to test/OOT for calibration scoring",
  },
  "apply-model-raw": {
    stepId: "apply-model-raw",
    expectedBackendPosition: 18.5,
    displayOrder: 17.75,
    section: "Model Build",
    label: "Apply Model (Raw)",
    shortDescription: "Score holdout data without scorecard",
  },
  "calibrate-probabilities": {
    stepId: "calibrate-probabilities",
    expectedBackendPosition: 17,
    displayOrder: 17.5,
    section: "Model Build",
    label: "Calibrate Probabilities",
    shortDescription: "Platt or isotonic probability calibration on holdout",
  },
```

### Fail-hard vs warn rules:

- If `apply-woe-raw` fails, `apply-model-raw` is blocked (implicitly through the pathway framework - no explicit rule needed).
- If `calibrate-probabilities` is skipped, `apply-model` in Phase 2C works as before (calibration is optional).
- If the user provides a frozen bundle without calibration, the bundle validation in `ApplyModelNode` must still pass (the bundle `model_artifact_id` must match). Calibration creates a *new* model artifact, so the bundle check may fail unless the pathway ensures the bundle is updated or the check is relaxed. **For now: document this as a known limitation** - frozen bundle with calibration requires re-freeze.

### Run:

```bash
# No dedicated test for pathway edits - verify by inspecting the pathway:
python -c "
from sidecar.proof_pathway import SCORECARD_PATHWAY
for phase in SCORECARD_PATHWAY.phases:
    for step in phase:
        print(step.step_id, '->', step.node_type)
"
```

Check that:
- `apply-woe-raw` appears after `logistic-regression`
- `apply-model-raw` appears after `apply-woe-raw`
- `calibrate-probabilities` appears after `apply-model-raw`
- `apply-model` in Phase 2C depends on `calibrate-probabilities`

---

## Model Artifact JSON Examples

### Before calibration (output of LogisticRegressionNode):

```json
{
  "schema_version": "cardre.model_artifact.v1",
  "model_family": "logistic_regression",
  "features": ["age_woe", "income_woe", "ltv_woe"],
  "intercept": -2.15,
  "coefficients": {
    "age_woe": 0.45,
    "income_woe": 0.32,
    "ltv_woe": 0.78
  },
  "target_column": "default_flag",
  "class_mapping": {"0": "good", "1": "bad"},
  "training": {
    "row_count": 5000,
    "converged": true,
    "iterations": 45
  }
}
```

### After calibration (output of CalibrateProbabilitiesNode):

```json
{
  "schema_version": "cardre.model_artifact.v1",
  "model_family": "logistic_regression",
  "features": ["age_woe", "income_woe", "ltv_woe"],
  "intercept": -2.15,
  "coefficients": {
    "age_woe": 0.45,
    "income_woe": 0.32,
    "ltv_woe": 0.78
  },
  "target_column": "default_flag",
  "class_mapping": {"0": "good", "1": "bad"},
  "training": {
    "row_count": 5000,
    "converged": true,
    "iterations": 45
  },
  "calibration": {
    "method": "platt",
    "cross_validated": true,
    "calibrator_artifact_id": "art_cal_abc123",
    "calibration_report_artifact_id": "art_rep_def456",
    "calibration_error": 0.012,
    "max_bin_deviation": 0.038,
    "calibrator_format": "joblib"
  },
  "warnings": []
}
```

Note: For score-scaling-compatible folded Platt, the new calibrated model artifact updates top-level `intercept` and `coefficients` so score scaling uses calibrated log-odds. Keep `original_model_artifact_id` and the calibrator/report references so the raw model remains auditable. Runtime-only calibrations such as isotonic keep the original coefficients but must not feed additive score scaling.

### Calibration Report Artifact:

```json
{
  "schema_version": "cardre.calibration_report.v1",
  "method": "platt",
  "calibrated_on": "test",
  "cross_validated": true,
  "calibration_error": 0.012326,
  "max_bin_deviation": 0.038100,
  "bins": [
    {"bin": 0, "count": 200, "avg_predicted": 0.021000, "actual_bad_rate": 0.025000, "avg_predicted_raw": 0.015000, "abs_deviation": 0.004000},
    {"bin": 1, "count": 200, "avg_predicted": 0.058000, "actual_bad_rate": 0.055000, "avg_predicted_raw": 0.072000, "abs_deviation": 0.003000},
    {"bin": 2, "count": 200, "avg_predicted": 0.102000, "actual_bad_rate": 0.090000, "avg_predicted_raw": 0.131000, "abs_deviation": 0.012000},
    {"bin": 3, "count": 200, "avg_predicted": 0.154000, "actual_bad_rate": 0.160000, "avg_predicted_raw": 0.198000, "abs_deviation": 0.006000},
    {"bin": 4, "count": 200, "avg_predicted": 0.215000, "actual_bad_rate": 0.205000, "avg_predicted_raw": 0.267000, "abs_deviation": 0.010000},
    {"bin": 5, "count": 200, "avg_predicted": 0.284000, "actual_bad_rate": 0.290000, "avg_predicted_raw": 0.341000, "abs_deviation": 0.006000},
    {"bin": 6, "count": 200, "avg_predicted": 0.361000, "actual_bad_rate": 0.350000, "avg_predicted_raw": 0.419000, "abs_deviation": 0.011000},
    {"bin": 7, "count": 200, "avg_predicted": 0.447000, "actual_bad_rate": 0.460000, "avg_predicted_raw": 0.502000, "abs_deviation": 0.013000},
    {"bin": 8, "count": 200, "avg_predicted": 0.552000, "actual_bad_rate": 0.540000, "avg_predicted_raw": 0.591000, "abs_deviation": 0.012000},
    {"bin": 9, "count": 200, "avg_predicted": 0.701000, "actual_bad_rate": 0.710000, "avg_predicted_raw": 0.723000, "abs_deviation": 0.009000}
  ],
  "pre_calibration_bins": [],
  "warnings": []
}
```

---

## ApplyModel Adapter Detection Snippet

In `adapters.py`, the `apply_logistic` function receives the `model` dict. The calibration block is accessed via `model.get("calibration")`. Here is the exact detection pattern:

```python
# Inside apply_logistic(), after computing raw probabilities but
# before computing scorecard scores:

if model.get("calibration"):
    raw_probs = df["predicted_bad_probability"].to_numpy()
    cal_probs = _apply_calibration(model, store, raw_probs)
    df = df.with_columns([
        pl.Series("predicted_bad_probability", cal_probs, dtype=pl.Float64),
    ])
    # Recompute log-odds from calibrated probs for scorecard scoring
    cal_log_odds = np.log(
        np.clip(cal_probs / np.maximum(1 - cal_probs, 1e-15), 1e-15, None)
    )
    df = df.with_columns([
        pl.Series("raw_model_output", cal_log_odds, dtype=pl.Float64),
    ])
```

For `apply_sklearn_estimator()`, the pattern is simpler (inserted before scorecard computation):

```python
    pred_bad = ...  # from estimator.predict_proba()

    # Apply calibration if present
    if model.get("calibration"):
        pred_bad = _apply_calibration(model, store, pred_bad)

    # Scorecard scaling uses pred_bad (now calibrated)
    if has_scorecard:
        ...
```

---

## Pathway Snippet (Final Phase 2B Layout)

```python
# Phase 2B: WOE transform, logistic regression, raw apply, calibration, score scaling
[
    PathwayStepSpec("woe-transform-train", "cardre.woe_transform_train", category="fit",
                    parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "final-woe-iv", "variable-selection"]),
    PathwayStepSpec("logistic-regression", "cardre.logistic_regression", category="fit",
                    params={"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42},
                    parent_step_ids=["woe-transform-train", "define-metadata"]),

    # Raw apply path for calibration holdout
    PathwayStepSpec("apply-woe-raw", "cardre.apply_woe_mapping", category="apply",
                    params={"woe_unmatched_policy": "fail"},
                    parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "final-woe-iv", "variable-selection"]),
    PathwayStepSpec("apply-model-raw", "cardre.apply_model", category="apply",
                    parent_step_ids=["apply-woe-raw", "logistic-regression"]),
    PathwayStepSpec("calibrate-probabilities", "cardre.calibrate_probabilities", category="fit",
                    params={"calibration_sample": "test"},
                    parent_step_ids=["apply-model-raw", "logistic-regression", "define-metadata"]),

    # Standard score scaling consumes the calibrated model artifact.
    PathwayStepSpec("score-scaling", "cardre.score_scaling", category="fit",
                    params={"base_score": 600, "base_odds": 50.0,
                            "points_to_double_odds": 20, "higher_score_is_lower_risk": True},
                    parent_step_ids=["calibrate-probabilities", "manual-binning", "final-woe-iv"]),
    PathwayStepSpec("build-summary-report", "cardre.build_summary_report", category="fit",
                    parent_step_ids=["score-scaling", "calibrate-probabilities", "final-woe-iv"]),
    PathwayStepSpec("freeze-scorecard-bundle", "cardre.freeze_scorecard_bundle", category="fit",
                    parent_step_ids=["calibrate-probabilities", "score-scaling", "manual-binning", "final-woe-iv", "define-metadata", "variable-selection"]),
],
```

Phase 2C `apply-model` must depend on `calibrate-probabilities`:

```python
    PathwayStepSpec("apply-model", "cardre.apply_model", category="apply",
                    parent_step_ids=["apply-woe", "calibrate-probabilities", "score-scaling", "freeze-scorecard-bundle"]),
```

---

## Verification Gates

Run these commands at the end of each phase, and definitely before declaring done:

```bash
# 1. Unit and integration tests for calibration
pytest tests/test_calibrate.py -v --tb=short 2>&1 | tail -30

# 2. Contract tests (all nodes)
pytest tests/contracts/test_node_contracts.py -v --tb=short 2>&1 | tail -40

# 3. Registry reconciliation (every registered node has contract coverage)
pytest tests/contracts/test_node_contracts.py::test_all_registered_public_nodes_have_contract_coverage -v

# 4. Broad backend test suite (evidence, adapters, nodes)
pytest tests/ -x -q 2>&1 | tail -20

# 5. Frontend tests (if applicable)
# npm run test -- src/config src/utils 2>&1 | tail -20

# 6. Pathway integrity check
python -c "
from sidecar.proof_pathway import SCORECARD_PATHWAY
step_ids = set()
for phase in SCORECARD_PATHWAY.phases:
    for step in phase:
        assert step.step_id not in step_ids, f'Duplicate step_id: {step.step_id}'
        step_ids.add(step.step_id)
        print(f'  {step.step_id:35s} {step.node_type:35s}')
print(f'Total steps: {len(step_ids)} - no duplicates')
"

# 7. Lint and preflight
ruff check --fix cardre/nodes/calibrate.py cardre/modeling/adapters.py cardre/nodes/build/models.py sidecar/proof_pathway.py cardre/_evidence/
make preflight
```

**Frontend tests affected (no change expected, but verify):**

- `frontend/src/utils/evidenceLabels.ts` - new kind label (no test, but verify label renders in `EvidenceCard`)
- `frontend/src/config/stepDisplayMetadata.ts` - new step entries (verify they don't break existing lookup by unique `stepId`)
- `frontend/src/components/inspector/EvidenceCard.tsx` - new `formatSummary()` branch (verify it renders calibration report artifacts)

No existing frontend test should fail because new entries are additive.

**Do not commit or open a PR.** This document is an execution guide only. When all phases are green, a human or orchestrator will decide on commit/PR strategy.
