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
        assert len(overrides) >= 2, "Fixture should have at least 2 representative overrides"

        actions = {o["action"] for o in overrides}
        assert "merge_bins" in actions, "Fixture should include a merge_bins override"
        assert "reject_variable" in actions, "Fixture should include a reject_variable override"

        for override in overrides:
            assert "variable" in override, "Each override must have a variable"
            assert "action" in override, "Each override must have an action"
            assert "reason" in override, "Each override must have a reason"
            assert "source_bin_ids" in override, "Each override must have source_bin_ids"

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

    def test_merge_bins_preserves_all_fields(self):
        var = LifecycleVariable(
            variable="age",
            kind="numeric",
            bins=[
                LifecycleBin(bin_id="b1", label="Low", lower=0, upper=30, kind="numeric", row_count=100, good_count=60, bad_count=40, bad_rate=0.4, row_pct=0.2222, woe=0.5, iv=0.1),
                LifecycleBin(bin_id="b2", label="Mid", lower=30, upper=60, kind="numeric", row_count=200, good_count=120, bad_count=80, bad_rate=0.4, row_pct=0.4444, woe=-0.3, iv=0.2),
                LifecycleBin(bin_id="b3", label="High", lower=60, upper=100, kind="numeric", row_count=150, good_count=90, bad_count=60, bad_rate=0.4, row_pct=0.3333, woe=0.1, iv=0.05),
            ],
            active=True,
        )
        bin_def = LifecycleBinDefinition(variables=[var], rejected=[])

        result = LifecycleBinDefinition.apply_overrides(
            bin_def,
            [{"variable": "age", "action": "merge_bins", "source_bin_ids": ["b1", "b2"], "new_label": "Low-Mid", "reason": "Merge sparse bins"}],
        )

        assert len(result.variables) == 1
        merged_bins = result.variables[0].bins
        assert len(merged_bins) == 2, "Should have 2 bins after merging 3 into 2"
        merged = merged_bins[0]
        assert merged.bin_id == "age_manual_low-mid"
        assert merged.label == "Low-Mid"
        assert merged.lower == 0
        assert merged.upper == 60
        assert merged.kind == "numeric"
        assert merged.row_count == 300
        assert merged.good_count == 180
        assert merged.bad_count == 120
        assert merged.bad_rate == 120 / 300
        assert merged.row_pct == pytest.approx(0.2222 + 0.4444, rel=1e-4)
        assert merged.woe is None
        assert merged.iv is None
        assert merged.is_missing_bin is False
        assert merged.categories is None

    def test_group_categories_preserves_all_fields(self):
        var = LifecycleVariable(
            variable="cat_var",
            kind="categorical",
            bins=[
                LifecycleBin(bin_id="c1", label="A", categories=["a"], kind="categorical", row_count=50, good_count=30, bad_count=20, bad_rate=0.4, row_pct=0.2273, woe=0.5, iv=0.1),
                LifecycleBin(bin_id="c2", label="B", categories=["b"], kind="categorical", row_count=70, good_count=40, bad_count=30, bad_rate=0.4286, row_pct=0.3182, woe=-0.3, iv=0.2),
                LifecycleBin(bin_id="c3", label="C", categories=["c"], kind="categorical", row_count=100, good_count=60, bad_count=40, bad_rate=0.4, row_pct=0.4545, woe=0.1, iv=0.05),
            ],
            active=True,
        )
        bin_def = LifecycleBinDefinition(variables=[var], rejected=[])

        result = LifecycleBinDefinition.apply_overrides(
            bin_def,
            [{"variable": "cat_var", "action": "group_categories", "source_bin_ids": ["c1", "c2"], "new_label": "A-B", "reason": "Group sparse categories"}],
        )

        assert len(result.variables) == 1
        grouped_bins = result.variables[0].bins
        assert len(grouped_bins) == 2, "Should have 2 bins after grouping 3 into 2"
        grouped = grouped_bins[0]
        assert grouped.bin_id == "cat_var_manual_grouped"
        assert grouped.label == "A-B"
        assert grouped.categories == ["a", "b"]
        assert grouped.kind == "categorical"
        assert grouped.row_count == 120
        assert grouped.good_count == 70
        assert grouped.bad_count == 50
        assert grouped.bad_rate == 50 / 120
        assert grouped.row_pct == pytest.approx(0.2273 + 0.3182, rel=1e-4)
        assert grouped.woe is None
        assert grouped.iv is None
        assert grouped.is_missing_bin is False
        assert grouped.lower is None
        assert grouped.upper is None
        assert grouped.row_count == 120
        assert grouped.good_count == 70
        assert grouped.bad_count == 50
        assert grouped.is_missing_bin is False
        assert grouped.lower is None
        assert grouped.upper is None


class TestApplyOverridesGoldenFixture:
    """Golden fixture regression tests for apply_overrides round-trip losslessness."""

    def test_golden_bin_def_round_trips_through_apply_overrides(self):
        data = _load_fixture("golden_bin_definition.json")
        overrides = _load_fixture("golden_manual_binning_overrides.json")["overrides"]

        bin_def = LifecycleBinDefinition.from_payload(data)
        result = LifecycleBinDefinition.apply_overrides(bin_def, overrides)

        re_serialized = result.to_payload()
        round_tripped = LifecycleBinDefinition.from_payload(re_serialized)

        assert round_tripped.schema_version == result.schema_version
        assert len(round_tripped.variables) == len(result.variables)
        assert len(round_tripped.rejected) == len(result.rejected)
        assert len(round_tripped.warnings) == len(result.warnings)

        for var, rvar in zip(result.variables, round_tripped.variables, strict=True):
            assert var.variable == rvar.variable
            assert var.kind == rvar.kind
            assert len(var.bins) == len(rvar.bins)
            for b, rb in zip(var.bins, rvar.bins, strict=True):
                assert b.bin_id == rb.bin_id
                assert b.label == rb.label
                assert b.lower == rb.lower
                assert b.upper == rb.upper
                assert b.lower_inclusive == rb.lower_inclusive
                assert b.upper_inclusive == rb.upper_inclusive
                assert b.categories == rb.categories
                assert b.is_missing_bin == rb.is_missing_bin
                assert b.is_special_bin == rb.is_special_bin
                assert b.is_other_bin == rb.is_other_bin
                assert b.row_count == rb.row_count
                assert b.good_count == rb.good_count
                assert b.bad_count == rb.bad_count
                assert b.bad_rate == rb.bad_rate
                assert b.woe == rb.woe
                assert b.iv == rb.iv
                assert b.row_pct == rb.row_pct
                assert b.kind == rb.kind
                assert b.special_values == rb.special_values
                assert b.extra == rb.extra

    def test_merged_bins_preserve_previously_dropped_metrics(self):
        data = _load_fixture("golden_bin_definition.json")
        overrides = _load_fixture("golden_manual_binning_overrides.json")["overrides"]

        bin_def = LifecycleBinDefinition.from_payload(data)
        result = LifecycleBinDefinition.apply_overrides(bin_def, overrides)

        credit_amount_var = next(v for v in result.variables if v.variable == "credit_amount")
        merged = [b for b in credit_amount_var.bins if b.bin_id == "credit_amount_manual_low_credit"]
        assert len(merged) == 1, "Expected exactly one merged bin for credit_amount"
        merged = merged[0]

        assert merged.label == "Low Credit"
        assert merged.lower is None
        assert merged.upper == 1525.0
        assert merged.lower_inclusive is False
        assert merged.upper_inclusive is True
        assert merged.categories is None
        assert merged.is_missing_bin is False
        assert merged.row_count == 4
        assert merged.good_count == 3
        assert merged.bad_count == 1
        assert merged.bad_rate == 0.25
        assert merged.row_pct is None
        assert merged.woe is None
        assert merged.iv is None
        assert merged.kind == ""
        assert merged.is_special_bin is False
        assert merged.is_other_bin is False
        assert merged.special_values is None

    def test_apply_overrides_with_no_overrides_round_trips_stably(self):
        data = _load_fixture("golden_bin_definition.json")
        bin_def = LifecycleBinDefinition.from_payload(data)
        result = LifecycleBinDefinition.apply_overrides(bin_def, [])

        assert len(result.warnings) == len(bin_def.warnings) + 1
        assert result.warnings[-1]["message"] == (
            "No manual overrides applied; passing through auto bins for selected variables"
        )

        re_serialized = result.to_payload()
        round_tripped = LifecycleBinDefinition.from_payload(re_serialized)

        assert round_tripped.schema_version == result.schema_version
        assert len(round_tripped.variables) == len(result.variables)
        for var, rvar in zip(result.variables, round_tripped.variables, strict=True):
            assert var.variable == rvar.variable
            for b, rb in zip(var.bins, rvar.bins, strict=True):
                assert b.bin_id == rb.bin_id
                assert b.bad_rate == rb.bad_rate
                assert b.woe == rb.woe
                assert b.iv == rb.iv
                assert b.row_pct == rb.row_pct
                assert b.kind == rb.kind
