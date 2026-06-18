"""Golden comparison tests: Cardre vs R scorecard reference fixtures.

Deterministic steps use R's golden fixture outputs as Cardre inputs and
verify exact match.  Random / algorithm-difference steps show statistical
equivalence.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash

# ======================================================================
# Phase 1: Helper functions to convert R golden fixtures → Cardre inputs
# ======================================================================


def _parse_numeric_interval(label: str) -> tuple:
    """Parse a bin label like ``[-Inf,8)`` or ``[44, Inf)``.

    Returns ``(lower, upper, lower_inclusive, upper_inclusive)``.

    ``None`` in lower/upper means unbounded.  ``Inf`` in the label is
    mapped to ``None`` (unbounded) since Cardre's bin definition uses
    ``null`` for no bound.
    """
    m = re.match(r"^(\[|\()(.+?),\s*(.+?)(\]|\))$", label.strip())
    if not m:
        return None, None, False, False
    li = m.group(1) == "["
    ui = m.group(4) == "]"
    raw_lower = m.group(2).strip()
    raw_upper = m.group(3).strip()
    lower = None if raw_lower in ("-Inf", "-inf") else float(raw_lower)
    upper = None if raw_upper in ("Inf", "inf") else float(raw_upper)
    return lower, upper, li, ui


def _looks_numeric(val) -> bool:
    """Check if a value can be parsed as a number (or is ``Inf``/``-Inf``)."""
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


def build_bin_def_from_r_bins(r_bins_json: dict, r_col_map: dict[str, str]) -> dict:
    """Convert R's ``bins_adj.json`` to Cardre's bin definition format.

    R's format (from ``scorecard::woebin``)::

        {"status.of.existing.checking.account": [
            {"variable": ..., "bin": "...", "count": ...,
             "neg": ..., "pos": ..., "woe": ..., "breaks": ...,
             "is_special_values": ...},
        ], ...}

    Cardre's format::

        {"variables": [{"variable": str, "kind": "numeric" | "categorical",
                        "bins": [{"bin_id": str, "label": str, ...}]}],
         "warnings": []}
    """
    from tests.conftest import r_col as _r_col

    variables: list[dict] = []
    for r_var_name, bins in r_bins_json.items():
        cardre_var = _r_col(r_var_name)

        # Determine kind from the first bin's breaks
        first = bins[0]
        kind = "numeric" if _looks_numeric(first.get("breaks", "")) else "categorical"

        cardre_bins: list[dict] = []
        for i, b in enumerate(bins):
            bin_id = f"{cardre_var}_rbin_{i:03d}"
            label = b.get("bin", "")
            breaks_val = b.get("breaks", "")
            is_special = bool(b.get("is_special_values", False))

            if kind == "numeric":
                lower, upper, li, ui = _parse_numeric_interval(label)
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
                # Categorical: the breaks value may contain %,% separator
                # for merged categories.
                cats = [breaks_val] if breaks_val else [label]
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

        variables.append({
            "variable": cardre_var,
            "kind": kind,
            "bins": cardre_bins,
        })

    return {"variables": variables, "warnings": []}


def build_woe_table_from_r_bins(r_bins_json: dict, r_col_map: dict[str, str]) -> pl.DataFrame:
    """Convert R's ``bins_adj.json`` to Cardre's WOE table Parquet.

    The WOE table columns match what ``ArtifactEvidenceReader`` expects:
    ``variable, bin_id, label, row_count, good_count, bad_count,
    good_distribution, bad_distribution, woe, iv_component``.
    """
    from tests.conftest import r_col as _r_col

    rows: list[dict] = []
    for r_var_name, bins in r_bins_json.items():
        cardre_var = _r_col(r_var_name)
        # Compute total good and bad for this variable for distributions
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
    r_raw_csv: pl.DataFrame,
    r_col_map: dict[str, str],
    *,
    selected_vars: list[str] | None = None,
) -> pl.DataFrame:
    """Convert R's ``train_woe.csv`` / ``test_woe.csv`` to a Cardre-compatible
    Parquet dataframe.

    R's WOE CSV already contains ``cardre_reference_row_number``,
    ``creditability`` (0/1 integer), and ``{r_var}_woe`` columns.  This
    function renames:
    - ``creditability`` → ``credit_risk_class`` (cast to string "0"/"1")
    - ``{r_var}_woe`` → ``{cardre_var}_woe`` (dots → underscores)
    """
    from tests.conftest import r_woe_col as _r_woe_col

    woe_cols_r = [c for c in r_woe_csv.columns if c.endswith("_woe")]
    if selected_vars:
        needed = {f"{v}_woe" for v in selected_vars}
        woe_cols_r = [c for c in woe_cols_r if c in needed]

    cols_to_select = ["cardre_reference_row_number", "creditability"] + woe_cols_r
    result = r_woe_csv.select([c for c in cols_to_select if c in r_woe_csv.columns])

    # Rename + cast target: creditability (int 0/1) → credit_risk_class (str "0"/"1")
    if "creditability" in result.columns:
        result = result.with_columns(
            pl.col("creditability").cast(pl.Utf8).alias("credit_risk_class"),
        ).drop("creditability")

    # Rename _woe columns
    rename_map = {}
    for c in woe_cols_r:
        cardre_name = _r_woe_col(c)
        if cardre_name != c and c in result.columns:
            rename_map[c] = cardre_name
    if rename_map:
        result = result.rename(rename_map)

    return result


# ======================================================================
# Constants (shared across test classes)
# =====================================================================

R_BASE_POINTS = 456
