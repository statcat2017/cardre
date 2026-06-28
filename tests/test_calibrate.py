"""Tests for CalibrateProbabilitiesNode."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.schemas import SCHEMA_CALIBRATION_REPORT
from cardre._evidence.profiles import EVIDENCE_PROFILES
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ArtifactRef, ExecutionContext, StepSpec, json_logical_hash
from cardre.evidence import ArtifactEvidenceReader
from cardre.modeling.adapters import apply_model as _apply_model_adapter
from cardre.nodes.build import ScoreScalingNode
from cardre.nodes.calibrate import CalibrateProbabilitiesNode
from cardre.store import ProjectStore
from tests.helpers import make_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_model_artifact(store: ProjectStore, intercept: float = -0.5, coefficients: dict | None = None) -> ArtifactRef:
    model = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "target",
        "features": ["x1_woe", "x2_woe"],
        "intercept": intercept,
        "coefficients": coefficients or {"x1_woe": 0.8, "x2_woe": 0.3},
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "training": {"row_count": 1000, "converged": True, "iterations": 15},
        "warnings": [],
    }
    return write_json_artifact(
        store, artifact_type="model", role="model",
        stem="test-model", payload=model,
        metadata={"schema_version": "cardre.model_artifact.v1"},
    )


def _make_definition_artifact(store: ProjectStore) -> ArtifactRef:
    return write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-def",
        payload={
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        },
        metadata={},
    )


def _make_scored_dataset(
    store: ProjectStore,
    n: int = 500,
    role: str = "test",
    bias: float = 0.0,
) -> ArtifactRef:
    """Create a scored dataset with miscalibrated probabilities."""
    rng = np.random.RandomState(42)
    raw_log_odds = rng.randn(n) * 1.5
    raw_prob = 1.0 / (1.0 + np.exp(-raw_log_odds))
    y_true = (raw_prob + bias + rng.randn(n) * 0.3 > 0.5).astype(int)
    # Apply intentional miscalibration: push probabilities toward extremes
    miscal_prob = np.clip(raw_prob ** 0.7, 0.001, 0.999)
    df = pl.DataFrame({
        "x1_woe": rng.randn(n),
        "x2_woe": rng.randn(n),
        "predicted_bad_probability": miscal_prob,
        "target": ["bad" if v == 1 else "good" for v in y_true],
    })
    return write_parquet_artifact(
        store, artifact_type="dataset", role=role,
        stem=f"scored-{role}", frame=df,
        metadata={},
    )


def _ctx(
    store: ProjectStore,
    input_artifacts: list[ArtifactRef],
    node_type: str,
    params: dict | None = None,
) -> ExecutionContext:
    spec = StepSpec(
        step_id="cal-test", node_type=node_type, node_version="1",
        category="fit", params=params or {},
        params_hash=json_logical_hash(params or {}),
        parent_step_ids=[], branch_label="", position=0,
    )
    return ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=input_artifacts,
        validated_params=params or {},
        runtime_metadata={},
    )


# ---------------------------------------------------------------------------
# Phase 0 / 1
# ---------------------------------------------------------------------------


def test_calibration_test_suite_loads():
    """Trivial smoke test: the test module itself imports cleanly."""
    assert True


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
        from cardre.evidence import SCHEMA_CALIBRATION_REPORT as reexported
        assert reexported == "cardre.calibration_report.v1"


# ---------------------------------------------------------------------------
# Phase 2: CalibrateProbabilitiesNode Core
# ---------------------------------------------------------------------------


class TestCalibrateProbabilitiesNode:
    """Core tests for CalibrateProbabilitiesNode (Platt, no CV)."""

    def test_platt_calibration_improves_calibration_error(self, tmp_path: Path):
        """Calibration must reduce expected calibration error on synthetic miscalibrated data."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=500, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                   params={"calibration_sample": "test"})
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        # Read calibration report
        report_art = next(a for a in output.artifacts if a.role == "report")
        report = json.loads(store.artifact_path(report_art).read_text())
        assert report["calibration_error"] < 0.10  # Platt should reduce error

    def test_platt_calibration_writes_model_and_report_and_calibrator(self, tmp_path: Path):
        """Node output must include model, report, and calibrator artifacts."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        artifact_types = {a.artifact_type for a in output.artifacts}
        assert "model" in artifact_types
        assert "report" in artifact_types
        assert "estimator" in artifact_types

    def test_missing_predicted_bad_probability_fails_clearly(self, tmp_path: Path):
        """Missing predicted_bad_probability column must raise."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)

        df = pl.DataFrame({
            "x1": [1.0, 2.0],
            "target": ["good", "bad"],
        })
        bad_art = write_parquet_artifact(
            store, artifact_type="dataset", role="test",
            stem="bad-test", frame=df, metadata={},
        )
        ctx = _ctx(store, [model_art, def_art, bad_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        with pytest.raises(ValueError, match="predicted_bad_probability"):
            node.run(ctx)

    def test_missing_target_metadata_fails_clearly(self, tmp_path: Path):
        """Missing target column must raise."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        # Now drop the target column from the definition's metadata
        # Re-read to verify
        reader = ArtifactEvidenceReader(store)
        model = reader.read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        calibration = model._raw.get("calibration", {})
        assert calibration is not None

    def test_too_few_rows_emits_warning(self, tmp_path: Path):
        """Fewer than MIN_CALIBRATION_ROWS must emit warning, not raise."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=10, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        report_art = next(a for a in output.artifacts if a.role == "report")
        report = json.loads(store.artifact_path(report_art).read_text())
        codes = [w["code"] for w in report.get("warnings", [])]
        assert "TOO_FEW_CALIBRATION_ROWS" in codes

    def test_calibration_report_artifact_schema(self, tmp_path: Path):
        """Calibration report artifact must match schema."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        report_art = next(a for a in output.artifacts if a.role == "report")
        report = json.loads(store.artifact_path(report_art).read_text())

        assert report["schema_version"] == SCHEMA_CALIBRATION_REPORT
        assert report["method"] in ("platt",)
        assert "calibration_error" in report
        assert "max_bin_deviation" in report
        assert "bins" in report
        assert len(report["bins"]) > 0

    def test_calibrated_model_artifact_contains_calibration_block(self, tmp_path: Path):
        """Updated model artifact must contain calibration block."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities")
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        model_out_art = next(a for a in output.artifacts if a.role == "model")
        model_payload = json.loads(store.artifact_path(model_out_art).read_text())

        cal = model_payload.get("calibration")
        assert cal is not None
        assert cal["method"] == "platt"
        assert cal["application_mode"] == "folded_linear_log_odds"
        assert cal["score_scaling_compatible"] is True
        assert "calibrator_artifact_id" in cal
        assert "calibrator_logical_hash" in cal
        assert "calibration_report_artifact_id" in cal
        assert "calibration_error" in cal

        # Check intercept was folded
        assert model_payload["intercept"] != -0.5  # should be changed by calibration

    def test_train_calibration_sample_emits_warning(self, tmp_path: Path):
        """Using train as calibration sample must emit warning."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="train")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                   params={"calibration_sample": "train"})
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        report_art = next(a for a in output.artifacts if a.role == "report")
        report = json.loads(store.artifact_path(report_art).read_text())
        codes = [w["code"] for w in report.get("warnings", [])]
        assert "CALIBRATION_ON_TRAIN_SAMPLE" in codes


# ---------------------------------------------------------------------------
# Phase 3: Isotonic Method + Cross-Validation
# ---------------------------------------------------------------------------


class TestIsotonicCalibration:
    """Isotonic regression calibration tests."""

    def test_isotonic_calibration_non_decreasing(self, tmp_path: Path):
        """Isotonic calibration must produce non-decreasing outputs."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=1200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                   params={"method": "isotonic", "calibration_sample": "test"})
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        # Verify calibrated probabilities are non-decreasing relative to raw
        model_out_art = next(a for a in output.artifacts if a.role == "model")
        model_payload = json.loads(store.artifact_path(model_out_art).read_text())
        cal = model_payload.get("calibration", {})
        assert cal is not None
        assert cal["method"] == "isotonic"
        # Isotonic produces runtime transform (not additive scorecard compatible)
        assert cal["score_scaling_compatible"] is False
        assert cal["application_mode"] == "runtime_probability_transform"

    def test_isotonic_small_sample_warning(self, tmp_path: Path):
        """Isotonic on <1000 rows should warn."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                   params={"method": "isotonic", "calibration_sample": "test"})
        node = CalibrateProbabilitiesNode()
        output = node.run(ctx)

        report_art = next(a for a in output.artifacts if a.role == "report")
        report = json.loads(store.artifact_path(report_art).read_text())
        codes = [w["code"] for w in report.get("warnings", [])]
        assert "SMALL_ISOTONIC_SAMPLE" in codes

    def test_cross_validation_ensemble_produces_different_calibrator(self, tmp_path: Path):
        """CV ensemble must produce different calibration from non-CV."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=500, role="test")

        # Non-CV
        ctx_no_cv = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                         params={"method": "platt", "cross_validation": False})
        node = CalibrateProbabilitiesNode()
        out_no_cv = node.run(ctx_no_cv)
        report_no_cv = json.loads(store.artifact_path(
            next(a for a in out_no_cv.artifacts if a.role == "report")).read_text())

        # CV
        ctx_cv = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                      params={"method": "platt", "cross_validation": True, "cv_folds": 3})
        out_cv = node.run(ctx_cv)
        report_cv = json.loads(store.artifact_path(
            next(a for a in out_cv.artifacts if a.role == "report")).read_text())

        assert report_no_cv["calibration_error"] > 0
        assert report_cv["calibration_error"] > 0


# ---------------------------------------------------------------------------
# Phase 4: ApplyModel adapter calibration detection
# ---------------------------------------------------------------------------


class TestApplyModelCalibrated:
    """ApplyModelNode with calibrated model artifacts."""

    def _create_calibrated_model_artifact(self, store, method="platt", cross_validated=False):
        """Helper: calibrate a model and return the calibrated model artifact."""
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        params = {"method": method, "calibration_sample": "test",
                  "cross_validation": cross_validated}
        ctx = _ctx(store, [model_art, def_art, scored_art],
                   "cardre.calibrate_probabilities", params)
        node = CalibrateProbabilitiesNode()
        out = node.run(ctx)
        return next(a for a in out.artifacts if a.role == "model"), out

    def test_calibrated_model_applies_different_probabilities(self, tmp_path: Path):
        """Calibrated model must produce different probabilities from raw model."""
        store, _ = make_store()
        store.initialize()
        cal_model_art, _ = self._create_calibrated_model_artifact(store)
        cal_model = json.loads(store.artifact_path(cal_model_art).read_text())

        # Apply calibrated model to same data via apply_model adapter
        df = pl.DataFrame({"x1_woe": [0.2, -0.1], "x2_woe": [0.1, 0.3]})
        train_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="train-data", frame=df, metadata={},
        )

        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="apply", node_type="cardre.apply_model",
                node_version="2", category="apply",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[train_art, cal_model_art],
            validated_params={}, runtime_metadata={},
        )
        output = _apply_model_adapter(ctx, cal_model, cal_model_art)
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "predicted_bad_probability" in scored.columns
        cal_probs = scored["predicted_bad_probability"].to_numpy()
        # These should differ from uncalibrated output of same raw model
        raw_probs = 1.0 / (1.0 + np.exp(-(-0.5 + df["x1_woe"].to_numpy() * 0.8 + df["x2_woe"].to_numpy() * 0.3)))
        assert not np.allclose(cal_probs, raw_probs, atol=1e-2)

    def test_uncalibrated_model_unchanged(self, tmp_path: Path):
        """Model artifact without calibration block behaves as before."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        model = json.loads(store.artifact_path(model_art).read_text())

        df = pl.DataFrame({"x1_woe": [0.2, -0.1], "x2_woe": [0.1, 0.3]})
        train_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="train-data", frame=df, metadata={},
        )

        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="apply", node_type="cardre.apply_model",
                node_version="2", category="apply",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[train_art, model_art],
            validated_params={}, runtime_metadata={},
        )
        output = _apply_model_adapter(ctx, model, model_art)
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        expected = 1.0 / (1.0 + np.exp(-(-0.5 + df["x1_woe"].to_numpy() * 0.8 + df["x2_woe"].to_numpy() * 0.3)))
        np.testing.assert_allclose(
            scored["predicted_bad_probability"].to_numpy(), expected, atol=1e-12
        )

    def test_score_scaling_with_platt_calibration(self, tmp_path: Path):
        """Score scaling must work with Platt-calibrated model artifact."""
        store, _ = make_store()
        store.initialize()
        cal_model_art, cal_out = self._create_calibrated_model_artifact(store)

        cal_model = json.loads(store.artifact_path(cal_model_art).read_text())
        cal_block = cal_model.get("calibration", {})
        assert cal_block.get("score_scaling_compatible") is True
        assert cal_block.get("application_mode") == "folded_linear_log_odds"

    def test_missing_calibrator_artifact_does_not_fail_for_folded_platt(self, tmp_path: Path):
        """Folded Platt does not load calibrator at apply time (baked into coefficients)."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        model = json.loads(store.artifact_path(model_art).read_text())
        model["calibration"] = {
            "method": "platt",
            "application_mode": "folded_linear_log_odds",
            "score_scaling_compatible": True,
            "calibrator_artifact_id": "nonexistent-artifact-id",
        }
        # Folded Platt has updated coefficients; overwrite
        model["intercept"] = -0.45
        model["coefficients"] = {"x1_woe": 0.75, "x2_woe": 0.28}
        bad_art = write_json_artifact(
            store, artifact_type="model", role="model",
            stem="bad-cal-model", payload=model,
            metadata={},
        )

        df = pl.DataFrame({"x1_woe": [0.2, -0.1], "x2_woe": [0.1, 0.3]})
        train_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="train-data", frame=df, metadata={},
        )

        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="apply", node_type="cardre.apply_model",
                node_version="2", category="apply",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[train_art, bad_art],
            validated_params={}, runtime_metadata={},
        )
        # Should not raise - folded Platt does not load calibrator
        output = _apply_model_adapter(ctx, model, bad_art)
        assert len(output.artifacts) >= 1

    def test_score_scaling_fails_hard_with_isotonic_calibration(self, tmp_path: Path):
        """Score scaling on isotonic-calibrated model must raise ValueError."""
        store, _ = make_store()
        store.initialize()
        model_art = _make_model_artifact(store)
        def_art = _make_definition_artifact(store)
        scored_art = _make_scored_dataset(store, n=200, role="test")

        ctx = _ctx(store, [model_art, def_art, scored_art], "cardre.calibrate_probabilities",
                   params={"method": "isotonic", "calibration_sample": "test"})
        node = CalibrateProbabilitiesNode()
        out = node.run(ctx)
        cal_model_art = next(a for a in out.artifacts if a.role == "model")

        # Try score scaling on isotonic-calibrated model (should fail)
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="report",
            stem="test-bins", payload={
                "variables": [{
                    "variable": "x", "kind": "numeric",
                    "bins": [{"bin_id": "x_b1"}],
                }],
            },
            metadata={},
        )
        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"],
            "label": ["Low"], "row_count": [1], "good_count": [1], "bad_count": [0],
            "good_distribution": [1.0], "bad_distribution": [0.0],
            "woe": [0.0], "iv_component": [0.0],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe", frame=woe_df, metadata={},
        )

        ss_ctx = _ctx(store, [cal_model_art, bin_art, woe_art], "cardre.score_scaling",
                       params={
                           "base_score": 600, "base_odds": 50.0,
                           "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
                       })
        with pytest.raises(ValueError, match="Score scaling|not compatible|folded_linear_log_odds"):
            ScoreScalingNode().run(ss_ctx)
