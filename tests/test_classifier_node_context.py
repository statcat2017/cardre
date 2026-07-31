from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import NodeContext, NodeResult, RuntimeMeta
from cardre.nodes.ml_models import DecisionTreeNode
from cardre.nodes.tuning import HyperparameterTuningNode


class _Inputs:
    def __init__(self) -> None:
        self._train_artifact = SimpleNamespace(artifact_id="train-artifact")
        self._frame = pl.DataFrame({
            "feature": [1.0, 2.0, 3.0, 4.0],
            "target": ["good", "bad", "good", "bad"],
        })

    def require(self, role: str, node_type: str):
        assert role == "train"
        assert node_type in {
            "cardre.decision_tree_classifier",
            "cardre.hyperparameter_tuning",
        }
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


class _Outputs:
    def __init__(self) -> None:
        self.staged_artifacts = []
        self.metrics = {}

    def publish_bytes(self, **kwargs):
        artifact = SimpleNamespace(
            provisional_artifact_id="estimator-artifact",
            logical_hash=kwargs["logical_hash"],
            physical_hash="estimator-physical-hash",
        )
        self.staged_artifacts.append(artifact)
        self.estimator = kwargs
        return artifact

    def publish_json(self, **kwargs):
        artifact = SimpleNamespace(provisional_artifact_id="model-artifact")
        self.staged_artifacts.append(artifact)
        self.model = kwargs
        return artifact

    def add_metric(self, name: str, value):
        self.metrics[name] = value

    def build_result(self):
        return NodeResult(
            staged_artifacts=self.staged_artifacts,
            metrics=self.metrics,
        )


def test_decision_tree_node_uses_node_context_staged_outputs():
    step_spec = StepSpec(
        step_id="fit-1",
        node_type="cardre.decision_tree_classifier",
        node_version="1",
        category="fit",
        params={},
        params_hash="params-hash",
        parent_step_ids=[],
    )
    outputs = _Outputs()
    context = NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=step_spec,
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

    result = DecisionTreeNode().run(context)

    assert len(result.staged_artifacts) == 2
    assert outputs.estimator["kind"] is EvidenceKind.MODEL_ARTIFACT
    assert outputs.model["kind"] is EvidenceKind.MODEL_ARTIFACT
    assert outputs.model["payload"]["estimator_reference"]["artifact_id"] == "estimator-artifact"
    assert outputs.model["payload"]["estimator_reference"]["creating_run_id"] == "run-1"
    assert outputs.model["payload"]["estimator_reference"]["creating_run_step_id"] == "fit-1"
    assert result.metrics["feature_count"] == 1


def test_tuning_node_uses_node_context_staged_outputs():
    params = {
        "estimator_type": "decision_tree",
        "param_grid": {"max_depth": [1]},
        "cv_folds": 2,
        "random_seed": 42,
    }
    step_spec = StepSpec(
        step_id="tune-1",
        node_type="cardre.hyperparameter_tuning",
        node_version="1",
        category="fit",
        params=params,
        params_hash="params-hash",
        parent_step_ids=[],
    )
    outputs = _Outputs()
    context = NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=step_spec,
        inputs=_Inputs(),
        outputs=outputs,
        params=params,
        runtime=RuntimeMeta(
            run_id="run-1",
            plan_version_id="plan-1",
            step_id="tune-1",
            node_type="cardre.hyperparameter_tuning",
        ),
    )

    result = HyperparameterTuningNode().run(context)

    assert len(result.staged_artifacts) == 2
    assert outputs.estimator["kind"] is EvidenceKind.MODEL_ARTIFACT
    assert outputs.model["kind"] is EvidenceKind.MODEL_ARTIFACT
    assert outputs.model["payload"]["estimator_reference"]["artifact_id"] == "estimator-artifact"
    assert outputs.model["payload"]["estimator_reference"]["creating_run_step_id"] == "tune-1"
    assert result.metrics["best_score"] == 0.5
