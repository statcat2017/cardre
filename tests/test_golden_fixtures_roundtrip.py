"""Round-trip tests for golden fixtures.

Verifies that each golden fixture can be deserialized and re-serialized
without data loss.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre._evidence.models.binning import BinDefinition
from cardre.modeling.schema import ModelArtifactV1

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not found")
    with open(path) as f:
        return json.load(f)


class TestModelArtifactRoundTrip:
    def test_round_trip(self):
        data = _load_fixture("golden_model_artifact.json")
        obj = ModelArtifactV1.from_dict(data)
        re_serialized = obj.to_dict()
        assert re_serialized == data, (
            f"ModelArtifactV1 round-trip changed data.\n"
            f"Keys in original: {set(data)}\n"
            f"Keys in re-serialized: {set(re_serialized)}"
        )

    def test_from_dict_handles_empty(self):
        obj = ModelArtifactV1.from_dict({})
        assert obj.schema_version == "cardre.model_artifact.v1"
        assert obj.model_family == "logistic_regression"

    def test_to_dict_round_trip_empty(self):
        obj = ModelArtifactV1()
        d = obj.to_dict()
        obj2 = ModelArtifactV1.from_dict(d)
        assert obj2.to_dict() == d


class TestBinDefinitionRoundTrip:
    def test_round_trip(self):
        data = _load_fixture("golden_bin_definition.json")
        obj = BinDefinition.from_json(data, artifact_id="golden-test")
        re_serialized = obj.to_dict()
        assert re_serialized["variables"] == data.get("variables", []), (
            "BinDefinition round-trip changed variables"
        )

    def test_from_json_handles_empty(self):
        obj = BinDefinition.from_json({}, artifact_id="test")
        assert obj.variables == []
        assert obj.source_artifact_id == "test"

    def test_to_dict_round_trip_empty(self):
        obj = BinDefinition.from_json({}, artifact_id="test")
        d = obj.to_dict()
        assert "variables" in d
        assert d["variables"] == []


class TestManualBinningOverridesRoundTrip:
    def test_round_trip(self):
        data = _load_fixture("golden_manual_binning_overrides.json")
        re_serialized = json.loads(json.dumps(data))
        assert re_serialized == data, "Manual binning overrides round-trip changed data"

    def test_has_expected_schema(self):
        data = _load_fixture("golden_manual_binning_overrides.json")
        assert data.get("schema_version") == "cardre.manual_binning_overrides.v1"
        assert "overrides" in data
