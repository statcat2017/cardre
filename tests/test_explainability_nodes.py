from __future__ import annotations

from types import SimpleNamespace

from cardre.domain.step import StepSpec
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes._params import NodeParams
from cardre.nodes.contracts import NodeContext, NodeResult, RuntimeMeta
from cardre.nodes.explainability import ModelExplainabilityNode, ModelLimitationsNode


class _Inputs:
    def __init__(self, model):
        self.model = model
        self.model_artifact = SimpleNamespace(role="model", artifact_id="model-1")

    def require(self, role, node_type):
        if role != "model":
            raise ValueError(f"{node_type} requires a {role!r} artifact")
        return self.model_artifact

    def read(self, artifact, kind):
        return self.model

    def first(self, role):
        return None


class _Outputs:
    def __init__(self):
        self.payloads = []
        self.metrics = {}

    def publish_json(self, **kwargs):
        self.payloads.append(kwargs)
        return SimpleNamespace(artifact_id="report-1", logical_hash="report-hash")

    def add_metric(self, name, value):
        self.metrics[name] = value

    def build_result(self):
        return NodeResult(metrics=self.metrics)


def _context(node_type, inputs, outputs, params):
    step_spec = StepSpec(
        step_id="explain-1",
        node_type=node_type,
        node_version="1",
        category="report",
        params=NodeParams(params),
        params_hash="test",
        parent_step_ids=[],
        canonical_step_id="explain-1",
    )
    return NodeContext(
        run_id="run-1",
        plan_version_id="plan-1",
        step_spec=step_spec,
        inputs=inputs,
        outputs=outputs,
        params=NodeParams(params),
        runtime=RuntimeMeta(
            run_id="run-1",
            plan_version_id="plan-1",
            step_id="explain-1",
            node_type=node_type,
        ),
    )


def _model():
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "bad_flag",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"intercept": -0.4, "coefficients": {"age_woe": 0.8}},
        "training": {"row_count": 100},
        "interpretability": {"explanation_level": "native_scorecard"},
    })


def test_explainability_node_publishes_report_through_node_context():
    outputs = _Outputs()
    result = ModelExplainabilityNode().run(_context(
        "cardre.model_explainability",
        _Inputs(_model()),
        outputs,
        {},
    ))

    assert outputs.payloads[0]["kind"].value == "explainability_report"
    assert outputs.payloads[0]["payload"]["explanation_type"] == "coefficients"
    assert result.metrics == {"model_family": "logistic_regression"}


def test_limitations_node_publishes_report_through_node_context():
    outputs = _Outputs()
    result = ModelLimitationsNode().run(_context(
        "cardre.model_limitations",
        _Inputs(_model()),
        outputs,
        {"accepted_limitations": []},
    ))

    assert outputs.payloads[0]["kind"].value == "explainability_report"
    assert outputs.payloads[0]["payload"]["overall_status"] == "pass"
    assert result.metrics == {"overall_status": "pass"}
