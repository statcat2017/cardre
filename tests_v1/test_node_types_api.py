"""Tests for /node-types availability fields in launch mode."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api]


class TestNodeTypesLaunchMode:
    def test_deferred_node_marked_unavailable(self, client):
        resp = client.get("/node-types")
        assert resp.status_code == 200
        data = resp.json()
        deferred = [n for n in data["node_types"] if n["tier"] == "deferred"]
        assert deferred, "expected at least one deferred node"
        for n in deferred:
            assert n["available"] is False
            assert n["disabled_reason"] is not None

    def test_deferred_node_without_optional_deps_has_launch_reason(self, client):
        resp = client.get("/node-types")
        data = resp.json()
        gbdt = next(n for n in data["node_types"]
                    if n["node_type"] == "cardre.gradient_boosting_classifier")
        assert gbdt["available"] is False
        assert gbdt["disabled_reason"] is not None
        assert "launch" in gbdt["disabled_reason"].lower()

    def test_launch_node_marked_available(self, client):
        resp = client.get("/node-types")
        data = resp.json()
        logistic = next(n for n in data["node_types"]
                        if n["node_type"] == "cardre.logistic_regression")
        assert logistic["available"] is True
        assert logistic["disabled_reason"] is None

    def test_available_only_filters_deferred(self, client):
        resp = client.get("/node-types?available_only=true")
        data = resp.json()
        for n in data["node_types"]:
            assert n["available"] is True, f"{n['node_type']} should have been filtered"

    def test_schema_endpoint_carries_availability(self, client):
        resp = client.get("/node-types/cardre.gradient_boosting_classifier/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["disabled_reason"] is not None

    def test_boosting_node_reports_missing_dep(self, client, monkeypatch):
        from cardre import registry as regmod
        monkeypatch.setattr(regmod, "_probe_optional_dep", lambda g: g != "xgboost")
        resp = client.get("/node-types")
        xgb = next(n for n in resp.json()["node_types"]
                   if n["node_type"] == "cardre.xgboost_classifier")
        assert "xgboost" in xgb["missing_optional_dependencies"]
