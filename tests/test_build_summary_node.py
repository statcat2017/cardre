from __future__ import annotations

import pytest

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.modeling.schema import ModelArtifactV1
from cardre.nodes.build.models import BuildSummaryReportNode, DummyFitNode, NoopNode


def _scorecard_payload() -> dict:
    return {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20.0,
        "factor": 28.85, "offset": 487.0, "score_direction": "higher_is_lower_risk",
        "intercept": -0.5, "base_points": 500.0, "attributes": [],
    }


def _model_artifact() -> ModelArtifactV1:
    return ModelArtifactV1.from_dict({
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": "credit_risk_class",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["age_woe"]},
        "model_payload": {"intercept": -0.5, "coefficients": {"age_woe": -1.0}},
        "training": {"row_count": 100},
        "warnings": [],
    })


class TestBuildSummaryReportNode:
    def test_missing_scorecard_raises(self, node_harness):
        with pytest.raises(ValueError, match="requires a scorecard artifact"):
            node_harness(BuildSummaryReportNode)

    def test_missing_model_raises(self, node_harness):
        from node_harness import FakeArtifact as _FakeArtifact

        with pytest.raises(ValueError, match="requires a model artifact"):
            node_harness(
                BuildSummaryReportNode,
                roles={"scorecard": [_FakeArtifact("scorecard")]},
                evidence={EvidenceKind.SCORE_SCALING: _scorecard_payload()},
            )


class TestNoopNode:
    def test_run_returns_empty(self, node_harness):
        out = node_harness(NoopNode)
        assert out.staged == []
        assert out.metrics == {}


class TestDummyFitNode:
    def test_run_with_valid_input(self, node_harness):
        import polars as pl

        out = node_harness(
            DummyFitNode,
            frames={"train": pl.DataFrame({"a": [1, 2], "b": [3, 4]})},
            params={"dummy_param": 42},
        )
        assert len(out.staged) == 1
        assert out.staged[0].role == "definition"
        assert out.metrics["row_count"] == 2
