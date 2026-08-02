from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import polars as pl

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.evidence.kinds import EvidenceKind
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


def _context(inputs, outputs, params):
    step_spec = StepSpec(
        step_id="calibrate-1",
        node_type="cardre.calibrate_probabilities",
        node_version="1",
        category="fit",
        params=params,
        params_hash="test",
        parent_step_ids=[],
        canonical_step_id="calibrate-1",
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


def test_calibration_publishes_binary_calibrator_through_node_context(tmp_path: Path):
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
    store = FsArtifactStore(tmp_path)
    outputs: Any = StagingOutputPublisher(store)
    result = CalibrateProbabilitiesNode().run(_context(
        _Inputs(model, frame),
        outputs,
        {"method": "platt", "calibration_sample": "train", "cross_validation": False},
    ))

    assert isinstance(result, NodeResult)
    staged = result.staged_artifacts
    assert len(staged) == 3
    # Publish order: report, JSON model, calibrator blob. The JSON model must
    # precede the binary so role consumers select the parseable model.
    report_artifact = staged[0]
    model_artifact = staged[1]
    binary_artifact = staged[2]
    assert model_artifact.media_type == "application/json"
    assert binary_artifact.media_type == "application/octet-stream"
    assert report_artifact.media_type == "application/json"
    assert report_artifact.provisional_artifact_id

    model_payload = json.loads(model_artifact.staging_path.read_bytes())
    assert model_payload["calibration"]["calibrator_artifact_id"] == binary_artifact.provisional_artifact_id
    assert model_payload["calibration"]["calibration_report_artifact_id"] == report_artifact.provisional_artifact_id
    assert result.metrics["calibration_skipped"] is False


def test_calibrate_emits_json_model_first_for_role_consumers(tmp_path: Path):
    """A downstream `require("model")` returns the first artifact by role.

    It must be the updated JSON model, not the joblib calibrator blob — the
    MODEL_ARTIFACT profile rejects the binary on media type, so consumers would
    hard-fail with EvidenceNotFoundError (same class as the classifier fix).
    """
    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.domain.artifacts import ArtifactRef

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
    store = FsArtifactStore(tmp_path)
    outputs: Any = StagingOutputPublisher(store)
    result = CalibrateProbabilitiesNode().run(_context(
        _Inputs(model, frame),
        outputs,
        {"method": "platt", "calibration_sample": "train", "cross_validation": False},
    ))

    model_arts = [a for a in result.staged_artifacts if a.role == "model"]
    assert len(model_arts) == 2
    first = model_arts[0]
    assert first.media_type == "application/json", (
        f"first-by-role model artifact must be the JSON model, "
        f"got media_type={first.media_type!r}"
    )

    for staged in result.staged_artifacts:
        store.finalize(staged)

    class _NullRepo:
        def get(self, artifact_id):
            return None

    def to_ref(staged):
        return ArtifactRef(
            artifact_id=staged.provisional_artifact_id,
            artifact_type=staged.artifact_type,
            role=staged.role,
            path=str(staged.staging_path),
            physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash,
            media_type=staged.media_type,
            metadata=staged.metadata,
        )

    reader = EvidenceReader(store, _NullRepo(), _NullRepo())
    typed = reader.find([to_ref(first)], EvidenceKind.MODEL_ARTIFACT)
    assert typed is not None
    assert typed.model_family == "logistic_regression"


def test_calibrator_binary_passes_output_contract_validation(tmp_path: Path):
    """The staged calibrator binary must satisfy the declared output contract.

    `StepRunner` runs `validate_output_contract` before publication, so a
    fitted calibrator that omits `metadata["schema_version"]` fails the run
    with ``schema version '' ...``. Unit tests that call `run()` directly
    bypass contract validation, which is exactly why this regression is
    invisible to them.
    """
    from cardre.application.execution.contract_validation import validate_output_contract

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
    store = FsArtifactStore(tmp_path)
    outputs: Any = StagingOutputPublisher(store)
    result = CalibrateProbabilitiesNode().run(_context(
        _Inputs(model, frame),
        outputs,
        {"method": "platt", "calibration_sample": "train", "cross_validation": False},
    ))

    # This is what StepRunner._validate_output_roles does before publication.
    validate_output_contract(
        CalibrateProbabilitiesNode.__definition__.output_contract,
        result.staged_artifacts,
        node_type="cardre.calibrate_probabilities",
        step_id="calibrate-1",
    )


def test_calibration_skipped_path_uses_real_publisher_contract(tmp_path: Path):
    """The too-few-rows skip path still reads the staged report artifact ID."""
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
    probabilities = np.concatenate([np.full(5, 0.1), np.full(5, 0.9)])
    frame = pl.DataFrame({
        "bad_flag": ["good"] * 5 + ["bad"] * 5,
        "predicted_bad_probability": probabilities,
    })
    store = FsArtifactStore(tmp_path)
    outputs: Any = StagingOutputPublisher(store)
    result = CalibrateProbabilitiesNode().run(_context(
        _Inputs(model, frame),
        outputs,
        {"method": "platt", "calibration_sample": "train", "cross_validation": False},
    ))

    assert isinstance(result, NodeResult)
    staged = result.staged_artifacts
    assert len(staged) == 2  # no calibrator bytes, just report + model
    report_artifact = staged[0]
    model_artifact = staged[1]
    assert report_artifact.media_type == "application/json"
    assert report_artifact.provisional_artifact_id

    model_payload = json.loads(model_artifact.staging_path.read_bytes())
    assert model_payload["calibration"]["calibrator_artifact_id"] == ""
    assert model_payload["calibration"]["calibration_report_artifact_id"] == report_artifact.provisional_artifact_id
    assert result.metrics["calibration_skipped"] is True
