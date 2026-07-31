from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import polars as pl

from cardre.domain.step import StepSpec
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.calibrate import CalibrateProbabilitiesNode, _supports_folded_linear_calibration
from cardre.nodes.contracts import NodeContext, NodeResult, RuntimeMeta


class _Inputs:
    def __init__(self, model, frame):
        self.model = model
        self.frame = frame
        self.model_artifact = SimpleNamespace(role="model", artifact_id="model-1")
        self.train_artifact = SimpleNamespace(role="train", artifact_id="train-1")

    def by_role(self, role):
        return {
            "model": [self.model_artifact],
            "train": [self.train_artifact],
        }.get(role, [])

    def require(self, role, node_type):
        artifacts = self.by_role(role)
        if not artifacts:
            raise ValueError(f"{node_type} requires a {role!r} artifact")
        return artifacts[0]

    def read(self, artifact, kind):
        return self.model

    def read_dataframe(self, artifact):
        return self.frame

    def target_metadata(self):
        return SimpleNamespace(
            target_column="bad_flag",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
        )


class _Outputs:
    def __init__(self):
        self.artifacts = []
        self.metrics = {}

    def publish_bytes(self, **kwargs):
        artifact = SimpleNamespace(**kwargs)
        artifact.artifact_id = f"artifact-{len(self.artifacts)}"
        self.artifacts.append(artifact)
        return artifact

    def publish_json(self, **kwargs):
        artifact = SimpleNamespace(**kwargs)
        artifact.artifact_id = f"artifact-{len(self.artifacts)}"
        artifact.logical_hash = "json-hash"
        self.artifacts.append(artifact)
        return artifact

    def add_metric(self, name, value):
        self.metrics[name] = value

    def build_result(self):
        return NodeResult(staged_artifacts=self.artifacts, metrics=self.metrics)


def _context(inputs, outputs, params):
    step_spec = StepSpec(
        step_id="calibrate-1",
        node_type="cardre.calibrate_probabilities",
        node_version="1",
        category="fit",
        params=params,
        params_hash="test",
        parent_step_ids=[],
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=step_spec,
        inputs=inputs,
        outputs=outputs,
        params=params,
        runtime=RuntimeMeta(
            run_id="run-1",
            plan_version_id="plan-1",
            step_id="calibrate-1",
            node_type="cardre.calibrate_probabilities",
        ),
    )


def test_folded_linear_calibration_requires_explicit_intercept():
    without_intercept = ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "decision_tree",
        "target_column": "bad_flag",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"coefficients": {"age_woe": 0.8}},
        "training": {"row_count": 100},
    })
    with_intercept = ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"intercept": -0.4, "coefficients": {"age_woe": 0.8}},
        "training": {"row_count": 100},
    })

    assert not _supports_folded_linear_calibration(without_intercept)
    assert _supports_folded_linear_calibration(with_intercept)


def test_calibration_publishes_binary_calibrator_through_node_context():
    model = ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"intercept": -0.4, "coefficients": {"age_woe": 0.8}},
        "training": {"row_count": 100},
    })
    probabilities = np.concatenate([np.full(20, 0.1), np.full(20, 0.9)])
    frame = pl.DataFrame({
        "bad_flag": ["good"] * 20 + ["bad"] * 20,
        "predicted_bad_probability": probabilities,
    })
    outputs = _Outputs()
    result = CalibrateProbabilitiesNode().run(_context(
        _Inputs(model, frame),
        outputs,
        {"method": "platt", "calibration_sample": "train", "cross_validation": False},
    ))

    binary_artifact = outputs.artifacts[0]
    updated_model = outputs.artifacts[-1].payload
    assert binary_artifact.kind.value == "model_artifact"
    assert binary_artifact.metadata["creating_run_id"] == "run-1"
    assert updated_model["calibration"]["calibrator_artifact_id"] == binary_artifact.artifact_id
    assert result.metrics["calibration_skipped"] is False
