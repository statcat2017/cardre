"""Tests for launch-mode feature gating: node tiers & governance."""
from __future__ import annotations

import os

import pytest

from cardre.errors import NodeNotAvailableForLaunch
from cardre.registry import NodeRegistry


def _cardre_data_dir() -> str:
    return os.environ.get("CARDRE_DATA_DIR", "/tmp")


class TestNodeTiers:
    """Verify launch/deferred node tier behaviour in default (launch) mode."""

    def test_launch_node_instantiates(self) -> None:
        reg = NodeRegistry.with_defaults()
        node = reg.instantiate("cardre.logistic_regression")
        assert node is not None

    def test_deferred_node_raises_on_instantiation(self) -> None:
        reg = NodeRegistry.with_defaults()
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.gradient_boosting_classifier")

    def test_deferred_node_listed_in_deferred_list(self) -> None:
        reg = NodeRegistry.with_defaults()
        deferred = reg.list_deferred_nodes()
        assert "cardre.gradient_boosting_classifier" in deferred
        assert "cardre.random_forest_classifier" in deferred

    def test_launch_node_not_in_deferred_list(self) -> None:
        reg = NodeRegistry.with_defaults()
        deferred = reg.list_deferred_nodes()
        assert "cardre.logistic_regression" not in deferred
        assert "cardre.decision_tree_classifier" not in deferred

    def test_launch_mode_disabled_allows_deferred_instantiation(self, monkeypatch) -> None:
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        # Re-create registry after env change
        reg = NodeRegistry()
        from cardre.nodes import GradientBoostingClassifierNode
        reg.register(GradientBoostingClassifierNode)
        node = reg.instantiate("cardre.gradient_boosting_classifier")
        assert node is not None
