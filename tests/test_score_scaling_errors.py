from __future__ import annotations

import pytest

from cardre._evidence.models.binning import BinDefinition, BinVariable
from cardre._evidence.models.woe import WoeTable
from cardre.domain.evidence.kinds import EvidenceKind, EvidenceNotFoundError
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build.models import ScoreScalingNode


def _model_artifact() -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "default_flag",
        "source_variables": ["age"],
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"], "transformation_strategy": "woe",
                             "order_hash": "abc", "missing_policy": "error",
                             "unknown_category_policy": "error"},
        "feature_order_hash": "abc",
        "model_payload": {"intercept": -0.5, "coefficients": {"age_woe": 1.2}},
        "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {}},
        "warnings": [],
    })


def _bin_definition(*, empty: bool = False) -> BinDefinition:
    variables = []
    if not empty:
        variables = [
            BinVariable(
                variable="age", dtype="numeric", kind="fine",
                bins=[{"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30}],
            ),
        ]
    return BinDefinition(source_artifact_id="bin-def-art", variables=variables)


def _woe_table() -> WoeTable:
    return WoeTable(
        mapping={"age": {"b1": 0.5}},
        columns=["variable", "bin_id", "woe"],
    )


_SCALING_PARAMS = {
    "base_score": 600,
    "base_odds": "50:1",
    "points_to_double_odds": 20.0,
    "higher_score_is_lower_risk": True,
}


class TestScoreScalingRunErrors:
    def test_missing_model_artifact_raises(self, node_harness):
        with pytest.raises((EvidenceNotFoundError, ValueError)):
            node_harness(
                ScoreScalingNode,
                evidence={
                    EvidenceKind.BIN_DEFINITION: _bin_definition(),
                    EvidenceKind.WOE_TABLE: _woe_table(),
                },
                params=_SCALING_PARAMS,
            )

    def test_empty_bin_def_raises(self, node_harness):
        with pytest.raises(ValueError, match="empty bin definition"):
            node_harness(
                ScoreScalingNode,
                roles={"model": ["model-art"]},
                evidence={
                    EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
                    EvidenceKind.BIN_DEFINITION: _bin_definition(empty=True),
                    EvidenceKind.WOE_TABLE: _woe_table(),
                },
                params=_SCALING_PARAMS,
            )

    def test_diverging_score_direction(self, node_harness):
        out = node_harness(
            ScoreScalingNode,
            roles={"model": ["model-art"]},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
                EvidenceKind.BIN_DEFINITION: _bin_definition(),
                EvidenceKind.WOE_TABLE: _woe_table(),
            },
            params={**_SCALING_PARAMS, "higher_score_is_lower_risk": False},
        )
        assert len(out.staged) == 1
        payload = out.staged[0].payload
        assert payload["score_direction"] == "higher_is_better"
        assert payload["base_points"] < 600
