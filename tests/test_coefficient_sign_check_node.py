from __future__ import annotations

import json

from cardre._evidence.schemas import (
    SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_WOE_IV_EVIDENCE,
)
from cardre.artifacts import write_json_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.diagnostics import CoefficientSignCheckNode


def test_coefficient_sign_check_flags_positive_woe_coefficients(store):
    model_artifact = write_json_artifact(
        store,
        artifact_type="model",
        role="model",
        stem="model-artifact",
        payload={
            "schema_version": SCHEMA_MODEL_ARTIFACT,
            "model_family": "logistic_regression",
            "target_column": "credit_risk_class",
            "feature_contract": {"features": ["age_woe", "income_woe"]},
            "model_payload": {
                "coefficients": {
                    "age_woe": -0.8,
                    "income_woe": 0.4,
                },
            },
            "training": {},
            "warnings": [],
        },
        metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
    )
    woe_evidence_artifact = write_json_artifact(
        store,
        artifact_type="report",
        role="report",
        stem="final-woe-evidence",
        payload={
            "schema_version": SCHEMA_WOE_IV_EVIDENCE,
            "target_column": "credit_risk_class",
            "variables": [
                {"variable_name": "age", "status": "included"},
                {"variable_name": "income", "status": "included"},
            ],
        },
        metadata={"schema_version": SCHEMA_WOE_IV_EVIDENCE, "purpose": "final"},
    )
    step_spec = StepSpec(
        step_id="coefficient-sign-check",
        node_type="cardre.coefficient_sign_check",
        node_version="1",
        category="fit",
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=[],
        position=0,
        canonical_step_id="coefficient-sign-check",
    )
    context = ExecutionContext(
        store=store,
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[model_artifact, woe_evidence_artifact],
        validated_params={},
        runtime_metadata={},
    )

    output = CoefficientSignCheckNode().run(context)

    assert len(output.artifacts) == 1
    artifact = output.artifacts[0]
    payload = json.loads((store.root / artifact.path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS
    assert payload["summary"]["checked_variable_count"] == 2
    assert payload["summary"]["warning_count"] == 1
    by_variable = {row["variable_name"]: row for row in payload["variables"]}
    assert by_variable["age"]["status"] == "pass"
    assert by_variable["income"]["status"] == "warning"
    assert by_variable["income"]["expected_sign"] == "negative"
