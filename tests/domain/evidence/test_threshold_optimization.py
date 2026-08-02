"""Threshold optimization evidence model tests."""

from __future__ import annotations

import pytest

from cardre.domain.evidence.kinds import EvidenceParseError
from cardre.domain.evidence.models.threshold import ThresholdOptimization
from cardre.domain.evidence.schemas import SCHEMA_THRESHOLD_OPTIMIZATION


class TestThresholdOptimization:
    def test_round_trip(self):
        payload = {
            "schema_version": SCHEMA_THRESHOLD_OPTIMIZATION,
            "objective": "youden",
            "cost_fp": 1.0,
            "cost_fn": 10.0,
            "selected_threshold": 0.5,
            "roles": {
                "test": {
                    "threshold": 0.5,
                    "objective_value": 0.75,
                    "detail": {"recall": 0.8, "specificity": 0.7},
                },
            },
        }
        obj = ThresholdOptimization.from_json(payload, artifact_id="a1")
        assert obj.objective == "youden"
        assert obj.selected_threshold == 0.5
        assert obj.roles["test"]["threshold"] == 0.5
        assert obj.schema_version == SCHEMA_THRESHOLD_OPTIMIZATION

    def test_missing_roles_rejected(self):
        with pytest.raises(EvidenceParseError, match="roles"):
            ThresholdOptimization.from_json({
                "schema_version": SCHEMA_THRESHOLD_OPTIMIZATION,
                "objective": "youden",
                "selected_threshold": 0.5,
            })

    def test_missing_selected_threshold_rejected(self):
        with pytest.raises(EvidenceParseError, match="selected_threshold"):
            ThresholdOptimization.from_json({
                "schema_version": SCHEMA_THRESHOLD_OPTIMIZATION,
                "objective": "youden",
                "roles": {"test": {"threshold": 0.5}},
            })

    def test_wrong_schema_rejected(self):
        with pytest.raises(EvidenceParseError, match="Unexpected threshold"):
            ThresholdOptimization.from_json({
                "schema_version": "cardre.threshold_optimization.v9",
                "objective": "youden",
                "selected_threshold": 0.5,
                "roles": {"test": {}},
            })
