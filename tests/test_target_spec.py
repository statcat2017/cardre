"""Tests for TargetSpec — canonical target encoding and validation."""

from __future__ import annotations

import polars as pl
import pytest

from cardre.modeling.target import TargetSpec


def _make_df(values: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"target": values})


class TestTargetSpecFromMetadata:
    def test_none_meta_returns_none(self):
        assert TargetSpec.from_metadata(None) is None

    def test_missing_target_column_returns_none(self):
        meta = object()
        assert TargetSpec.from_metadata(meta) is None

    def test_basic_construction(self):
        class Meta:
            target_column = "target"
            good_values = ["good"]
            bad_values = ["bad"]
            indeterminate_values = []
        spec = TargetSpec.from_metadata(Meta())
        assert spec is not None
        assert spec.target_column == "target"
        assert spec.good_values == frozenset({"good"})
        assert spec.bad_values == frozenset({"bad"})


class TestTargetSpecValidateGoodBadOnly:
    def test_accepts_good_and_bad(self):
        spec = TargetSpec(target_column="target", good_values=frozenset({"good"}), bad_values=frozenset({"bad"}))
        spec.validate_good_bad_only(_make_df(["good", "bad", "good", "bad"]))

    def test_rejects_indeterminate(self):
        spec = TargetSpec(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            indeterminate_values=frozenset({"maybe"}),
        )
        with pytest.raises(ValueError, match="not declared as good or bad"):
            spec.validate_good_bad_only(_make_df(["good", "bad", "maybe"]))

    def test_rejects_unknown(self):
        spec = TargetSpec(target_column="target", good_values=frozenset({"good"}), bad_values=frozenset({"bad"}))
        with pytest.raises(ValueError, match="not declared as good or bad"):
            spec.validate_good_bad_only(_make_df(["good", "bad", "unknown"]))


class TestTargetSpecEncodeBinaryStrict:
    def test_bad_is_1_good_is_0(self):
        spec = TargetSpec(target_column="target", good_values=frozenset({"good"}), bad_values=frozenset({"bad"}))
        result = spec.encode_binary_strict(_make_df(["good", "bad", "good", "bad"]))
        assert result.to_list() == [0, 1, 0, 1]

    def test_rejects_indeterminate(self):
        spec = TargetSpec(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            indeterminate_values=frozenset({"maybe"}),
        )
        with pytest.raises(ValueError, match="not declared as good or bad"):
            spec.encode_binary_strict(_make_df(["good", "bad", "maybe"]))


class TestTargetSpecEncodeBinary:
    def test_bad_is_1_good_is_0(self):
        spec = TargetSpec(target_column="target", good_values=frozenset({"good"}), bad_values=frozenset({"bad"}))
        result = spec.encode_binary(_make_df(["good", "bad", "good"]))
        assert result.to_list() == [0, 1, 0]

    def test_indeterminate_encoded_as_0(self):
        """Indeterminate values are accepted and encoded as 0 (non-bad)."""
        spec = TargetSpec(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            indeterminate_values=frozenset({"maybe"}),
        )
        result = spec.encode_binary(_make_df(["good", "bad", "maybe"]))
        assert result.to_list() == [0, 1, 0]

    def test_rejects_unknown(self):
        spec = TargetSpec(
            target_column="target",
            good_values=frozenset({"good"}),
            bad_values=frozenset({"bad"}),
            all_known=frozenset({"good", "bad"}),
        )
        with pytest.raises(ValueError, match="not declared as good, bad, or indeterminate"):
            spec.encode_binary(_make_df(["good", "bad", "unknown"]))
