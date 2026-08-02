from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import NodeContext, RuntimeMeta
from cardre.nodes.ml_models import DecisionTreeNode


class _Inputs:
    def __init__(self) -> None:
        self._train_artifact = SimpleNamespace(artifact_id="train-artifact", role="train")
        self._frame = pl.DataFrame({
            "feature": [1.0, 2.0, 3.0, 4.0, 1.5, 2.5, 3.5, 0.5],
            "target": ["good", "bad", "good", "bad", "good", "bad", "good", "bad"],
        })

    def require(self, role, node_type):
        assert role == "train"
        return self._train_artifact

    def target_metadata(self):
        return SimpleNamespace(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
        )

    def read_dataframe(self, artifact):
        assert artifact is self._train_artifact
        return self._frame


class _NullRepo:
    def get(self, artifact_id):
        return None


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


def _run_decision_tree(tmp_path: Path):
    store = FsArtifactStore(tmp_path)
    outputs = StagingOutputPublisher(store)
    spec = StepSpec(
        step_id="fit-1",
        node_type="cardre.decision_tree_classifier",
        node_version="1",
        category="fit",
        params={"max_depth": 1, "random_seed": 42},
        params_hash="params-hash",
        parent_step_ids=[],
        canonical_step_id="fit-1",
    )
    context = NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=spec,
        inputs=_Inputs(),
        outputs=outputs,
        params={"max_depth": 1, "random_seed": 42},
        runtime=RuntimeMeta(
            run_id="run-1",
            plan_version_id="plan-1",
            step_id="fit-1",
            node_type="cardre.decision_tree_classifier",
        ),
    )
    return DecisionTreeNode().run(context), store


def test_classifier_emits_json_model_first_for_role_consumers(tmp_path: Path):
    """A downstream `require("model")` returns the parseable JSON model.

    The classifier publishes the JSON model under the ``model`` role and the
    joblib estimator blob under the distinct ``estimator`` role, so role
    consumers always get the JSON model (never the binary).
    """
    result, store = _run_decision_tree(tmp_path)

    model_arts = [a for a in result.staged_artifacts if a.role == "model"]
    estimator_arts = [a for a in result.staged_artifacts if a.role == "estimator"]
    assert len(model_arts) == 1
    assert len(estimator_arts) == 1

    first = model_arts[0]
    assert first.media_type == "application/json", (
        f"model-role artifact must be the JSON model, "
        f"got media_type={first.media_type!r}"
    )
    assert estimator_arts[0].media_type == "application/octet-stream"

    # Publish staged artifacts to the object store (ExecuteRun finalizes after
    # DB registration) so the evidence reader can resolve them by hash.
    for staged in result.staged_artifacts:
        store.finalize(staged)

    # The real evidence reader must read the model-role artifact as
    # MODEL_ARTIFACT evidence; the binary estimator must NOT match the profile.
    reader = EvidenceReader(store, _NullRepo(), _NullRepo())
    typed = reader.find([_staged_to_ref(first)], EvidenceKind.MODEL_ARTIFACT)
    assert typed is not None
    assert typed.model_family == "decision_tree"

    # The JSON model's estimator_reference must point at the staged binary's
    # actual descriptor id (the distinct estimator role must not break
    # estimator identity).
    second = estimator_arts[0]
    import json

    payload = json.loads(store.read_bytes(first))
    assert payload["estimator_reference"]["artifact_id"] == second.provisional_artifact_id
