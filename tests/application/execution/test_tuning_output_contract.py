"""StepRunner-integrated contract test for HyperparameterTuningNode.

The tuning node publishes a JSON model (role ``model``) and a binary
estimator (role ``estimator``). Both must pass output-contract validation
through the real StepRunner — the JSON model against the strict MODEL_ARTIFACT
contract and the binary against the octet-stream estimator contract.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.application.execution.step_runner import StepRunner
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import ArtifactRef, json_logical_hash
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec


class _NullRepo:
    def get(self, artifact_id):
        return None


class _StubArtifactRepo:
    def __init__(self, refs: list[ArtifactRef]):
        self._refs = {r.artifact_id: r for r in refs}

    def get(self, artifact_id):
        return self._refs.get(artifact_id)


def _staged_to_ref(staged) -> ArtifactRef:
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


def _train_frame() -> pl.DataFrame:
    rng = np.random.RandomState(42)
    target = ["good"] * 80 + ["bad"] * 20
    rng.shuffle(target)
    return pl.DataFrame({
        "row_id": list(range(100)),
        "feature_a": rng.randn(100).tolist(),
        "feature_b": rng.randn(100).tolist(),
        "target": target,
    })


def _publish_inputs(tmp_path):
    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)

    train_staged = pub.publish_table(
        role="train", kind=EvidenceKind.SCORED_DATASET, frame=_train_frame(),
    )
    store.finalize(train_staged)
    train_ref = _staged_to_ref(train_staged)

    meta_staged = pub.publish_json(
        role="definition",
        kind=EvidenceKind.MODELLING_METADATA,
        payload={
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
            "indeterminate_values": [],
        },
        metadata={"schema_version": SCHEMA_MODELLING_METADATA},
    )
    store.finalize(meta_staged)
    meta_ref = _staged_to_ref(meta_staged)

    return store, [train_ref, meta_ref]


def test_tuning_passes_output_contract_and_emits_model_and_estimator(tmp_path):
    store, refs = _publish_inputs(tmp_path)
    reader = EvidenceReader(store, _StubArtifactRepo(refs), _NullRepo())
    cat = build_default_catalogue(Settings(launch_mode=False))
    runner = StepRunner(cat, lambda: FsArtifactStore(tmp_path), lambda: (reader, None))

    spec = StepSpec(
        step_id="tune-1",
        node_type="cardre.hyperparameter_tuning",
        node_version="1",
        category="fit",
        params={
            "estimator_type": "decision_tree",
            "param_grid": {"max_depth": [1]},
            "cv_folds": 2,
            "random_seed": 42,
        },
        params_hash=json_logical_hash({
            "estimator_type": "decision_tree",
            "param_grid": {"max_depth": [1]},
            "cv_folds": 2,
            "random_seed": 42,
        }),
        parent_step_ids=["train-parent", "definition-parent"],
        canonical_step_id="tune-1",
    )

    result = runner.run_step(
        "pv-1", "run-1", spec,
        {"train-parent": [refs[0]], "definition-parent": [refs[1]]},
        {},
    )

    assert result.status == RunStepStatus.SUCCEEDED, (
        f"tuning step must pass output-contract validation: {result.errors}"
    )
    roles = {s.role for s in result.staged_artifacts}
    assert roles == {"model", "estimator"}, f"expected model+estimator, got {sorted(roles)}"

    model = next(s for s in result.staged_artifacts if s.role == "model")
    estimator = next(s for s in result.staged_artifacts if s.role == "estimator")
    assert model.media_type == "application/json"
    assert estimator.media_type == "application/octet-stream"
