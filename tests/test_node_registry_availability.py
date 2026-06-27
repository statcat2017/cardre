"""Tests for NodeRegistry availability introspection (launch vs deferred,
optional-dependency importability)."""
from __future__ import annotations

import pytest

from cardre.registry import NodeRegistry


class TestAvailability:
    def test_launch_node_available_in_launch_mode(self) -> None:
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.logistic_regression")
        assert av.available is True
        assert av.tier == "launch"
        assert av.disabled_reason is None
        assert av.missing_optional_dependencies == []

    def test_deferred_node_unavailable_in_launch_mode(self) -> None:
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.gradient_boosting_classifier")
        assert av.available is False
        assert av.tier == "deferred"
        assert av.disabled_reason is not None
        assert "launch" in av.disabled_reason.lower()

    def test_deferred_node_available_when_launch_mode_off(self, monkeypatch) -> None:
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        reg = NodeRegistry.with_defaults()
        av = reg.availability("cardre.gradient_boosting_classifier")
        assert av.tier == "deferred"
        assert av.available is True
        assert av.disabled_reason is None

    def test_optional_dep_missing_marks_unavailable(self, monkeypatch) -> None:
        reg = NodeRegistry.with_defaults()
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep",
                            lambda group: group != "boosting")
        av = reg.availability("cardre.xgboost_classifier")
        assert av.available is False
        assert "boosting" in av.missing_optional_dependencies
        assert av.disabled_reason is not None
        assert "boosting" in av.disabled_reason.lower()

    def test_optional_dep_present_marks_available_when_not_deferred(self, monkeypatch) -> None:
        reg = NodeRegistry.with_defaults()
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda group: True)
        monkeypatch.setenv("CARDRE_LAUNCH_MODE", "0")
        av = reg.availability("cardre.xgboost_classifier")
        assert av.available is True
        assert av.missing_optional_dependencies == []

    def test_is_available_matches_availability(self) -> None:
        reg = NodeRegistry.with_defaults()
        assert reg.is_available("cardre.logistic_regression") is True
        assert reg.is_available("cardre.gradient_boosting_classifier") is False

    def test_availability_unknown_node_raises(self) -> None:
        reg = NodeRegistry.with_defaults()
        with pytest.raises(KeyError):
            reg.availability("cardre.does_not_exist")
