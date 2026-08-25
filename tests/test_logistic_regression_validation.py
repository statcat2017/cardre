from __future__ import annotations

import pytest

from cardre.nodes.build.models import LogisticRegressionNode


class TestLogisticRegressionNodeValidateParams:
    @pytest.fixture
    def node(self):
        return LogisticRegressionNode()

    def test_default_params(self, node):
        errors = node.validate_params({})
        assert errors == []

    def test_valid_params(self, node):
        errors = node.validate_params({"max_iter": 1000})
        assert errors == []

    def test_invalid_max_iter(self, node):
        errors = node.validate_params({"max_iter": 0})
        assert any("max_iter" in e for e in errors)

    def test_invalid_max_iter_type(self, node):
        errors = node.validate_params({"max_iter": "abc"})
        assert any("max_iter" in e for e in errors)


class TestScoreScalingValidateParams:
    @pytest.fixture
    def node(self):
        from cardre.nodes.build.models import ScoreScalingNode
        return ScoreScalingNode()

    def test_default_params(self, node):
        errors = node.validate_params({})
        assert errors == []

    def test_valid_params(self, node):
        errors = node.validate_params({"base_score": 600, "base_odds": "50:1", "points_to_double_odds": 20.0})
        assert errors == []

    def test_invalid_base_odds_string(self, node):
        errors = node.validate_params({"base_odds": "abc"})
        assert any("base_odds" in e for e in errors)

    def test_non_positive_base_odds(self, node):
        errors = node.validate_params({"base_odds": "0:1"})
        assert any("base_odds" in e for e in errors)

    def test_non_positive_pdo(self, node):
        errors = node.validate_params({"points_to_double_odds": -1})
        assert any("points_to_double_odds" in e for e in errors)

    def test_invalid_pdo_type(self, node):
        errors = node.validate_params({"points_to_double_odds": "abc"})
        assert any("points_to_double_odds" in e for e in errors)
