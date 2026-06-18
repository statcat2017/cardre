"""Section A & B: Golden fixture integrity and WOE-data helper verification."""

from __future__ import annotations

import polars as pl
import pytest

from tests.golden_scorecard.helpers import (
    R_BASE_POINTS,
    R_SELECTED_VARS_DOT,
    build_woe_data_from_r,
)


class TestFixtureIntegrity:
    """Sanity checks on the golden fixture files themselves."""

    def test_golden_row_count(self, golden_metadata):
        assert golden_metadata["dataset"]["original_rows"] == 1000

    def test_golden_target_distribution(self, golden_csv):
        df = golden_csv["filtered_data"]
        good = df.filter(pl.col("creditability") == "0").height
        bad = df.filter(pl.col("creditability") == "1").height
        assert good == 700, f"expected 700 good, got {good}"
        assert bad == 300, f"expected 300 bad, got {bad}"

    def test_golden_selected_variables(self, golden_csv):
        terms = golden_csv["selected_terms"]
        assert terms.shape[0] == 10, "R stepwise selected 10 variables"
        selected = set(terms["term"].to_list())
        for v in ("present.employment.since_woe", "other.debtors.or.guarantors_woe", "property_woe"):
            assert v not in selected, f"{v} should have been dropped by stepwise"

    def test_golden_scorecard_basepoints(self, golden_json):
        sc = golden_json["scorecard"]
        bp = [b for b in sc["basepoints"] if b["variable"] == "basepoints"][0]
        assert abs(bp["points"] - R_BASE_POINTS) < 0.5

    def test_golden_split_sizes(self, golden_metadata):
        meta = golden_metadata
        assert meta["split"]["train_rows"] == 620
        assert meta["split"]["test_rows"] == 380

    def test_golden_reference_package_version(self, golden_metadata):
        pkgs = golden_metadata["packages"]
        assert pkgs["scorecard"] == "0.4.6", (
            f"Expected scorecard v0.4.6, got {pkgs['scorecard']}"
        )


class TestWOEDataHelper:
    """Verify the ``build_woe_data_from_r`` helper."""

    def test_woe_data_columns(self, golden_csv):
        df = build_woe_data_from_r(golden_csv["train_woe"])
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        assert len(woe_cols) == 13, f"expected 13 woe cols, got {len(woe_cols)}"

    def test_woe_data_target_column(self, golden_csv):
        df = build_woe_data_from_r(golden_csv["train_woe"])
        assert "credit_risk_class" in df.columns
        assert df["credit_risk_class"].dtype == pl.Utf8
        assert set(df["credit_risk_class"].unique().to_list()) == {"0", "1"}

    def test_woe_data_selected_columns(self, golden_csv):
        df = build_woe_data_from_r(
            golden_csv["train_woe"],
            selected_vars=R_SELECTED_VARS_DOT,
        )
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        assert len(woe_cols) == 10
        for v in ("present_employment_since_woe", "other_debtors_guarantors_woe", "property_woe"):
            assert v not in woe_cols

    def test_woe_data_row_count(self, golden_csv):
        train = build_woe_data_from_r(golden_csv["train_woe"])
        test = build_woe_data_from_r(golden_csv["test_woe"])
        assert train.shape[0] == 620
        assert test.shape[0] == 380

    def test_bin_def_categorical_merged_cats(self, golden_json):
        """R's %,% delimiter is split into separate categories."""
        from tests.golden_scorecard.helpers import build_bin_def_from_r_bins
        bin_def = build_bin_def_from_r_bins(golden_json["bins_adj"])
        for v in bin_def["variables"]:
            if v["kind"] != "categorical":
                continue
            for b in v["bins"]:
                if b["categories"] is None:
                    continue
                # No entry should contain the raw %,% separator
                for cat in b["categories"]:
                    assert "%,%" not in cat, (
                        f"categories for {v['variable']} bin {b['bin_id']} "
                        f"contain un-split separator: {b['categories']}"
                    )
