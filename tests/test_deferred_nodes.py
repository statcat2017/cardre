from __future__ import annotations

import pytest

from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.errors import NodeNotAvailableForLaunch

pytestmark = pytest.mark.unit


def _cat(launch_mode: bool = True):
    return build_default_catalogue(Settings(launch_mode=launch_mode))


class TestDeferredNodeTiers:
    def test_deferred_node_raises_on_instantiation(self) -> None:
        cat = _cat()
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.xgboost_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.random_forest_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.gradient_boosting_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.lightgbm_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.catboost_classifier")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.hyperparameter_tuning")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.model_explainability")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.fairness_report")
        with pytest.raises(NodeNotAvailableForLaunch):
            cat.instantiate("cardre.reject_inference_augmentation")

    def test_deferred_nodes_listed_in_deferred_list(self) -> None:
        cat = _cat()
        deferred = cat.list_deferred_types()
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
        cat = _cat()
        for node_type in cat.list_deferred_types():
            av = cat.availability(node_type)
            assert av.tier == "deferred", f"{node_type} should have tier='deferred' got {av.tier}"

    def test_launch_node_not_in_deferred_list(self) -> None:
        cat = _cat()
        deferred = cat.list_deferred_types()
        assert "cardre.logistic_regression" not in deferred
        assert "cardre.import_dataset" not in deferred
        assert "cardre.automatic_binning" not in deferred

    def test_deferred_nodes_not_available_in_launch_mode(self) -> None:
        cat = _cat()
        for node_type in cat.list_deferred_types():
            av = cat.availability(node_type)
            assert not av.available, f"Deferred node {node_type} should not be available in launch mode"
            assert av.tier == "deferred"

    def test_availability_returns_disabled_reason_for_deferred(self) -> None:
        cat = _cat()
        deferred_no_deps = [
            nt for nt in cat.list_deferred_types()
            if not getattr(cat.resolve(nt), "optional_dependencies", None)
        ]
        if deferred_no_deps:
            av = cat.availability(deferred_no_deps[0])
            assert not av.available
            assert "Not available in launch mode" in (av.disabled_reason or "")

    def test_outside_launch_mode_deferred_available_if_no_optional_deps(self) -> None:
        cat = _cat(launch_mode=False)
        for node_type in cat.list_deferred_types():
            av = cat.availability(node_type)
            cls = cat.resolve(node_type)
            deps = getattr(cls, "optional_dependencies", None)
            if not deps:
                assert av.available or "Optional dependency" in (av.disabled_reason or ""), (
                    f"{node_type} should be available outside launch mode"
                )
