"""Tests for manual-binning preview pure functions — WOE/IV/event-rate extraction.

Ported from tests/test_manual_binning_preview.py to cover the pure functions
now in cardre/application/plans/manual_binning_preview.py.
"""

from __future__ import annotations

import math

from cardre.application.plans.manual_binning_preview import (
    extract_event_rate_by_bin,
    extract_iv,
    extract_woe_by_bin,
)

SAMPLE_VARIABLE = {
    "variable": "income",
    "kind": "numeric",
    "bins": [
        {
            "bin_id": "b1",
            "label": "Low",
            "good_count": 200,
            "bad_count": 50,
            "row_count": 250,
        },
        {
            "bin_id": "b2",
            "label": "Medium",
            "good_count": 150,
            "bad_count": 100,
            "row_count": 250,
        },
        {
            "bin_id": "b3",
            "label": "High",
            "good_count": 50,
            "bad_count": 200,
            "row_count": 250,
        },
    ],
}


class TestExtractWoeByBin:
    def test_returns_one_entry_per_bin(self):
        result = extract_woe_by_bin(SAMPLE_VARIABLE)
        assert len(result) == 3
        assert [b["bin_id"] for b in result] == ["b1", "b2", "b3"]

    def test_low_bad_bin_has_negative_woe(self):
        result = extract_woe_by_bin(SAMPLE_VARIABLE)
        assert result[0]["woe"] < 0

    def test_high_bad_bin_has_positive_woe(self):
        result = extract_woe_by_bin(SAMPLE_VARIABLE)
        assert result[2]["woe"] > 0

    def test_empty_bins_returns_empty(self):
        assert extract_woe_by_bin({"bins": []}) == []

    def test_zero_good_count_uses_floor_woe(self):
        var = {"bins": [{"bin_id": "b", "label": "L", "good_count": 0, "bad_count": 10, "row_count": 10}]}
        result = extract_woe_by_bin(var)
        assert result[0]["woe"] == -10.0

    def test_zero_bad_count_uses_ceiling_woe(self):
        var = {"bins": [{"bin_id": "b", "label": "L", "good_count": 10, "bad_count": 0, "row_count": 10}]}
        result = extract_woe_by_bin(var)
        assert result[0]["woe"] == 10.0


class TestExtractIv:
    def test_returns_float(self):
        iv = extract_iv(SAMPLE_VARIABLE)
        assert isinstance(iv, float)
        assert iv > 0

    def test_empty_bins_returns_zero(self):
        assert extract_iv({"bins": []}) == 0.0


class TestExtractEventRateByBin:
    def test_returns_event_rate_per_bin(self):
        result = extract_event_rate_by_bin(SAMPLE_VARIABLE)
        assert len(result) == 3
        assert result[0]["event_rate"] == 50 / 250
        assert result[2]["event_rate"] == 200 / 250

    def test_empty_bins_returns_empty(self):
        assert extract_event_rate_by_bin({"bins": []}) == []

    def test_zero_row_count_event_rate_zero(self):
        var = {"bins": [{"bin_id": "b", "label": "L", "row_count": 0, "bad_count": 0}]}
        result = extract_event_rate_by_bin(var)
        assert result[0]["event_rate"] == 0.0