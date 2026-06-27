"""Tests for OptionalDependencyNotInstalled and PlanContainsUnavailableNodesError."""
from __future__ import annotations

from cardre.errors import (
    OptionalDependencyNotInstalled,
    PlanContainsUnavailableNodesError,
)


class TestOptionalDependencyNotInstalled:
    def test_has_code_and_missing_groups(self) -> None:
        err = OptionalDependencyNotInstalled(
            node_type="cardre.xgboost_classifier",
            missing_groups=["boosting"],
        )
        assert err.code == "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
        assert err.status_code == 400
        assert "boosting" in err.message
        assert "cardre.xgboost_classifier" in err.message
        assert err.context["missing_groups"] == ["boosting"]

    def test_install_hint_in_message(self) -> None:
        err = OptionalDependencyNotInstalled(
            node_type="cardre.xgboost_classifier",
            missing_groups=["boosting", "explain"],
        )
        assert "boosting" in err.message
        assert "explain" in err.message


class TestPlanContainsUnavailableNodesError:
    def test_carries_step_issues(self) -> None:
        issues = [
            {"step_id": "gbdt", "node_type": "cardre.gradient_boosting_classifier",
             "disabled_reason": "Not available in launch mode."},
        ]
        err = PlanContainsUnavailableNodesError(issues=issues)
        assert err.code == "PLAN_CONTAINS_UNAVAILABLE_NODES"
        assert err.status_code == 400
        assert err.context["issues"] == issues
        assert "gbdt" in err.message
