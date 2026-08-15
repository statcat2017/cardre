from __future__ import annotations

from cardre._evidence.models.woe import WoeIvEvidence, WoeIvVariable
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build.diagnostics import CoefficientSignCheckNode


def _model_artifact() -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "credit_risk_class",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe", "income_woe"]},
        "model_payload": {
            "intercept": 0.0,
            "coefficients": {
                "age_woe": -0.8,
                "income_woe": 0.4,
            },
        },
        "training": {"row_count": 100},
        "warnings": [],
    })


def _woe_evidence() -> WoeIvEvidence:
    return WoeIvEvidence(
        variables=[
            WoeIvVariable(variable_name="age", status="included"),
            WoeIvVariable(variable_name="income", status="included"),
        ],
    )


def test_coefficient_sign_check_flags_positive_woe_coefficients(node_harness):
    from node_harness import FakeArtifact as _FakeArtifact

    out = node_harness(
        CoefficientSignCheckNode,
        roles={
            "report": [
                _FakeArtifact(
                    "report",
                    metadata={"schema_version": "cardre.woe_iv_evidence.v1", "purpose": "final"},
                ),
            ],
        },
        evidence={
            EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
            EvidenceKind.WOE_IV_EVIDENCE: _woe_evidence(),
        },
    )

    assert len(out.staged) == 1
    payload = out.staged[0].payload
    assert payload["schema_version"] == "cardre.coefficient_sign_diagnostics.v1"
    assert payload["summary"]["checked_variable_count"] == 2
    assert payload["summary"]["warning_count"] == 1
    by_variable = {row["variable_name"]: row for row in payload["variables"]}
    assert by_variable["age"]["status"] == "pass"
    assert by_variable["income"]["status"] == "warning"
    assert by_variable["income"]["expected_sign"] == "negative"
