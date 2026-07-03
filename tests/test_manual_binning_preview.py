"""Tests for WOE/IV extraction from evidence — pure functions."""

from __future__ import annotations

import math

from cardre.services.manual_binning_service import (
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

SAMPLE_NO_GOOD = {
    "variable": "x",
    "kind": "numeric",
    "bins": [
        {
            "bin_id": "b1",
            "label": "Bin1",
            "good_count": 0,
            "bad_count": 100,
            "row_count": 100,
        },
    ],
}

SAMPLE_NO_BAD = {
    "variable": "x",
    "kind": "numeric",
    "bins": [
        {
            "bin_id": "b1",
            "label": "Bin1",
            "good_count": 100,
            "bad_count": 0,
            "row_count": 100,
        },
    ],
}


class TestExtractWoeByBin:
    """Tests for _extract_woe_by_bin equivalent."""

    def test_returns_correct_woe_values(self):
        result = extract_woe_by_bin(SAMPLE_VARIABLE)
        assert len(result) == 3

        # Low: good_pct=200/400=0.5, bad_pct=50/350≈0.142857
        # WOE = ln(0.142857/0.5) = ln(0.285714) ≈ -1.252763
        low = result[0]
        assert low["bin_id"] == "b1"
        assert low["label"] == "Low"
        assert low["good_count"] == 200
        assert low["bad_count"] == 50
        assert abs(low["good_pct"] - 0.5) < 1e-6
        assert abs(low["bad_pct"] - 50/350) < 1e-6
        expected_woe = math.log((50/350) / (200/400))
        assert abs(low["woe"] - expected_woe) < 1e-6

    def test_woe_sign_changes_with_risk(self):
        result = extract_woe_by_bin(SAMPLE_VARIABLE)
        # Low-risk bin (more goods than bads) should have negative WOE
        assert result[0]["woe"] < 0, "Low-risk bin should have negative WOE"
        # High-risk bin (more bads than goods) should have positive WOE
        assert result[2]["woe"] > 0, "High-risk bin should have positive WOE"

    def test_zero_good_returns_large_negative(self):
        result = extract_woe_by_bin(SAMPLE_NO_GOOD)
        assert result[0]["woe"] == -10.0, "No goods should give -10 WOE"

    def test_zero_bad_returns_large_positive(self):
        result = extract_woe_by_bin(SAMPLE_NO_BAD)
        assert result[0]["woe"] == 10.0, "No bads should give 10 WOE"

    def test_empty_bins(self):
        result = extract_woe_by_bin({"variable": "x", "bins": []})
        assert result == []

    def test_missing_count_fields_default_to_zero(self):
        data = {
            "variable": "x",
            "bins": [{"bin_id": "b1", "label": "X"}],
        }
        result = extract_woe_by_bin(data)
        assert len(result) == 1
        assert result[0]["good_count"] == 0
        assert result[0]["bad_count"] == 0


class TestExtractIv:
    """Tests for _extract_iv equivalent."""

    def test_returns_expected_iv(self):
        iv = extract_iv(SAMPLE_VARIABLE)
        # IV = sum (bad_pct - good_pct) * WOE
        assert iv > 0, "IV should be positive for predictive variable"
        # Expect roughly 0.8-1.2 for this distribution
        assert 0.5 < iv < 2.0

    def test_zero_good_returns_negative_iv(self):
        iv = extract_iv(SAMPLE_NO_GOOD)
        # With no goods, WOE = -10 per bin; IV = (1.0 - 0.0) * -10.0 = -10.0
        assert iv == -10.0

    def test_empty_bins_returns_zero(self):
        iv = extract_iv({"variable": "x", "bins": []})
        assert iv == 0.0


class TestExtractEventRateByBin:
    """Tests for _extract_event_rate_by_bin equivalent."""

    def test_returns_correct_event_rates(self):
        result = extract_event_rate_by_bin(SAMPLE_VARIABLE)
        assert len(result) == 3

        # Low: 50/250 = 0.2
        assert result[0]["bin_id"] == "b1"
        assert result[0]["event_rate"] == 50/250
        assert result[0]["event_count"] == 50
        assert result[0]["row_count"] == 250

        # High: 200/250 = 0.8
        assert abs(result[2]["event_rate"] - 0.8) < 1e-6

    def test_event_rate_increases_with_risk(self):
        result = extract_event_rate_by_bin(SAMPLE_VARIABLE)
        assert result[0]["event_rate"] < result[1]["event_rate"] < result[2]["event_rate"]

    def test_empty_bins(self):
        result = extract_event_rate_by_bin({"variable": "x", "bins": []})
        assert result == []

    def test_zero_row_count_returns_zero_rate(self):
        data = {
            "variable": "x",
            "bins": [{"bin_id": "b1", "label": "X", "row_count": 0, "bad_count": 0}],
        }
        result = extract_event_rate_by_bin(data)
        assert result[0]["event_rate"] == 0.0
