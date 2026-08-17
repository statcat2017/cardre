from __future__ import annotations

from node_harness import FakeArtifact, FakeInputCollection, FakeOutputPublisher, make_context

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.explainability import ModelExplainabilityNode, ModelLimitationsNode


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


def _run(node, params):
    model = _model()
    model_art = FakeArtifact(role="model", artifact_id="model-1")
    inputs = FakeInputCollection(
        roles={"model": [model_art]},
        evidence={EvidenceKind.MODEL_ARTIFACT: model},
    )
    outputs = FakeOutputPublisher()
    context = make_context(
        inputs, outputs, params, node_type=node.node_type, step_id="explain-1",
    )
    result = node.run(context)
    return outputs, result


def test_explainability_node_publishes_report_through_node_context():
    node = ModelExplainabilityNode()
    outputs, result = _run(node, {})
    report = outputs.by_kind(EvidenceKind.EXPLAINABILITY_REPORT)[0]
    assert report.payload["explanation_type"] == "coefficients"
    assert result.metrics == {"model_family": "logistic_regression"}


def test_limitations_node_publishes_report_through_node_context():
    node = ModelLimitationsNode()
    outputs, result = _run(node, {"accepted_limitations": []})
    report = outputs.by_kind(EvidenceKind.EXPLAINABILITY_REPORT)[0]
    assert report.payload["overall_status"] == "pass"
    assert result.metrics == {"overall_status": "pass"}
