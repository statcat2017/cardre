"""Helpers for golden comparison tests against R scorecard reference fixtures.

All fixture-loading, column-mapping, and R→Cardre conversion logic
lives here so it is importable across the split test modules without
polluting the top-level ``tests/conftest.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GOLDEN_DIR = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "reference_scorecard_r_german_credit"
)


# ---------------------------------------------------------------------------
# Fixture-loading helpers
# ---------------------------------------------------------------------------


def load_golden_csvs() -> dict[str, pl.DataFrame]:
    """Load all CSV golden fixture files into Polars DataFrames."""
    result: dict[str, pl.DataFrame] = {}
    for csv_path in sorted(GOLDEN_DIR.glob("*.csv")):
        result[csv_path.stem] = pl.read_csv(
            csv_path,
            infer_schema_length=0,
            null_values=["", "NA"],
            truncate_ragged_lines=True,
        )
    return result


def load_golden_jsons() -> dict[str, object]:
    """Load all JSON golden fixture files."""
    result: dict[str, object] = {}
    for json_path in sorted(GOLDEN_DIR.glob("*.json")):
        result[json_path.stem] = json.loads(json_path.read_text())
    return result


def load_golden_metadata() -> dict:
    """Load just the metadata JSON."""
    return json.loads((GOLDEN_DIR / "metadata.json").read_text())


# ---------------------------------------------------------------------------
# R → Cardre column name mapping
# ---------------------------------------------------------------------------

R_TO_CARDRE: dict[str, str] = {
    "status.of.existing.checking.account": "checking_account_status",
    "duration.in.month": "duration_months",
    "credit.history": "credit_history",
    "purpose": "purpose",
    "credit.amount": "credit_amount",
    "savings.account.and.bonds": "savings_account_bonds",
    "present.employment.since": "present_employment_since",
    "installment.rate.in.percentage.of.disposable.income": "installment_rate_percent_disposable_income",
    "other.debtors.or.guarantors": "other_debtors_guarantors",
    "property": "property",
    "age.in.years": "age_years",
    "other.installment.plans": "other_installment_plans",
    "housing": "housing",
    "creditability": "credit_risk_class",
}

CARDRE_TO_R: dict[str, str] = {v: k for k, v in R_TO_CARDRE.items()}

R_FILTERED_COLUMNS: list[str] = [
    "status.of.existing.checking.account",
    "duration.in.month",
    "credit.history",
    "purpose",
    "credit.amount",
    "savings.account.and.bonds",
    "present.employment.since",
    "installment.rate.in.percentage.of.disposable.income",
    "other.debtors.or.guarantors",
    "property",
    "age.in.years",
    "other.installment.plans",
    "housing",
]

R_SELECTED_VARS_DOT: list[str] = [
    "status.of.existing.checking.account",
    "duration.in.month",
    "credit.history",
    "purpose",
    "credit.amount",
    "savings.account.and.bonds",
    "installment.rate.in.percentage.of.disposable.income",
    "age.in.years",
    "other.installment.plans",
    "housing",
]

R_DROPPED_VARS_DOT: list[str] = [
    "present.employment.since",
    "other.debtors.or.guarantors",
    "property",
]

CARDRE_EXCLUDE: list[str] = [
    "personal_status_sex",
    "present_residence_since",
    "existing_credits_at_bank",
    "job",
    "people_liable_maintenance",
    "telephone",
    "foreign_worker",
]

R_SCORECARD_PARAMS: dict[str, object] = {
    "base_score": 600,
    "base_odds": "19:1",
    "points_to_double_odds": 50,
    "higher_score_is_lower_risk": True,
}

R_BASE_POINTS = 456


# ---------------------------------------------------------------------------
# Column-translation helpers
# ---------------------------------------------------------------------------


def r_col(r_name: str) -> str:
    """Translate R dot-name to Cardre underscore-name."""
    return R_TO_CARDRE.get(r_name, r_name)


def r_woe_col(r_woe_name: str) -> str:
    """Translate R ``status.of.existing.checking.account_woe`` to Cardre
    ``checking_account_status_woe``."""
    base = r_woe_name.replace("_woe", "")
    return r_col(base) + "_woe"


def r_woe_list(r_feature_names: list[str]) -> list[str]:
    """Translate a list of R feature names to Cardre _woe column names."""
    return [r_woe_col(f + "_woe") for f in r_feature_names]


# ---------------------------------------------------------------------------
# R golden-fixture → Cardre-artifact converters
# ---------------------------------------------------------------------------


def _parse_r_numeric_interval(label: str) -> tuple:
    """Parse a bin label like ``[-Inf,8)`` to ``(lower, upper, lower_inclusive,
    upper_inclusive)``."""
    m = re.match(r"^(\[|\()(.+?),\s*(.+?)(\]|\))$", label.strip())
    if not m:
        return None, None, False, False
    li = m.group(1) == "["
    ui = m.group(4) == "]"
    lower_raw = m.group(2).strip()
    upper_raw = m.group(3).strip()
    lower = None if lower_raw in ("-Inf", "-inf") else float(lower_raw)
    upper = None if upper_raw in ("Inf", "inf") else float(upper_raw)
    return lower, upper, li, ui


def _r_breaks_is_numeric(val) -> bool:
    """Check if a value can be parsed as a number (or Inf/-Inf)."""
    if isinstance(val, (int, float)):
        return True
    if not isinstance(val, str):
        return False
    val = val.strip()
    if val in ("Inf", "-Inf", "-inf", "inf", "NaN"):
        return True
    try:
        float(val)
        return True
    except ValueError:
        return False


def build_bin_def_from_r_bins(r_bins_json: dict) -> dict:
    """Convert R's ``bins_adj.json`` to Cardre's bin definition format.

    Fixes: categorical merged bins (e.g. ``"bank%,%stores"``) are split
    into separate category strings.
    """
    variables: list[dict] = []
    for r_var_name, bins in r_bins_json.items():
        cardre_var = r_col(r_var_name)
        first = bins[0]
        kind = "numeric" if _r_breaks_is_numeric(first.get("breaks", "")) else "categorical"

        cardre_bins: list[dict] = []
        for i, b in enumerate(bins):
            bin_id = f"{cardre_var}_rbin_{i:03d}"
            label = b.get("bin", "")
            breaks_val = b.get("breaks", "")
            is_special = bool(b.get("is_special_values", False))

            if kind == "numeric":
                lower, upper, li, ui = _parse_r_numeric_interval(label)
                cardre_bins.append({
                    "bin_id": bin_id,
                    "label": label,
                    "lower": lower,
                    "upper": upper,
                    "lower_inclusive": li,
                    "upper_inclusive": ui,
                    "categories": None,
                    "is_missing_bin": False,
                    "row_count": int(b.get("count", 0)),
                    "good_count": int(b.get("neg", 0)),
                    "bad_count": int(b.get("pos", 0)),
                })
            else:
                cats = _split_r_categories(breaks_val or label)
                cardre_bins.append({
                    "bin_id": bin_id,
                    "label": label,
                    "lower": None,
                    "upper": None,
                    "lower_inclusive": False,
                    "upper_inclusive": False,
                    "categories": cats,
                    "is_missing_bin": is_special,
                    "row_count": int(b.get("count", 0)),
                    "good_count": int(b.get("neg", 0)),
                    "bad_count": int(b.get("pos", 0)),
                })

        variables.append({"variable": cardre_var, "kind": kind, "bins": cardre_bins})

    return {"variables": variables, "warnings": []}


def _split_r_categories(breaks_label: str) -> list[str]:
    """Split R's ``%,%``-separated category labels into a cleaned list.

    R uses ``%,%`` as a delimiter in binning (e.g. ``"none%,%co-applicant"``).
    """
    return [c.strip() for c in breaks_label.split("%,%") if c.strip()]


def build_woe_table_from_r_bins(r_bins_json: dict) -> pl.DataFrame:
    """Convert R's ``bins_adj.json`` to Cardre's WOE table Parquet."""
    rows: list[dict] = []
    for r_var_name, bins in r_bins_json.items():
        cardre_var = r_col(r_var_name)
        total_good = sum(int(b.get("neg", 0)) for b in bins)
        total_bad = sum(int(b.get("pos", 0)) for b in bins)
        for i, b in enumerate(bins):
            good_cnt = int(b.get("neg", 0))
            bad_cnt = int(b.get("pos", 0))
            rows.append({
                "variable": cardre_var,
                "bin_id": f"{cardre_var}_rbin_{i:03d}",
                "label": b.get("bin", ""),
                "row_count": int(b.get("count", 0)),
                "good_count": good_cnt,
                "bad_count": bad_cnt,
                "good_distribution": good_cnt / max(total_good, 1),
                "bad_distribution": bad_cnt / max(total_bad, 1),
                "woe": float(b.get("woe", 0)),
                "iv_component": float(b.get("bin_iv", 0)),
            })
    return pl.DataFrame(rows)


def build_woe_data_from_r(
    r_woe_csv: pl.DataFrame,
    *,
    selected_vars: list[str] | None = None,
) -> pl.DataFrame:
    """Convert R's ``train_woe.csv`` / ``test_woe.csv`` to a Cardre-compatible
    dataframe with renamed columns and string-typed target."""
    woe_cols_r = [c for c in r_woe_csv.columns if c.endswith("_woe")]
    if selected_vars:
        needed = {f"{v}_woe" for v in selected_vars}
        woe_cols_r = [c for c in woe_cols_r if c in needed]

    cols_to_select = ["cardre_reference_row_number", "creditability"] + woe_cols_r
    result = r_woe_csv.select([c for c in cols_to_select if c in r_woe_csv.columns])

    if "creditability" in result.columns:
        result = result.with_columns(
            pl.col("creditability").cast(pl.Utf8).alias("credit_risk_class"),
        ).drop("creditability")

    rename_map = {}
    for c in woe_cols_r:
        cn = r_woe_col(c)
        if cn != c and c in result.columns:
            rename_map[c] = cn
    if rename_map:
        result = result.rename(rename_map)

    result = result.with_columns(
        pl.col(c).cast(pl.Float64) for c in result.columns if c.endswith("_woe")
    )
    if "cardre_reference_row_number" in result.columns:
        result = result.with_columns(pl.col("cardre_reference_row_number").cast(pl.Int64))

    return result
