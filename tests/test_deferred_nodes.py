"""Tests for deferred ML node tier enforcement.

Verifies that deferred nodes are registered, non-executable in launch mode,
and listed correctly.
"""

from __future__ import annotations

import pytest

from cardre.config import CardreConfig
from cardre.domain.errors import NodeNotAvailableForLaunch
from cardre.nodes.registry import NodeRegistry

pytestmark = pytest.mark.unit


class TestDeferredNodeTiers:
    """Verify deferred ML node tier behaviour in default (launch) mode."""

    def test_deferred_node_raises_on_instantiation(self) -> None:
        reg = NodeRegistry.with_defaults()
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.xgboost_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.random_forest_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.gradient_boosting_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.lightgbm_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.catboost_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.hyperparameter_tuning")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.model_explainability")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.fairness_report")
        with pytest.raises(NodeNotAvailableForLaunch):
            reg.instantiate("cardre.reject_inference_augmentation")

    def test_deferred_nodes_listed_in_deferred_list(self) -> None:
        reg = NodeRegistry.with_defaults()
        deferred = reg.list_deferred_nodes()
        assert "cardre.xgboost_classifier" in deferred
        assert "cardre.random_forest_classifier" in deferred
        assert "cardre.gradient_boosting_classifier" in deferred
        assert "cardre.lightgbm_classifier" in deferred
        assert "cardre.catboost_classifier" in deferred
        assert "cardre.hyperparameter_tuning" in deferred
        assert "cardre.model_explainability" in deferred
        assert "cardre.fairness_report" in deferred
        assert "cardre.reject_inference_augmentation" in deferred

    def test_deferred_nodes_have_correct_tier(self) -> None:
        reg = NodeRegistry.with_defaults()
        for node_type in reg.list_deferred_nodes():
            av = reg.availability(node_type)
            assert av.tier == "deferred", f"{node_type} should have tier='deferred' got {av.tier}"

    def test_launch_node_not_in_deferred_list(self) -> None:
        reg = NodeRegistry.with_defaults()
        deferred = reg.list_deferred_nodes()
        # Launch-tier nodes should not appear in deferred list
        assert "cardre.logistic_regression" not in deferred
        assert "cardre.import_dataset" not in deferred
        assert "cardre.fine_classing" not in deferred

    def test_deferred_nodes_not_available_in_launch_mode(self) -> None:
        reg = NodeRegistry.with_defaults()
        for node_type in reg.list_deferred_nodes():
            av = reg.availability(node_type)
            assert not av.available, f"Deferred node {node_type} should not be available in launch mode"
            assert av.tier == "deferred"

    def test_availability_returns_disabled_reason_for_deferred(self) -> None:
        reg = NodeRegistry.with_defaults()
        # Pick a deferred node with no optional deps to test tier gating
        deferred_no_deps = [
            nt for nt in reg.list_deferred_nodes()
            if not getattr(reg.resolve(nt), "optional_dependencies", None)
        ]
        if deferred_no_deps:
            av = reg.availability(deferred_no_deps[0])
            assert not av.available
            assert "Not available in launch mode" in (av.disabled_reason or "")

    def test_outside_launch_mode_deferred_available_if_no_optional_deps(self, monkeypatch) -> None:
        """Outside launch mode, deferred nodes with no optional deps are available."""
        monkeypatch.setattr(CardreConfig, "from_env", lambda: CardreConfig(launch_mode=False))
        reg = NodeRegistry.with_defaults()

        for node_type in reg.list_deferred_nodes():
            av = reg.availability(node_type)
            cls = reg.resolve(node_type)
            deps = getattr(cls, "optional_dependencies", None)
            if not deps:
                # With no optional deps and launch_mode=False, should be available
                assert av.available or "Optional dependency" in (av.disabled_reason or ""), (
                    f"{node_type} should be available outside launch mode"
                )
