"""Section C & D: Oracle tests for Cardre's WOE/IV calculation and logistic regression.

These tests feed R golden data + R bin definitions through Cardre's
own calculation nodes and verify the outputs match the golden reference.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes import CalculateWoeIvNode, LogisticRegressionNode
from tests.golden_scorecard.helpers import (
    R_SELECTED_VARS_DOT,
    build_bin_def_from_r_bins,
    build_woe_data_from_r,
    r_woe_col,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

R_VAR_MAP = [
    ("status.of.existing.checking.account", "checking_account_status"),
    ("duration.in.month", "duration_months"),
    ("credit.history", "credit_history"),
    ("purpose", "purpose"),
    ("credit.amount", "credit_amount"),
    ("savings.account.and.bonds", "savings_account_bonds"),
    ("present.employment.since", "present_employment_since"),
    ("installment.rate.in.percentage.of.disposable.income", "installment_rate_percent_disposable_income"),
    ("other.debtors.or.guarantors", "other_debtors_guarantors"),
    ("property", "property"),
    ("age.in.years", "age_years"),
    ("other.installment.plans", "other_installment_plans"),
    ("housing", "housing"),
]


def _cardre_to_r_var(ca_var: str) -> str | None:
    for r_name, ca_name in R_VAR_MAP:
        if ca_name == ca_var:
            return r_name
    return None


# ---------------------------------------------------------------------------
# WOE/IV exact oracle
# ---------------------------------------------------------------------------


def _run_woe_iv_oracle(store, golden_csv, golden_json):
    """Feed R's filtered_data (full 1000 rows) + R's bin definitions through
    Cardre's CalculateWoeIvNode.

    R's woebin() computes WOE on the full dataset before splitting, so
    this oracle feeds all 1000 rows to match.  Bypasses import, split,
    and binning to test the calculation engine directly.
    """
    bin_def = build_bin_def_from_r_bins(golden_json["bins_adj"])

    # Use ALL filtered_data rows (1000) — R computes WOE on the full dataset
    full = golden_csv["filtered_data"].with_columns(
        pl.col("creditability").cast(pl.Utf8).alias("credit_risk_class"),
    ).drop("creditability")

    # Cast numeric columns from string to float (CSVs loaded with infer_schema_length=0).
    # Determine numeric columns from the bin definition.
    for v in bin_def["variables"]:
        ca_name = v["variable"]
        if v["kind"] == "numeric":
            r_name = next((r for r, ca in R_VAR_MAP if ca == ca_name), None)
            if r_name and r_name in full.columns:
                full = full.with_columns(pl.col(r_name).cast(pl.Float64))
            elif ca_name in full.columns:
                full = full.with_columns(pl.col(ca_name).cast(pl.Float64))

    # Rename columns to Cardre names
    for r_name, ca_name in R_VAR_MAP:
        if r_name in full.columns:
            full = full.rename({r_name: ca_name})

    train_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="oracle-train-raw", frame=full,
    )
    bin_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="oracle-bins", payload=bin_def,
    )
    meta = {
        "target_column": "credit_risk_class",
        "good_values": ["0"], "bad_values": ["1"],
        "indeterminate_values": [],
    }
    meta_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="oracle-meta", payload=meta,
    )

    params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
    spec = StepSpec(
        step_id="woe-iv-oracle", node_type="cardre.calculate_woe_iv",
        node_version="1", category="selection",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[train_art, bin_art, meta_art],
        validated_params=params, runtime_metadata={},
    )
    out = CalculateWoeIvNode().run(ctx)

    for art in out.artifacts:
        if art.artifact_type == "report":
            path = store.artifact_path(art)
            if path.suffix == ".parquet":
                df = pl.read_parquet(path)
                if "woe" in df.columns and "iv_component" in df.columns:
                    return df
    return None


class TestWOEIVOracle:
    """Exact oracle: Cardre's WOE/IV with R data + R bins."""

    def test_woe_table_is_produced(self, store, golden_csv, golden_json):
        woe_table = _run_woe_iv_oracle(store, golden_csv, golden_json)
        assert woe_table is not None, "No WOE table artifact — missing evidence is a FAILURE"

    def test_woe_values_match_r(self, store, golden_csv, golden_json):
        """Per-bin WOE magnitude matches R within 1e-6.

        Note: Cardre uses ``ln(good_dist/bad_dist)`` while R uses
        ``ln(bad_dist/good_dist)`` — opposite sign convention.
        Comparing Cardre value to negated R value.
        """
        woe_table = _run_woe_iv_oracle(store, golden_csv, golden_json)
        assert woe_table is not None, "No WOE table artifact produced"

        r_bins = golden_csv["bins_adj"]
        mismatches = []
        for row in woe_table.iter_rows(named=True):
            cardre_var = row["variable"]
            cardre_bin_id = row["bin_id"]
            cardre_woe = float(row["woe"])
            idx = int(cardre_bin_id.split("_rbin_")[-1])
            r_var = _cardre_to_r_var(cardre_var)
            if r_var is None:
                continue
            r_rows = r_bins.filter(pl.col("variable") == r_var)
            if idx >= len(r_rows):
                continue
            r_woe = float(r_rows.row(idx)[r_rows.columns.index("woe")])
            # Cardre: ln(good/bad); R: ln(bad/good) → compare Cardre ≈ -R
            if abs(cardre_woe - (-r_woe)) >= 1e-6:
                mismatches.append(
                    f"{cardre_var}[{idx}]: Cardre={cardre_woe:.8f} "
                    f"(-R)={-r_woe:.8f} R(raw)={r_woe:.8f}"
                )
        assert not mismatches, "WOE mismatches (Cardre vs -R):\n" + "\n".join(mismatches)

    def test_iv_components_match_r(self, store, golden_csv, golden_json):
        """Per-bin IV components match R within 1e-6 (IV is sign-invariant)."""
        woe_table = _run_woe_iv_oracle(store, golden_csv, golden_json)
        assert woe_table is not None, "No WOE table artifact produced"

        r_bins = golden_csv["bins_adj"]
        mismatches = []
        for row in woe_table.iter_rows(named=True):
            cardre_var = row["variable"]
            cardre_bin_id = row["bin_id"]
            cardre_iv = float(row["iv_component"])
            idx = int(cardre_bin_id.split("_rbin_")[-1])
            r_var = _cardre_to_r_var(cardre_var)
            if r_var is None:
                continue
            r_rows = r_bins.filter(pl.col("variable") == r_var)
            if idx >= len(r_rows):
                continue
            r_iv = float(r_rows.row(idx)[r_rows.columns.index("bin_iv")])
            if abs(cardre_iv - r_iv) >= 1e-6:
                mismatches.append(f"{cardre_var}[{idx}]: {cardre_iv:.8f} vs R {r_iv:.8f}")
        assert not mismatches, "IV mismatches:\n" + "\n".join(mismatches)

    def test_bin_counts_match_r(self, store, golden_csv, golden_json):
        """Per-bin row_count, good_count, bad_count match R within 1."""

        woe_table = _run_woe_iv_oracle(store, golden_csv, golden_json)
        assert woe_table is not None, "No WOE table artifact produced"

        r_bins = golden_csv["bins_adj"]
        mismatches = []
        for row in woe_table.iter_rows(named=True):
            cardre_var = row["variable"]
            cardre_bin_id = row["bin_id"]
            cardre_row_count = int(row["row_count"])
            cardre_good = int(row["good_count"])
            cardre_bad = int(row["bad_count"])
            idx = int(cardre_bin_id.split("_rbin_")[-1])
            r_var = _cardre_to_r_var(cardre_var)
            if r_var is None:
                continue
            r_rows = r_bins.filter(pl.col("variable") == r_var)
            if idx >= len(r_rows):
                continue
            r_row = r_rows.row(idx)
            ci = r_rows.columns
            r_row_count = int(r_row[ci.index("count")])
            r_good = int(r_row[ci.index("neg")])
            r_bad = int(r_row[ci.index("pos")])

            if (cardre_row_count, cardre_good, cardre_bad) != (r_row_count, r_good, r_bad):
                mismatches.append(
                    f"{cardre_var}[{idx}]: "
                    f"Cardre=({cardre_row_count},{cardre_good},{cardre_bad}) "
                    f"R=({r_row_count},{r_good},{r_bad})"
                )
        assert not mismatches, "Count mismatches:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# Logistic Regression oracle
# ---------------------------------------------------------------------------


def _run_lr_oracle(store, golden_csv):
    woe_df = build_woe_data_from_r(
        golden_csv["train_woe"],
        selected_vars=R_SELECTED_VARS_DOT,
    )
    train_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="golden-train-woe", frame=woe_df,
    )
    meta = {
        "target_column": "credit_risk_class",
        "good_values": ["0"], "bad_values": ["1"],
        "indeterminate_values": [],
    }
    meta_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-meta", payload=meta,
    )
    params = {"C": 1e10, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42}
    spec = StepSpec(
        step_id="lr-oracle", node_type="cardre.logistic_regression",
        node_version="1", category="fit",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[train_art, meta_art],
        validated_params=params, runtime_metadata={},
    )
    out = LogisticRegressionNode().run(ctx)
    return json.loads(store.artifact_path(out.artifacts[0]).read_text())


class TestLogisticRegressionOracle:
    """Oracle: Cardre LR on identical data ≈ R glm."""

    def test_coefficient_count(self, store, golden_csv):
        model = _run_lr_oracle(store, golden_csv)
        assert len(model["coefficients"]) == 10

    def test_intercept_matches_r(self, store, golden_csv):
        model = _run_lr_oracle(store, golden_csv)
        r_intercept = float(
            golden_csv["model_coefficients"]
            .filter(pl.col("term") == "(Intercept)").select("coefficient").item()
        )
        assert model["intercept"] == pytest.approx(r_intercept, rel=0.01)

    def test_coefficients_match_r(self, store, golden_csv):
        model = _run_lr_oracle(store, golden_csv)
        for row in golden_csv["model_coefficients"].iter_rows(named=True):
            r_term = row["term"]
            r_coef = float(row["coefficient"])
            if r_term == "(Intercept)":
                continue
            cardre_key = r_woe_col(r_term)
            assert cardre_key in model["coefficients"]
            diff = abs(model["coefficients"][cardre_key] - r_coef)
            threshold = max(0.01 * abs(r_coef), 0.002)
            assert diff < threshold, (
                f"{cardre_key}: Cardre={model['coefficients'][cardre_key]:.6f} "
                f"R={r_coef:.6f}"
            )

    def test_converged(self, store, golden_csv):
        model = _run_lr_oracle(store, golden_csv)
        assert model["training"]["converged"]
