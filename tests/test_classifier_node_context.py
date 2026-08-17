from __future__ import annotations

from types import SimpleNamespace

import polars as pl
from node_harness import FakeArtifact, FakeInputCollection, FakeOutputPublisher, make_context

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.ml_models import DecisionTreeNode
from cardre.nodes.tuning import HyperparameterTuningNode


def _inputs() -> FakeInputCollection:
    frame = pl.DataFrame({
        "feature": [1.0, 2.0, 3.0, 4.0],
        "target": ["good", "bad", "good", "bad"],
    })
    train_artifact = FakeArtifact(role="train", artifact_id="train-artifact", frame=frame)
    return FakeInputCollection(
        roles={"train": [train_artifact]},
        target_metadata=SimpleNamespace(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
        ),
    )


def test_decision_tree_node_uses_node_context_staged_outputs():
    outputs = FakeOutputPublisher()
    context = make_context(
        _inputs(), outputs, {"max_depth": 1, "random_seed": 42},
        node_type="cardre.decision_tree_classifier",
        step_id="fit-1", run_id="run-1",
    )
    result = DecisionTreeNode().run(context)

    assert len(result.staged_artifacts) == 2
    estimator = outputs.by_role("estimator")[0]
    assert estimator.kind is EvidenceKind.MODEL_ARTIFACT
    model = outputs.by_role("model")[0]
    assert model.kind is EvidenceKind.MODEL_ARTIFACT
    assert model.payload["estimator_reference"]["artifact_id"] == estimator.provisional_artifact_id
    assert model.payload["estimator_reference"]["creating_run_id"] == "run-1"
    assert model.payload["estimator_reference"]["creating_run_step_id"] == "fit-1"
    assert result.metrics["feature_count"] == 1


def test_tuning_node_uses_node_context_staged_outputs():
    params = {
        "estimator_type": "decision_tree",
        "param_grid": {"max_depth": [1]},
        "cv_folds": 2,
        "random_seed": 42,
    }
    outputs = FakeOutputPublisher()
    context = make_context(
        _inputs(), outputs, params,
        node_type="cardre.hyperparameter_tuning",
        step_id="tune-1", run_id="run-1",
    )
    result = HyperparameterTuningNode().run(context)

    assert len(result.staged_artifacts) == 2
    estimator = outputs.by_role("estimator")[0]
    assert estimator.kind is EvidenceKind.MODEL_ARTIFACT
    model = outputs.by_role("model")[0]
    assert model.kind is EvidenceKind.MODEL_ARTIFACT
    assert model.payload["estimator_reference"]["artifact_id"] == estimator.provisional_artifact_id
    assert model.payload["estimator_reference"]["creating_run_step_id"] == "tune-1"
    assert result.metrics["best_score"] == 0.5
