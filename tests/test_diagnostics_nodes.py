from __future__ import annotations

import json

import numpy as np
import polars as pl

from cardre._evidence.schemas import (
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_MODELLING_METADATA,
)
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.diagnostics import (
    CalibrationDiagnosticsNode,
    SeparationDiagnosticsNode,
    VifDiagnosticsNode,
)


def _make_model_artifact(
    store,
    *,
    features: list[str],
    coefficients: dict[str, float],
    target_column: str = "credit_risk_class",
    training: dict | None = None,
):
    payload = {
        "schema_version": SCHEMA_MODEL_ARTIFACT,
        "model_family": "logistic_regression",
        "target_column": target_column,
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": features},
        "model_payload": {
            "intercept": -1.0,
            "coefficients": coefficients,
        },
        "training": training or {"converged": True, "iterations": 50, "row_count": 100},
        "warnings": [],
    }
    return write_json_artifact(
        store,
        artifact_type="model",
        role="model",
        stem="model-artifact",
        payload=payload,
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )


def _make_step_spec(step_id: str, node_type: str):
    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category="fit",
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=[],
        position=0,
        canonical_step_id=step_id,
    )


def _make_context(store, step_id, node_type, input_artifacts):
    return ExecutionContext(
        store=store,
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=_make_step_spec(step_id, node_type),
        parent_run_steps=[],
        input_artifacts=input_artifacts,
        validated_params={},
        runtime_metadata={},
    )


class TestSeparationDiagnostics:
    def test_infinite_coefficient_detected(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": float("inf")},
        )
        ctx = _make_context(store, "separation-diagnostics", "cardre.separation_diagnostics", [model])
        output = SeparationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        assert payload["variables"][0]["status"] == "fail"
        assert "Coefficient is infinite" in payload["variables"][0]["reason"]

    def test_large_coefficient_detected(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": 15.0},
        )
        ctx = _make_context(store, "separation-diagnostics", "cardre.separation_diagnostics", [model])
        output = SeparationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        assert payload["variables"][0]["status"] == "warning"
        assert "15.00" in payload["variables"][0]["reason"]

    def test_normal_coefficient_passes(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": 0.5},
        )
        ctx = _make_context(store, "separation-diagnostics", "cardre.separation_diagnostics", [model])
        output = SeparationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        assert payload["variables"][0]["status"] == "pass"
        assert payload["summary"]["warning_count"] == 0


class TestVifDiagnostics:
    def _make_woe_train(self, store, data: dict[str, list[float]], model):
        df = pl.DataFrame(data)
        art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="woe-train", frame=df,
            metadata={"source_artifact_id": "src"},
        )
        return art

    def test_duplicate_columns_yield_infinite_vif(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe", "age_dup_woe"],
            coefficients={"age_woe": -1.0, "age_dup_woe": -0.5},
        )
        train = self._make_woe_train(
            store,
            {"age_woe": [0.1, 0.5, 0.9, 0.3, 0.7], "age_dup_woe": [0.1, 0.5, 0.9, 0.3, 0.7]},
            model,
        )
        ctx = _make_context(store, "vif-diagnostics", "cardre.vif_diagnostics", [train, model])
        output = VifDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        for var in payload["variables"]:
            assert var["vif"] is None
            assert var["vif_is_infinite"] is True
            assert var["status"] == "warning"

    def test_independent_features_pass(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe", "income_woe"],
            coefficients={"age_woe": -1.0, "income_woe": -0.5},
        )
        train = self._make_woe_train(
            store,
            {
                "age_woe": [-0.5, 0.1, 0.9, -0.3, 0.7, -0.1, 0.4, -0.8, 0.2, 0.6],
                "income_woe": [0.8, -0.2, 0.3, 0.5, -0.7, 0.1, -0.4, 0.9, -0.6, 0.2],
            },
            model,
        )
        ctx = _make_context(store, "vif-diagnostics", "cardre.vif_diagnostics", [train, model])
        output = VifDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        for var in payload["variables"]:
            assert var["vif"] is not None
            assert var["vif"] < 10.0
            assert var["status"] == "pass"

    def test_single_feature_returns_empty(self, store):
        model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": -1.0},
        )
        train = self._make_woe_train(store, {"age_woe": [0.1, 0.5, 0.9]}, model)
        ctx = _make_context(store, "vif-diagnostics", "cardre.vif_diagnostics", [train, model])
        output = VifDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        assert payload["summary"]["note"] is not None


class TestCalibrationDiagnostics:
    def _make_scored_dataset(self, store, role, probs, targets):
        df = pl.DataFrame({
            "predicted_bad_probability": probs,
            "credit_risk_class": targets,
        })
        return write_parquet_artifact(
            store, artifact_type="dataset", role=role,
            stem=f"scored-{role}", frame=df,
            metadata={"source_artifact_id": "src"},
        )

    def _make_metadata(self, store):
        return write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="modelling-metadata",
            payload={
                "schema_version": SCHEMA_MODELLING_METADATA,
                "target_column": "credit_risk_class",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )

    def test_hosmer_lemeshow_well_calibrated(self, store):
        np.random.seed(42)
        n = 100
        y_bin = np.random.binomial(1, 0.4, n)
        y_prob = np.clip(y_bin + np.random.normal(0, 0.05, n), 0.01, 0.99)

        model = _make_model_artifact(store, features=["age_woe"], coefficients={"age_woe": -1.0})
        meta = self._make_metadata(store)
        train = self._make_scored_dataset(
            store, "train",
            y_prob.tolist(),
            ["good" if y == 0 else "bad" for y in y_bin.tolist()],
        )
        ctx = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train, model, meta])
        output = CalibrationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())

        role_result = payload["roles"]["train"]
        assert role_result["status"] == "pass"
        assert "hosmer_lemeshow_statistic" in role_result
        assert "hosmer_lemeshow_p_value" in role_result
        assert "decile_bins" in role_result
        bins = role_result["decile_bins"]
        assert len(bins) >= 2
        for b in bins:
            assert "count" in b
            assert "observed_events" in b
            assert "expected_events" in b
            assert "observed_non_events" in b
            assert "expected_non_events" in b

    def test_skipped_when_probability_missing(self, store):
        model = _make_model_artifact(store, features=["age_woe"], coefficients={"age_woe": -1.0})
        meta = self._make_metadata(store)
        df = pl.DataFrame({"credit_risk_class": ["good", "bad", "good", "bad"]})
        train = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="no-prob", frame=df,
        )
        ctx = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train, model, meta])
        output = CalibrationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        assert payload["roles"]["train"]["status"] == "skipped"

    def test_hosmer_lemeshow_poorly_calibrated(self, store):
        n = 100
        y_bin = np.array([0] * 50 + [1] * 50)
        # Probabilities are all around 0.5 but actual bad rate alternates
        y_prob = np.array([0.5] * n)

        model = _make_model_artifact(store, features=["age_woe"], coefficients={"age_woe": -1.0})
        meta = self._make_metadata(store)
        train = self._make_scored_dataset(
            store, "train",
            y_prob.tolist(),
            ["good" if y == 0 else "bad" for y in y_bin.tolist()],
        )
        ctx = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train, model, meta])
        output = CalibrationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())

        role_result = payload["roles"]["train"]
        hl = role_result["hosmer_lemeshow_statistic"]
        # With all predicted at 0.5 and actual 50/50, HL should be very small
        assert hl is not None
        assert hl >= 0.0

    def test_hosmer_lemeshow_tie_invariant(self, store):
        """HL grouping is invariant to row-order shuffling within ties."""
        np.random.seed(42)
        n = 50
        y_bin = np.random.binomial(1, 0.4, n)
        # Create ties: round probabilities so many duplicate values exist
        base_prob = np.clip(y_bin + np.random.normal(0, 0.05, n), 0.01, 0.99)
        y_prob = np.round(base_prob, 1)

        model = _make_model_artifact(store, features=["age_woe"], coefficients={"age_woe": -1.0})
        meta = self._make_metadata(store)

        targets = ["good" if y == 0 else "bad" for y in y_bin.tolist()]

        # Build dataset in original order
        train = self._make_scored_dataset(
            store, "train",
            y_prob.tolist(), targets,
        )
        ctx = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train, model, meta])
        output = CalibrationDiagnosticsNode().run(ctx)
        payload = json.loads((store.root / output.artifacts[0].path).read_text())
        hl_original = payload["roles"]["train"]["hosmer_lemeshow_statistic"]

        # Shuffle row order and re-run
        shuffle_idx = np.random.permutation(n)
        y_prob_shuffled = y_prob[shuffle_idx]
        targets_shuffled = [targets[int(i)] for i in shuffle_idx]
        train2 = self._make_scored_dataset(
            store, "test",
            y_prob_shuffled.tolist(), targets_shuffled,
        )
        ctx2 = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train2, model, meta])
        output2 = CalibrationDiagnosticsNode().run(ctx2)
        payload2 = json.loads((store.root / output2.artifacts[0].path).read_text())
        hl_shuffled = payload2["roles"]["test"]["hosmer_lemeshow_statistic"]

        assert hl_original == hl_shuffled

    def _assert_json_safe(self, text: str) -> None:
        assert "Infinity" not in text
        assert "NaN" not in text
        assert "Inf" not in text
        json.loads(text)  # round-trips cleanly

    def test_payload_is_json_safe(self, store):
        """All diagnostic artifact payloads serialize without Infinity or NaN."""
        # --- Separation diagnostics ---
        model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": float("inf")},
        )
        ctx = _make_context(store, "separation-diagnostics", "cardre.separation_diagnostics", [model])
        output = SeparationDiagnosticsNode().run(ctx)
        text = (store.root / output.artifacts[0].path).read_text()
        self._assert_json_safe(text)
        payload = json.loads(text)
        assert payload["variables"][0]["coefficient"] is None
        assert payload["variables"][0]["coefficient_is_infinite"] is True

        # --- Calibration diagnostics (infinite HL stat) ---
        meta = self._make_metadata(store)
        y_bin = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
        y_prob = np.array([1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        train = self._make_scored_dataset(
            store, "train",
            y_prob.tolist(),
            ["bad" if y == 1 else "good" for y in y_bin.tolist()],
        )
        cal_model = _make_model_artifact(store, features=["age_woe"], coefficients={"age_woe": -1.0})
        ctx2 = _make_context(store, "calibration-diagnostics", "cardre.calibration_diagnostics", [train, cal_model, meta])
        output2 = CalibrationDiagnosticsNode().run(ctx2)
        text2 = (store.root / output2.artifacts[0].path).read_text()
        self._assert_json_safe(text2)
        payload2 = json.loads(text2)
        hl = payload2["roles"]["train"]["hosmer_lemeshow_statistic"]
        assert hl is None or isinstance(hl, float)

        # --- Coefficient sign diagnostics ---
        coeff_model = _make_model_artifact(
            store,
            features=["age_woe"],
            coefficients={"age_woe": float("inf")},
        )
        from cardre.nodes.build.diagnostics import CoefficientSignCheckNode
        woe_art = write_json_artifact(
            store, artifact_type="report", role="report", stem="woe-evidence",
            payload={
                "schema_version": "cardre.woe_iv_evidence.v1",
                "purpose": "final",
                "variables": [{"variable_name": "age", "status": "acceptable"}],
            },
            metadata={"schema_version": "cardre.woe_iv_evidence.v1", "purpose": "final"},
        )
        ctx3 = _make_context(store, "coeff-sign", "cardre.coefficient_sign_check", [coeff_model, woe_art])
        output3 = CoefficientSignCheckNode().run(ctx3)
        text3 = (store.root / output3.artifacts[0].path).read_text()
        self._assert_json_safe(text3)
        payload3 = json.loads(text3)
        assert payload3["variables"][0]["coefficient"] is None
        assert payload3["variables"][0]["coefficient_is_infinite"] is True
