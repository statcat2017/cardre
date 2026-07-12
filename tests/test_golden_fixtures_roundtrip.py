"""Round-trip tests for golden fixtures.

Verifies that each golden fixture can be deserialized and re-serialized
without data loss. Manual binning overrides are tested through the
production adapter parse path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre._evidence.adapters import get_adapter
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models.binning import BinDefinition, ManualBinningOverrides
from cardre.domain.artifacts import ArtifactRef
from cardre.engine.binning.definition import LifecycleBin, LifecycleBinDefinition, LifecycleVariable
from cardre.modeling.schema import ModelArtifactV1
from cardre.store.db import ProjectStore

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

    def test_typed_properties_match_raw_fixture(self):
        data = _load_fixture("golden_model_artifact.json")
        obj = ModelArtifactV1.from_dict(data)

        assert obj.coefficients_dict == data["model_payload"]["coefficients"]
        assert obj.intercept == data["model_payload"]["intercept"]
        assert obj.features == data["feature_contract"]["features"]
        assert obj.target_column == data["target_column"]
        assert obj.target_event_value == data["target_event_value"]
        assert obj.model_family == data["model_family"]
        assert obj.score_direction == data["score_direction"]

        raw_base_odds = data.get("base_odds")
        if raw_base_odds is not None:
            if isinstance(raw_base_odds, str) and ":" in raw_base_odds:
                parts = raw_base_odds.split(":", 1)
                expected = float(parts[0]) / float(parts[1])
            else:
                expected = float(raw_base_odds)
            assert obj.base_odds == expected
        else:
            assert obj.base_odds == 50.0

        assert obj.bad_class_label == str(data.get("bad_class_label", ""))
        assert obj.feature_strategy == str(data.get("feature_strategy", ""))

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
    def test_parse_through_adapter(self, tmp_path):
        """Parse fixture through the production adapter parse path."""
        data = _load_fixture("golden_manual_binning_overrides.json")

        store = ProjectStore(tmp_path / "test.cardre")
        store.initialize()

        fixture_path = tmp_path / "overrides.json"
        with open(fixture_path, "w") as f:
            json.dump(data, f)

        art = ArtifactRef(
            artifact_id="test-overrides",
            artifact_type="definition",
            role="definition",
            path=str(fixture_path),
            physical_hash="ph",
            logical_hash="lh",
            media_type="application/json",
            metadata={"schema_version": "cardre.manual_binning_overrides.v1"},
        )

        spec = get_adapter(EvidenceKind.MANUAL_BINNING_OVERRIDES)
        parsed = spec.parse(fixture_path, art, store)
        assert isinstance(parsed, ManualBinningOverrides), f"Expected ManualBinningOverrides, got {type(parsed)}"
        assert parsed.schema_version == data.get("schema_version", "")
        assert len(parsed.overrides) == len(data.get("overrides", []))
        for override, raw in zip(parsed.overrides, data.get("overrides", []), strict=False):
            assert override.variable == raw.get("variable", "")
            assert override.action == raw.get("action", "")

    def test_has_expected_schema(self):
        data = _load_fixture("golden_manual_binning_overrides.json")
        assert data.get("schema_version") == "cardre.manual_binning_overrides.v1"
        assert "overrides" in data

    def test_has_representative_overrides(self):
        data = _load_fixture("golden_manual_binning_overrides.json")
        overrides = data["overrides"]
        assert len(overrides) >= 3, "Fixture should have at least 3 representative overrides"

        actions = {o["action"] for o in overrides}
        assert "merge" in actions, "Fixture should include a merge override"
        assert "group" in actions, "Fixture should include a group override"
        assert "reject" in actions, "Fixture should include a reject override"

        for override in overrides:
            assert "variable" in override, "Each override must have a variable"
            assert "action" in override, "Each override must have an action"
            assert "reason" in override, "Each override must have a reason"

    def test_json_round_trip(self):
        data = _load_fixture("golden_manual_binning_overrides.json")
        re_serialized = json.loads(json.dumps(data))
        assert re_serialized == data, "Manual binning overrides round-trip changed data"


class TestApplyOverrides:
    def test_reject_variable_moves_to_rejected(self):
        var = LifecycleVariable(
            variable="age",
            kind="numeric",
            bins=[
                LifecycleBin(bin_id="b1", label="Low", lower=0, upper=30, row_count=100, good_count=60, bad_count=40),
                LifecycleBin(bin_id="b2", label="High", lower=30, upper=100, row_count=200, good_count=120, bad_count=80),
            ],
            active=True,
        )
        bin_def = LifecycleBinDefinition(
            variables=[var],
            rejected=[],
        )

        result = LifecycleBinDefinition.apply_overrides(
            bin_def,
            [{"variable": "age", "action": "reject_variable", "reason": "Test rejection", "source_bin_ids": []}],
        )

        assert len(result.variables) == 0, "Rejected variable should not be in active variables"
        assert len(result.rejected) == 1, "Rejected variable should appear in rejected list"
        assert result.rejected[0].variable == "age"
        assert result.rejected[0].active is False
        assert result.rejected[0].status == "excluded"
        assert result.rejected[0].failure_reason == "Test rejection"
