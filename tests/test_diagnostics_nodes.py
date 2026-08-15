from __future__ import annotations

import json

import numpy as np
import polars as pl

from cardre._evidence.models.woe import WoeIvEvidence, WoeIvVariable
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.modeling.target import TargetSpec
from cardre.nodes.build.diagnostics import (
    CalibrationDiagnosticsNode,
    CoefficientSignCheckNode,
    SeparationDiagnosticsNode,
    VifDiagnosticsNode,
)


def _make_model_artifact(
    *,
    features: list[str],
    coefficients: dict[str, float],
    target_column: str = "credit_risk_class",
    training: dict | None = None,
) -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
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
    })


def _target_metadata() -> TargetSpec:
    return TargetSpec(
        target_column="credit_risk_class",
        good_values=frozenset({"good"}),
        bad_values=frozenset({"bad"}),
    )


class TestSeparationDiagnostics:
    def test_infinite_coefficient_detected(self, node_harness):
        out = node_harness(
            SeparationDiagnosticsNode,
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": float("inf")},
                ),
            },
        )
        payload = out.staged[0].payload
        assert payload["variables"][0]["status"] == "fail"
        assert "Coefficient is infinite" in payload["variables"][0]["reason"]

    def test_large_coefficient_detected(self, node_harness):
        out = node_harness(
            SeparationDiagnosticsNode,
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": 15.0},
                ),
            },
        )
        payload = out.staged[0].payload
        assert payload["variables"][0]["status"] == "warning"
        assert "15.00" in payload["variables"][0]["reason"]

    def test_normal_coefficient_passes(self, node_harness):
        out = node_harness(
            SeparationDiagnosticsNode,
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": 0.5},
                ),
            },
        )
        payload = out.staged[0].payload
        assert payload["variables"][0]["status"] == "pass"
        assert payload["summary"]["warning_count"] == 0


class TestVifDiagnostics:
    def test_duplicate_columns_yield_infinite_vif(self, node_harness):
        out = node_harness(
            VifDiagnosticsNode,
            frames={"train": pl.DataFrame({
                "age_woe": [0.1, 0.5, 0.9, 0.3, 0.7],
                "age_dup_woe": [0.1, 0.5, 0.9, 0.3, 0.7],
            })},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe", "age_dup_woe"],
                    coefficients={"age_woe": -1.0, "age_dup_woe": -0.5},
                ),
            },
        )
        payload = out.staged[0].payload
        for var in payload["variables"]:
            assert var["vif"] is None
            assert var["vif_is_infinite"] is True
            assert var["status"] == "warning"

    def test_independent_features_pass(self, node_harness):
        out = node_harness(
            VifDiagnosticsNode,
            frames={"train": pl.DataFrame({
                "age_woe": [-0.5, 0.1, 0.9, -0.3, 0.7, -0.1, 0.4, -0.8, 0.2, 0.6],
                "income_woe": [0.8, -0.2, 0.3, 0.5, -0.7, 0.1, -0.4, 0.9, -0.6, 0.2],
            })},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe", "income_woe"],
                    coefficients={"age_woe": -1.0, "income_woe": -0.5},
                ),
            },
        )
        payload = out.staged[0].payload
        for var in payload["variables"]:
            assert var["vif"] is not None
            assert var["vif"] < 10.0
            assert var["status"] == "pass"

    def test_single_feature_returns_empty(self, node_harness):
        out = node_harness(
            VifDiagnosticsNode,
            frames={"train": pl.DataFrame({"age_woe": [0.1, 0.5, 0.9]})},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
        )
        payload = out.staged[0].payload
        assert payload["summary"]["note"] is not None


class TestCalibrationDiagnostics:
    def _scored(self, role, probs, targets) -> pl.DataFrame:
        return pl.DataFrame({
            "predicted_bad_probability": probs,
            "credit_risk_class": targets,
        })

    def test_hosmer_lemeshow_well_calibrated(self, node_harness):
        np.random.seed(42)
        n = 100
        y_bin = np.random.binomial(1, 0.4, n)
        y_prob = np.clip(y_bin + np.random.normal(0, 0.05, n), 0.01, 0.99)

        out = node_harness(
            CalibrationDiagnosticsNode,
            frames={"train": self._scored(
                "train", y_prob.tolist(),
                ["good" if y == 0 else "bad" for y in y_bin.tolist()],
            )},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
            target_metadata=_target_metadata(),
        )
        payload = out.staged[0].payload
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

    def test_skipped_when_probability_missing(self, node_harness):
        out = node_harness(
            CalibrationDiagnosticsNode,
            frames={"train": pl.DataFrame({
                "credit_risk_class": ["good", "bad", "good", "bad"],
            })},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
            target_metadata=_target_metadata(),
        )
        payload = out.staged[0].payload
        assert payload["roles"]["train"]["status"] == "skipped"

    def test_hosmer_lemeshow_tie_invariant(self, node_harness):
        np.random.seed(42)
        n = 50
        y_bin = np.random.binomial(1, 0.4, n)
        base_prob = np.clip(y_bin + np.random.normal(0, 0.05, n), 0.01, 0.99)
        y_prob = np.round(base_prob, 1)
        targets = ["good" if y == 0 else "bad" for y in y_bin.tolist()]

        out = node_harness(
            CalibrationDiagnosticsNode,
            frames={"train": self._scored("train", y_prob.tolist(), targets)},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
            target_metadata=_target_metadata(),
        )
        hl_original = out.staged[0].payload["roles"]["train"]["hosmer_lemeshow_statistic"]

        shuffle_idx = np.random.permutation(n)
        out2 = node_harness(
            CalibrationDiagnosticsNode,
            frames={"test": self._scored(
                "test", y_prob[shuffle_idx].tolist(),
                [targets[int(i)] for i in shuffle_idx],
            )},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
            target_metadata=_target_metadata(),
        )
        hl_shuffled = out2.staged[0].payload["roles"]["test"]["hosmer_lemeshow_statistic"]
        assert hl_original == hl_shuffled

    def _assert_json_safe(self, payload: dict) -> None:
        text = json.dumps(payload)
        assert "Infinity" not in text
        assert "NaN" not in text
        assert "Inf" not in text
        json.loads(text)

    def test_payload_is_json_safe(self, node_harness):
        out = node_harness(
            SeparationDiagnosticsNode,
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": float("inf")},
                ),
            },
        )
        payload = out.staged[0].payload
        self._assert_json_safe(payload)
        assert payload["variables"][0]["coefficient"] is None
        assert payload["variables"][0]["coefficient_is_infinite"] is True

        y_bin = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
        y_prob = np.array([1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        out2 = node_harness(
            CalibrationDiagnosticsNode,
            frames={"train": self._scored(
                "train", y_prob.tolist(),
                ["bad" if y == 1 else "good" for y in y_bin.tolist()],
            )},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": -1.0},
                ),
            },
            target_metadata=_target_metadata(),
        )
        payload2 = out2.staged[0].payload
        self._assert_json_safe(payload2)
        hl = payload2["roles"]["train"]["hosmer_lemeshow_statistic"]
        assert hl is None or isinstance(hl, float)

        from node_harness import FakeArtifact as _FakeArtifact
        out3 = node_harness(
            CoefficientSignCheckNode,
            roles={
                "report": [
                    _FakeArtifact(
                        "report",
                        metadata={"schema_version": "cardre.woe_iv_evidence.v1", "purpose": "final"},
                    ),
                ],
            },
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _make_model_artifact(
                    features=["age_woe"], coefficients={"age_woe": float("inf")},
                ),
                EvidenceKind.WOE_IV_EVIDENCE: WoeIvEvidence(
                    variables=[WoeIvVariable(variable_name="age", status="acceptable")],
                ),
            },
        )
        payload3 = out3.staged[0].payload
        self._assert_json_safe(payload3)
        assert payload3["variables"][0]["coefficient"] is None
        assert payload3["variables"][0]["coefficient_is_infinite"] is True
