"""End-to-end: a fitted non-logistic classifier applies through the current
NodeContext pathway.

Batch 4 closes the gap where the catalogue reports non-logistic classifiers
available but ``ApplyModelNode`` rejected every sklearn/ensemble family. The
estimator binary is resolved through ``InputCollection`` (``artifact_ref`` +
``read_bytes``), not a legacy store-backed reader.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

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


def test_decision_tree_fit_then_apply_through_step_runner(tmp_path: Path):
    """DecisionTreeClassifier fit -> ApplyModelNode must score test data with
    the tree's probability column — the current-contract apply path."""
    store = FsArtifactStore(tmp_path)
    pub = StagingOutputPublisher(store)

    train = pl.DataFrame({
        "feature": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "target": ["bad", "good", "bad", "good", "bad", "good"],
    })
    train_staged = pub.publish_table(
        role="train", kind=EvidenceKind.SCORED_DATASET, frame=train,
    )
    store.finalize(train_staged)
    train_ref = _staged_to_ref(train_staged)

    test = pl.DataFrame({"feature": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    test_staged = pub.publish_table(
        role="test", kind=EvidenceKind.SCORED_DATASET, frame=test,
    )
    store.finalize(test_staged)
    test_ref = _staged_to_ref(test_staged)

    catalogue = build_default_catalogue(Settings(launch_mode=False))
    from cardre.nodes.contracts import NodeContext, RuntimeMeta

    # --- Fit the tree through the real node ---
    fit_spec = StepSpec(
        step_id="fit-1", node_type="cardre.decision_tree_classifier",
        node_version="1", category="fit", params={"max_depth": 2, "random_seed": 42},
        params_hash=json_logical_hash({"max_depth": 2, "random_seed": 42}),
        parent_step_ids=[], branch_label="", position=0, canonical_step_id="fit",
    )
    from cardre.nodes.ml_models import DecisionTreeNode

    tree_outputs = StagingOutputPublisher(store)
    tree_context = NodeContext(
        run_id="run-1", plan_version_id="plan-1", step_spec=fit_spec,
        inputs=_TrainInputs(store, train_ref),
        outputs=tree_outputs,
        params={"max_depth": 2, "random_seed": 42},
        runtime=RuntimeMeta("run-1", "plan-1", "fit-1", "cardre.decision_tree_classifier"),
    )
    DecisionTreeNode().run(tree_context)

    for staged in tree_outputs._staged_artifacts:
        store.finalize(staged)
    fit_refs = [_staged_to_ref(s) for s in tree_outputs._staged_artifacts]

    # --- Apply through the real StepRunner ---
    reader = EvidenceReader(store, _StubArtifactRepo(fit_refs + [test_ref]), _NullRepo())
    runner = StepRunner(catalogue, lambda: FsArtifactStore(tmp_path), lambda: reader)

    apply_spec = StepSpec(
        step_id="apply-1", node_type="cardre.apply_model",
        node_version="2", category="apply", params={},
        params_hash="params-hash",
        parent_step_ids=["fit-1", "split-1"], branch_label="", position=1, canonical_step_id="apply",
    )
    result = runner.run_step(
        "plan-1", "run-1", apply_spec,
        {"fit-1": fit_refs, "split-1": [test_ref], "apply-1": []},
        {},
    )

    assert result.status == RunStepStatus.SUCCEEDED, (
        f"apply step must succeed for decision_tree: {result.errors}"
    )
    produced = {s.role for s in result.staged_artifacts}
    assert produced == {"test", "report"}, (
        f"expected test+report outputs, got {sorted(produced)}"
    )

    # --- Assert the scored probabilities come from the tree's predict_proba ---
    scored = next(s for s in result.staged_artifacts if s.role == "test")
    store.finalize(scored)
    scored_df = pl.read_parquet(store.resolve_path(_staged_to_ref(scored)))
    got = scored_df["predicted_bad_probability"].to_numpy()

    from sklearn.tree import DecisionTreeClassifier

    # The node maps bad->1 / good->0 (probability_column_index points at the
    # 'bad' class); fit the reference on binary 0/1 so class 1 is 'bad'.
    y_binary = (train["target"].to_numpy() == "bad").astype(int)
    tree = DecisionTreeClassifier(max_depth=2, random_state=42)
    tree.fit(train["feature"].to_numpy().reshape(-1, 1), y_binary)
    expected = tree.predict_proba(test["feature"].to_numpy().reshape(-1, 1))[:, 1]

    assert np.allclose(got, expected, atol=1e-6), (
        f"decision-tree apply probabilities mismatch: got {got}, expected {expected}"
    )


class _TrainInputs:
    """Minimal InputCollection for the tree-fit step: one train dataset."""

    def __init__(self, store: FsArtifactStore, train_ref: ArtifactRef) -> None:
        self._store = store
        self._ref = train_ref

    def by_role(self, role: str):
        return [self._ref] if role == "train" else []

    def by_kind(self, kind):
        return []

    def first(self, role: str):
        return self._ref if role == "train" else None

    def require(self, role: str, node_type: str):
        if role != "train":
            raise ValueError(f"unexpected require({role})")
        return self._ref

    def read(self, artifact, kind):
        return None

    def read_optional(self, artifact, kind):
        return None

    def read_dataframe(self, artifact):
        return pl.read_parquet(self._store.resolve_path(artifact))

    def read_bytes(self, artifact):
        return self._store.read_bytes(artifact)

    def target_metadata(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
        )

    def find_frozen_bundle(self):
        return None

    def artifact_ref(self, artifact_id, *, physical_hash=None):
        return self._ref if artifact_id == self._ref.artifact_id else None
