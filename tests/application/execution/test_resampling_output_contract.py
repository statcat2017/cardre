"""StepRunner-integrated contract tests for resampling / SMOTE.

These nodes publish both a ``train`` parquet and a ``report`` JSON artifact.
Their output contracts must declare both roles; running them through
``StepRunner`` (which validates the output contract) must succeed. These
tests bypass the direct ``node.run()`` path that the provenance tests use,
so a missing ``report`` role in the output contract is caught here.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import polars as pl
import pytest

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.step_runner import StepRunner
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import ArtifactRef, json_logical_hash
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec

RESAMPLE_NODE_TYPE = "cardre.resample_training_data"
SMOTE_NODE_TYPE = "cardre.smote_training_data"

_HAVE_IMBLEARN = importlib.util.find_spec("imblearn") is not None


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


def _imbalanced_frame() -> pl.DataFrame:
    rng = np.random.RandomState(42)
    n_good = 80
    n_bad = 20
    target_data = ["good"] * n_good + ["bad"] * n_bad
    rng.shuffle(target_data)
    return pl.DataFrame({
        "row_id": list(range(100)),
        "feature_a": rng.randn(100).tolist(),
        "feature_b": rng.randn(100).tolist(),
        "target": target_data,
    })


def _publish_inputs(tmp_path) -> tuple[FsArtifactStore, list[ArtifactRef]]:
    """Persist a train parquet and a modelling-metadata definition, return refs."""
    store = FsArtifactStore(tmp_path)
    from cardre.application.execution.output_publisher import StagingOutputPublisher

    pub = StagingOutputPublisher(store)

    train_staged = pub.publish_table(
        role="train", kind=EvidenceKind.SCORED_DATASET, frame=_imbalanced_frame(),
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


def _spec(node_type: str) -> StepSpec:
    return StepSpec(
        step_id="resample-step",
        node_type=node_type,
        node_version="1",
        category="transform",
        params={"strategy": "oversample_minority", "sampling_ratio": 1.0},
        params_hash=json_logical_hash({"strategy": "oversample_minority", "sampling_ratio": 1.0}),
        parent_step_ids=["train-parent", "definition-parent"],
        canonical_step_id="resample-step",
    )


class TestResamplingThroughStepRunner:
    def _run(self, tmp_path, node_type: str):
        store, refs = _publish_inputs(tmp_path)
        reader = EvidenceReader(store, _StubArtifactRepo(refs), _NullRepo())
        cat = build_default_catalogue(Settings(launch_mode=False))
        runner = StepRunner(cat, lambda: FsArtifactStore(tmp_path), lambda: (reader, None))
        return runner.run_step(
            "pv-1", "run-1", _spec(node_type),
            {"train-parent": [refs[0]], "definition-parent": [refs[1]]},
            {},
        )

    def test_resample_passes_output_contract(self, tmp_path):
        result = self._run(tmp_path, RESAMPLE_NODE_TYPE)
        assert result.status == RunStepStatus.SUCCEEDED, (
            f"resample step must pass output contract validation: {result.errors}"
        )
        produced = {s.role for s in result.staged_artifacts}
        assert produced == {"train", "report"}, f"expected train+report, got {sorted(produced)}"

    @pytest.mark.skipif(not _HAVE_IMBLEARN, reason="imblearn not installed")
    def test_smote_passes_output_contract(self, tmp_path):
        result = self._run(tmp_path, SMOTE_NODE_TYPE)
        assert result.status == RunStepStatus.SUCCEEDED, (
            f"smote step must pass output contract validation: {result.errors}"
        )
        produced = {s.role for s in result.staged_artifacts}
        assert produced == {"train", "report"}, f"expected train+report, got {sorted(produced)}"
