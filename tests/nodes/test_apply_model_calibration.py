from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import polars as pl
import pytest
from sklearn.isotonic import IsotonicRegression

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODEL_ARTIFACT
from cardre.domain.step import StepSpec
from cardre.nodes._params import NodeParams
from cardre.nodes.contracts import NodeContext, RuntimeMeta
from cardre.nodes.validate.apply import ApplyModelNode


class _NullRepo:
    def get(self, artifact_id):
        return None


class _StubArtifactRepo:
    def __init__(self, refs: list[ArtifactRef]):
        self._refs = {r.artifact_id: r for r in refs}

    def get(self, artifact_id):
        return self._refs.get(artifact_id)


def _staged_to_ref(staged: Any) -> ArtifactRef:
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


class _ApplyInputs:
    """Real-IO inputs: model/calibrator/dataframe resolved through the store."""

    def __init__(self, store: FsArtifactStore, refs: list[ArtifactRef]):
        self._store = store
        self._reader = EvidenceReader(store, _NullRepo(), _NullRepo())
        self._refs = {a.artifact_id: a for a in refs}

    def by_role(self, role: str) -> list[Any]:
        return [a for a in self._refs.values() if a.role == role]

    def first(self, role: str) -> Any | None:
        arts = self.by_role(role)
        return arts[0] if arts else None

    def require(self, role: str, node_type: str) -> Any:
        art = self.first(role)
        if art is None:
            raise ValueError(f"{node_type} requires a '{role}' artifact")
        return art

    def read(self, artifact: Any, kind: EvidenceKind) -> Any:
        return self._reader.find([artifact], kind)

    def read_bytes(self, artifact: Any) -> bytes:
        return self._store.read_bytes(artifact)

    def read_dataframe(self, artifact: Any) -> pl.DataFrame:
        return pl.read_parquet(self._store.resolve_path(artifact))

    def artifact_ref(self, artifact_id: str, *, physical_hash: str | None = None) -> Any | None:
        return self._refs.get(artifact_id)

    def find_frozen_bundle(self) -> Any | None:
        return None

    def target_metadata(self) -> Any | None:
        return None


def _context(inputs: Any, outputs: Any) -> NodeContext:
    spec = StepSpec(
        step_id="apply-1",
        node_type="cardre.apply_model",
        node_version="2",
        category="apply",
        params=NodeParams({}),
        params_hash="params-hash",
        parent_step_ids=[],
        canonical_step_id="apply-1",
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=spec,
        inputs=inputs,
        outputs=outputs,
        params=NodeParams({}),
        runtime=RuntimeMeta("run-1", "plan-1", "apply-1", "cardre.apply_model"),
    )


def _raw_prob(x: float) -> float:
    # intercept=0, coefficient=1.0
    return 1.0 / (1.0 + np.exp(-x))


def test_apply_model_node_applies_runtime_calibration(tmp_path: Path):
    """A runtime_probability_transform calibration (e.g. isotonic) must be
    applied to predicted probabilities. The refactored node computed raw
    sigmoid probabilities and silently dropped the calibration block."""
    # Real isotonic calibrator: raw probs ~ [0.12, 0.5, 0.88] map to ~[0, 0.5, 1].
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(np.array([0.12, 0.5, 0.88]), np.array([0.0, 0.5, 1.0]))

    buf = io.BytesIO()
    joblib.dump(calibrator, buf)
    cal_bytes = buf.getvalue()

    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)
    cal_staged = pub.publish_bytes(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        data=cal_bytes,
        media_type="application/octet-stream",
        logical_hash=__import__("hashlib").sha256(cal_bytes).hexdigest(),
        metadata={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "creating_run_id": "run-1",
            "creating_run_step_id": "fit-1",
        },
    )

    model_dict: dict[str, Any] = {
        "schema_version": SCHEMA_MODEL_ARTIFACT,
        "model_family": "logistic_regression",
        "target_column": "target",
        "target_event_value": "bad",
        "class_mapping": {"0": "good", "1": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["x"], "transformation_strategy": "raw_numeric"},
        "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
        "training": {"row_count": 3},
        "calibration": {
            "method": "isotonic",
            "application_mode": "runtime_probability_transform",
            "score_scaling_compatible": False,
            "cross_validated": False,
            "calibrator_artifact_id": cal_staged.provisional_artifact_id,
            "calibrator_logical_hash": cal_staged.logical_hash,
            "calibrator_format": "joblib",
        },
    }
    model_staged = pub.publish_json(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        payload=model_dict,
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )

    df = pl.DataFrame({"x": [-2.0, 0.0, 2.0]})
    data_staged = pub.publish_table(
        role="test",
        kind=EvidenceKind.SCORED_DATASET,
        frame=df,
    )

    for staged in (cal_staged, model_staged, data_staged):
        store.finalize(staged)

    refs = [_staged_to_ref(model_staged), _staged_to_ref(cal_staged), _staged_to_ref(data_staged)]
    inputs = _ApplyInputs(store, refs)
    outputs = StagingOutputPublisher(store)

    ApplyModelNode().run(_context(inputs, outputs))

    # Locate the published test dataset.
    assert outputs._staged_artifacts, "apply_model published no outputs"
    scored = next(
        (a for a in outputs._staged_artifacts if a.role == "test"),
        None,
    )
    assert scored is not None
    store.finalize(scored)
    scored_df = pl.read_parquet(store.resolve_path(_staged_to_ref(scored)))

    raw_probs = [_raw_prob(x) for x in [-2.0, 0.0, 2.0]]
    expected = calibrator.predict(np.array(raw_probs))

    got = scored_df["predicted_bad_probability"].to_numpy()
    assert np.allclose(got, expected, atol=1e-6), (
        f"expected calibrated probabilities {expected}, got raw {got}"
    )


def test_apply_model_partial_inputs_pass_input_contract(tmp_path: Path):
    """An unscaled apply-model step with only `model` + `test` (no scorecard,
    no train/oot) must satisfy ApplyModelNode's input contract — the reviewer
    scenario that the all-required contract wrongly rejected."""
    from cardre.application.execution.contract_validation import validate_input_contract

    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)
    model_staged = pub.publish_json(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        payload={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": "target",
            "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "probability_column_index": 1,
            "feature_contract": {"features": ["x"], "transformation_strategy": "raw_numeric"},
            "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
            "training": {"row_count": 3},
        },
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )
    data_staged = pub.publish_table(
        role="test",
        kind=EvidenceKind.SCORED_DATASET,
        frame=pl.DataFrame({"x": [-2.0, 0.0, 2.0]}),
    )
    for staged in (model_staged, data_staged):
        store.finalize(staged)

    from cardre.nodes.validate.apply import ApplyModelNode

    # The framework-level check must accept model+test only (this is what
    # StepRunner runs before node.run()).
    validate_input_contract(
        ApplyModelNode.__definition__.input_contract,
        [_staged_to_ref(model_staged), _staged_to_ref(data_staged)],
        node_type="cardre.apply_model",
        step_id="apply-1",
    )


def test_apply_model_partial_inputs_through_step_runner(tmp_path: Path):
    """A real StepRunner run of apply_model with only model+test must succeed —
    input AND output contract validation both pass, emitting test + report."""
    from cardre.application.execution.step_runner import StepRunner
    from cardre.bootstrap.node_catalogue import build_default_catalogue
    from cardre.bootstrap.settings import Settings
    from cardre.domain.run import RunStepStatus

    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)

    model_staged = pub.publish_json(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        payload={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": "target",
            "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "probability_column_index": 1,
            "feature_contract": {"features": ["x"], "transformation_strategy": "raw_numeric"},
            "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
            "training": {"row_count": 3},
        },
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )
    test_staged = pub.publish_table(
        role="test",
        kind=EvidenceKind.SCORED_DATASET,
        frame=pl.DataFrame({"x": [-2.0, 0.0, 2.0]}),
    )
    for staged in (model_staged, test_staged):
        store.finalize(staged)

    model_ref = _staged_to_ref(model_staged)
    test_ref = _staged_to_ref(test_staged)
    reader = EvidenceReader(store, _StubArtifactRepo([model_ref, test_ref]), _NullRepo())

    catalogue = build_default_catalogue(Settings(launch_mode=True))
    runner = StepRunner(
        catalogue,
        lambda: FsArtifactStore(tmp_path),
        lambda: (reader, None),
    )

    spec = StepSpec(
        step_id="apply-1",
        node_type="cardre.apply_model",
        node_version="2",
        category="apply",
        params=NodeParams({}),
        params_hash="params-hash",
        parent_step_ids=["parent-1"],
        canonical_step_id="apply-1",
    )
    result = runner.run_step(
        "plan-1", "run-1", spec,
        {"parent-1": [model_ref, test_ref]},
        {},
    )

    assert result.status == RunStepStatus.SUCCEEDED, (
        f"apply_model step must succeed with model+test only: {result.errors}"
    )
    produced = {s.role for s in result.staged_artifacts}
    assert produced == {"test", "report"}, (
        f"expected test+report outputs, got {sorted(produced)}"
    )


def test_apply_model_rejects_invalid_supplied_scorecard(tmp_path: Path):
    """A *supplied* scorecard that fails to parse must fail the apply step.

    Optionality means the role may be absent (the node then scores unscaled);
    it must NOT mean a supplied artifact is silently discarded when it cannot
    be read as a scorecard — that would drop the score column and provenance
    without any signal."""
    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)
    model_staged = pub.publish_json(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        payload={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": "target",
            "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "probability_column_index": 1,
            "feature_contract": {"features": ["x"], "transformation_strategy": "raw_numeric"},
            "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
            "training": {"row_count": 3},
        },
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )
    test_staged = pub.publish_table(
        role="test",
        kind=EvidenceKind.SCORED_DATASET,
        frame=pl.DataFrame({"x": [-2.0, 0.0, 2.0]}),
    )
    # A malformed scorecard: wrong kind (a scored dataset standing in for a
    # scorecard) so the SCORE_SCALING read must fail rather than fall back.
    bad_scorecard_staged = pub.publish_table(
        role="scorecard",
        kind=EvidenceKind.SCORED_DATASET,
        frame=pl.DataFrame({"offset": [1.0], "factor": [1.0]}),
    )
    for staged in (model_staged, test_staged, bad_scorecard_staged):
        store.finalize(staged)

    model_ref = _staged_to_ref(model_staged)
    test_ref = _staged_to_ref(test_staged)
    bad_scorecard_ref = _staged_to_ref(bad_scorecard_staged)
    refs = [model_ref, test_ref, bad_scorecard_ref]
    inputs = _ApplyInputs(store, refs)
    outputs = StagingOutputPublisher(store)

    from cardre.domain.evidence.kinds import EvidenceNotFoundError
    from cardre.nodes.validate.apply import ApplyModelNode

    with pytest.raises(EvidenceNotFoundError):
        ApplyModelNode().run(_context(inputs, outputs))
