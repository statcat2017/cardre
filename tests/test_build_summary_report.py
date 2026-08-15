"""Characterization tests for BuildSummaryReportNode — verifies the report
schema and model/scorecard summary extraction behavior.

Runs ScoreScalingNode then BuildSummaryReportNode through the node harness.
"""
from __future__ import annotations

import pytest

from cardre._evidence.models.binning import BinDefinition, BinVariable
from cardre._evidence.models.model import ScoreScaling
from cardre._evidence.models.woe import WoeTable
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build.models import BuildSummaryReportNode, ScoreScalingNode


def _model_artifact() -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "default_flag",
        "source_variables": ["age", "income"],
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "feature_contract": {
            "features": ["age_woe", "income_woe"],
            "transformation_strategy": "woe",
            "order_hash": "abc",
            "missing_policy": "error",
            "unknown_category_policy": "error",
        },
        "feature_order_hash": "abc",
        "model_payload": {
            "intercept": -0.5,
            "coefficients": {"age_woe": 1.2, "income_woe": -0.8},
        },
        "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {"C": 1.0}},
        "warnings": [],
    })


def _bin_definition() -> BinDefinition:
    return BinDefinition(
        source_artifact_id="bin-def-art",
        variables=[
            BinVariable(
                variable="age", dtype="numeric", kind="fine",
                bins=[
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30},
                    {"bin_id": "b2", "label": "31-50", "lower": 31, "upper": 50},
                ],
            ),
            BinVariable(
                variable="income", dtype="numeric", kind="fine",
                bins=[{"bin_id": "b3", "label": "Low", "lower": 0, "upper": 30000}],
            ),
        ],
    )


def _woe_table() -> WoeTable:
    return WoeTable(
        mapping={"age": {"b1": 0.5, "b2": -0.3}, "income": {"b3": 0.2}},
        columns=["variable", "bin_id", "woe"],
    )


_SCALING_PARAMS = {
    "base_score": 600,
    "base_odds": "50:1",
    "points_to_double_odds": 20.0,
    "higher_score_is_lower_risk": True,
}


class TestBuildSummaryReportNode:
    def test_happy_path_produces_report(self, node_harness):
        """Run ScoreScalingNode then BuildSummaryReportNode and verify the report payload."""
        sc_out = node_harness(
            ScoreScalingNode,
            roles={"model": ["model-art"]},
            evidence={
                EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
                EvidenceKind.BIN_DEFINITION: _bin_definition(),
                EvidenceKind.WOE_TABLE: _woe_table(),
            },
            params=_SCALING_PARAMS,
        )
        assert len(sc_out.staged) == 1
        scorecard_payload = sc_out.staged[0].payload

        report_out = node_harness(
            BuildSummaryReportNode,
            roles={
                "scorecard": [type("A", (), {"role": "scorecard", "metadata": {}})()],
                "model": ["model-art"],
            },
            evidence={
                EvidenceKind.SCORE_SCALING: ScoreScaling.from_json(scorecard_payload),
                EvidenceKind.MODEL_ARTIFACT: _model_artifact(),
            },
        )
        assert len(report_out.staged) == 1
        report = report_out.staged[0].payload

        assert "model_summary" in report
        assert "scorecard_summary" in report
        assert "woe_iv_references" in report
        assert "warnings" in report

        model_summary = report["model_summary"]
        assert model_summary["target_column"] == "default_flag"
        assert model_summary["features"] == ["age_woe", "income_woe"]
        assert model_summary["intercept"] == -0.5
        assert model_summary["coefficient_count"] == 2
        assert model_summary["converged"] is True
        assert model_summary["row_count"] == 100

        sc_summary = report["scorecard_summary"]
        assert sc_summary["base_score"] == 600
        assert sc_summary["base_odds"] == 50.0
        assert sc_summary["points_to_double_odds"] == 20.0
        assert sc_summary["attribute_count"] == 3  # age b1, age b2, income b3

        assert isinstance(report["woe_iv_references"], list)

    def test_missing_scorecard_raises(self, node_harness):
        with pytest.raises(ValueError, match="requires a scorecard artifact"):
            node_harness(BuildSummaryReportNode)

    def test_missing_model_raises(self, node_harness):
        from node_harness import FakeArtifact as _FakeArtifact

        with pytest.raises(ValueError, match="requires a model artifact"):
            node_harness(
                BuildSummaryReportNode,
                roles={"scorecard": [_FakeArtifact("scorecard")]},
                evidence={EvidenceKind.SCORE_SCALING: {
                    "schema_version": "cardre.score_scaling.v1",
                    "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20.0,
                    "factor": 28.85, "offset": 487.0, "score_direction": "higher_is_lower_risk",
                    "intercept": -0.5, "base_points": 500.0, "attributes": [],
                }},
            )
