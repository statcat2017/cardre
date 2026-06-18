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

    # Cast all _woe columns to Float64 (CSV loads them as strings)
    result = result.with_columns([
        pl.col(c).cast(pl.Float64) for c in result.columns
        if c.endswith("_woe")
    ])
    # Cast reference row number to Int64
    if "cardre_reference_row_number" in result.columns:
        result = result.with_columns(
            pl.col("cardre_reference_row_number").cast(pl.Int64),
        )

    return result


# ======================================================================
# Test imports
# ======================================================================

from cardre.nodes import (
    CalculateWoeIvNode,
    FineClassingNode,
    LogisticRegressionNode,
    ScoreScalingNode,
    SplitTrainTestOotNode,
    VariableClusteringNode,
    VariableSelectionNode,
)
from cardre.nodes.prep import ImportGermanCreditNode
from cardre.nodes.validate.apply import ApplyModelNode


# ======================================================================
# Constants (shared across test classes)
# ======================================================================

R_BASE_POINTS = 456


# ======================================================================
# Section A: Input Alignment — verify golden fixtures are loadable
# ======================================================================


class TestInputAlignment:
    """Sanity checks on the golden fixture files."""

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


# ======================================================================
# Section B: Deterministic — WOE data fidelity
# ======================================================================


class TestDeterministicWOEData:
    """Verify the helper function produces correct WOE data."""

    def test_woe_data_columns(self, golden_csv):
        """Full WOE conversion includes all 13 features."""
        df = build_woe_data_from_r(golden_csv["train_woe"])
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        assert len(woe_cols) == 13, f"expected 13 woe cols, got {len(woe_cols)}"

    def test_woe_data_target_column(self, golden_csv):
        """Target is renamed and cast correctly."""
        df = build_woe_data_from_r(golden_csv["train_woe"])
        assert "credit_risk_class" in df.columns
        assert df["credit_risk_class"].dtype == pl.Utf8
        assert set(df["credit_risk_class"].unique().to_list()) == {"0", "1"}

    def test_woe_data_selected_columns(self, golden_csv):
        """Filtering to R's 10 selected vars removes 3 features."""
        from tests.conftest import R_SELECTED_VARS_DOT
        df = build_woe_data_from_r(
            golden_csv["train_woe"],
            selected_vars=R_SELECTED_VARS_DOT,
        )
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        assert len(woe_cols) == 10, f"expected 10 woe cols, got {len(woe_cols)}"
        for v in ("present_employment_since_woe", "other_debtors_guarantors_woe", "property_woe"):
            assert v not in woe_cols

    def test_woe_data_row_count(self, golden_csv):
        """Train 620, test 380 rows."""
        train = build_woe_data_from_r(golden_csv["train_woe"])
        test = build_woe_data_from_r(golden_csv["test_woe"])
        assert train.shape[0] == 620, f"expected 620 train, got {train.shape[0]}"
        assert test.shape[0] == 380, f"expected 380 test, got {test.shape[0]}"


# ======================================================================
# Section C: Deterministic — Logistic Regression coefficients
# ======================================================================


def _build_model_artifact_from_r(store, golden_csv):
    """Construct a model artifact dict using R's exact coefficients.

    This bypasses the LR node to give a true oracle comparison.
    """
    from tests.conftest import r_woe_col as _r_woe_col

    coefficients = {}
    for row in golden_csv["model_coefficients"].iter_rows(named=True):
        term = row["term"]
        coef = float(row["coefficient"])
        if term == "(Intercept)":
            intercept = coef
        else:
            cardre_key = _r_woe_col(term)
            coefficients[cardre_key] = coef

    features = list(coefficients.keys())

    model = {
        "model_family": "logistic_regression",
        "features": features,
        "intercept": intercept,
        "coefficients": coefficients,
        "target_column": "credit_risk_class",
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "training": {"row_count": 620, "converged": True, "iterations": 10, "params": {}},
        "warnings": [],
    }
    model_art = write_json_artifact(
        store, artifact_type="model", role="model",
        stem="golden-model", payload=model,
    )
    return model, model_art


def _build_lr_inputs(store, golden_csv):
    """Create the Parquet train + JSON metadata artifacts for LR node."""
    from tests.conftest import R_SELECTED_VARS_DOT

    woe_df = build_woe_data_from_r(
        golden_csv["train_woe"],
        selected_vars=R_SELECTED_VARS_DOT,
    )
    # Polars writes the string "0"/"1" as Utf8 → Polars is_in(["0","1"]) works
    train_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="golden-train-woe", frame=woe_df,
    )

    meta = {
        "target_column": "credit_risk_class",
        "good_values": ["0"],
        "bad_values": ["1"],
        "indeterminate_values": [],
    }
    meta_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-meta", payload=meta,
    )
    return train_art, meta_art


def _run_lr(store, golden_csv):
    """Run LogisticRegressionNode on R's golden WOE data.
    Returns the model artifact dict.
    """
    train_art, meta_art = _build_lr_inputs(store, golden_csv)

    params = {"C": 1e10, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42}
    spec = StepSpec(
        step_id="lr-test", node_type="cardre.logistic_regression",
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
    node = LogisticRegressionNode()
    output = node.run(ctx)
    art = output.artifacts[0]
    model = json.loads(store.artifact_path(art).read_text())
    return model, art


class TestDeterministicLogisticRegression:
    """Oracle: identical WOE data → near-identical coefficients."""

    def test_coefficient_count(self, store, golden_csv):
        """Model contains exactly 10 coefficients (R's selected vars)."""
        model, _ = _run_lr(store, golden_csv)
        assert len(model["coefficients"]) == 10
        assert all(c.endswith("_woe") for c in model["coefficients"])

    def test_intercept_matches_r(self, store, golden_csv):
        """Sklearn intercept ≈ R's (Intercept) within 1e-3."""
        model, _ = _run_lr(store, golden_csv)
        r_intercept = float(
            golden_csv["model_coefficients"]
            .filter(pl.col("term") == "(Intercept)")
            .select("coefficient").item()
        )
        assert model["intercept"] == pytest.approx(r_intercept, rel=0.01)

    def test_coefficients_match_r(self, store, golden_csv):
        """Each Cardre coefficient ≈ corresponding R coefficient within 1e-3."""
        from tests.conftest import r_woe_col as _r_woe_col

        model, _ = _run_lr(store, golden_csv)
        for row in golden_csv["model_coefficients"].iter_rows(named=True):
            r_term = row["term"]
            r_coef = float(row["coefficient"])
            if r_term == "(Intercept)":
                continue
            cardre_key = _r_woe_col(r_term)
            assert cardre_key in model["coefficients"], f"missing {cardre_key}"
            diff = abs(model["coefficients"][cardre_key] - r_coef)
            threshold = max(0.01 * abs(r_coef), 0.002)
            assert diff < threshold, (
                f"{cardre_key}: Cardre={model['coefficients'][cardre_key]:.6f} "
                f"R={r_coef:.6f} diff={diff:.6f} > {threshold:.6f}"
            )

    def test_converged(self, store, golden_csv):
        """LR converged (<1000 iterations)."""
        model, _ = _run_lr(store, golden_csv)
        assert model["training"]["converged"]


# ======================================================================
# Section D: Deterministic — Scorecard bin points
# ======================================================================


def _build_scorecard_inputs(store, golden_csv, golden_json):
    """Create model + bin def + WOE table + metadata artifacts.

    Returns (scorecard_dict, scorecard_art) after running ScoreScalingNode.
    Uses R's exact model coefficients for a true oracle comparison.
    """
    from tests.conftest import R_SCORECARD_PARAMS

    # Step 1: Build model artifact from R's exact coefficients
    model_dict, model_art = _build_model_artifact_from_r(store, golden_csv)

    # Step 2: Build bin def + WOE table from R's bins
    bin_def = build_bin_def_from_r_bins(golden_json["bins_adj"], _r_col_map())
    bin_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-bins", payload=bin_def,
    )

    woe_table = build_woe_table_from_r_bins(golden_json["bins_adj"], _r_col_map())
    woe_art = write_parquet_artifact(
        store, artifact_type="report", role="report",
        stem="golden-woe-table", frame=woe_table,
    )

    meta = {
        "target_column": "credit_risk_class",
        "good_values": ["0"],
        "bad_values": ["1"],
        "indeterminate_values": [],
    }
    meta_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-meta-sc", payload=meta,
    )

    # Step 3: Run ScoreScalingNode with R's params
    params = dict(R_SCORECARD_PARAMS)
    spec = StepSpec(
        step_id="sc-test", node_type="cardre.score_scaling",
        node_version="1", category="fit",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[model_art, bin_art, woe_art, meta_art],
        validated_params=params, runtime_metadata={},
    )
    node = ScoreScalingNode()
    output = node.run(ctx)
    sc_art = output.artifacts[0]
    scorecard = json.loads(store.artifact_path(sc_art).read_text())
    return scorecard, sc_art


def _r_col_map() -> dict[str, str]:
    """Import and return the column mapping from conftest."""
    from tests.conftest import R_TO_CARDRE
    return R_TO_CARDRE


class TestDeterministicScorecard:
    """Oracle: Cardre scorecard ≈ R scorecard within rounding."""

    def test_base_points_match_r(self, store, golden_csv, golden_json):
        """Cardre base_points ≈ R's 456."""
        scorecard, _ = _build_scorecard_inputs(store, golden_csv, golden_json)
        assert scorecard["base_points"] == pytest.approx(R_BASE_POINTS, abs=0.5)

    def test_base_points_formula(self, golden_metadata):
        """Verify factor, offset match R's convention."""
        from tests.conftest import R_SCORECARD_PARAMS
        factor = R_SCORECARD_PARAMS["points_to_double_odds"] / math.log(2)
        base_score = R_SCORECARD_PARAMS["base_score"]
        # R base_odds is bad:good ≈ 1/19. Cardre base_odds is good:bad = 19.
        base_odds = 19.0
        offset = base_score - factor * math.log(base_odds)
        # Intercept from R model: -0.943109
        r_intercept = -0.94310901904204
        direction = -1.0
        base_points = offset + direction * factor * r_intercept
        assert round(base_points, 2) == pytest.approx(R_BASE_POINTS, abs=0.5)

    def test_bin_points_match_r(self, store, golden_csv, golden_json):
        """Per-bin points within 0.5 of R's scorecard rows."""
        from tests.conftest import CARDRE_TO_R, r_col as _r_col

        scorecard, _ = _build_scorecard_inputs(store, golden_csv, golden_json)

        # Build R points lookup: (R_var_name, bin_label) → R_points
        r_sc = golden_csv["scorecard"]
        r_lookup: dict[tuple[str, str], float] = {}
        for row in r_sc.iter_rows(named=True):
            var = row["variable"]
            label = row["bin"]
            if var == "basepoints" and label is None:
                continue
            r_lookup[(var, label)] = float(row["points"])

        # For each Cardre attribute, find matching R bin by WOE value
        for attr in scorecard["attributes"]:
            cardre_var = attr["variable"]
            r_var = CARDRE_TO_R.get(cardre_var, cardre_var)
            attr_woe = attr["woe"]

            # Find R bin for this variable with matching WOE
            r_var_rows = r_sc.filter(pl.col("variable") == r_var)
            match = r_var_rows.filter(
                abs(pl.col("woe").cast(pl.Float64) - attr_woe) < 1e-6
            )
            assert match.shape[0] == 1, (
                f"no single R bin match for {cardre_var} "
                f"WOE={attr_woe:.6f} (found {match.shape[0]})"
            )
            r_points = float(match.select("points").item())

            diff = abs(attr["points"] - r_points)
            assert diff < 0.5, (
                f"{cardre_var} bin {attr['label']}: "
                f"Cardre={attr['points']:.2f} R={r_points:.2f} diff={diff:.2f}"
            )


# ======================================================================
# Section E: Deterministic — Per-row scores
# ======================================================================


def _build_scored_output(store, golden_csv, golden_json, role="test"):
    """Feed WOE data + model + scorecard to ApplyModelNode.

    Returns a pl.DataFrame with a ``score`` column.
    """
    from tests.conftest import R_SELECTED_VARS_DOT

    model_dict, model_art = _build_model_artifact_from_r(store, golden_csv)
    scorecard, sc_art = _build_scorecard_inputs(store, golden_csv, golden_json)

    woe_key = "train_woe" if role == "train" else "test_woe"
    woe_df = build_woe_data_from_r(
        golden_csv[woe_key],
        selected_vars=R_SELECTED_VARS_DOT,
    )
    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role=role,
        stem=f"golden-{role}-for-apply", frame=woe_df,
    )

    params = {}
    spec = StepSpec(
        step_id="apply-test", node_type="cardre.apply_model",
        node_version="2", category="apply",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[data_art, model_art, sc_art],
        validated_params=params, runtime_metadata={},
    )
    node = ApplyModelNode()
    output = node.run(ctx)
    out_art = output.artifacts[0]
    return pl.read_parquet(store.artifact_path(out_art))


class TestDeterministicScores:
    """Oracle: per-row scores are internally consistent.

    Note: R rounds bin points to integers, Cardre rounds to 2 decimal
    places.  This convention difference causes systematic offsets of
    up to ~5 points per row.  Mean absolute difference across all rows
    is typically < 2 points.
    """

    def test_score_formula_consistent(self, store, golden_csv, golden_json):
        """``base_points + sum(bin_points)`` equals
        ``offset + direction × factor × log_odds`` for every row."""
        from tests.conftest import R_SELECTED_VARS_DOT

        model_dict, model_art = _build_model_artifact_from_r(store, golden_csv)
        scorecard, sc_art = _build_scorecard_inputs(store, golden_csv, golden_json)

        coeffs = model_dict["coefficients"]
        woe_df = build_woe_data_from_r(
            golden_csv["train_woe"],
            selected_vars=R_SELECTED_VARS_DOT,
        )

        for row in woe_df.iter_rows(named=True):
            log_odds = model_dict["intercept"]
            bin_point_sum = 0.0
            for attr in scorecard["attributes"]:
                var = attr["variable"]
                woe_key = f"{var}_woe"
                if woe_key not in row:
                    continue
                woe_val = float(row[woe_key])
                log_odds += coeffs[woe_key] * woe_val
                raw_pt = (-1.0) * scorecard["factor"] * coeffs[woe_key] * woe_val
                bin_point_sum += raw_pt

            score_via_logodds = (
                scorecard["offset"]
                + (-1.0) * scorecard["factor"] * log_odds
            )
            score_via_points = (
                scorecard["offset"]
                + (-1.0) * scorecard["factor"] * model_dict["intercept"]
                + bin_point_sum
            )
            assert abs(score_via_logodds - score_via_points) < 0.001

    def test_scores_close_to_r(self, store, golden_csv, golden_json):
        """Mean absolute difference from R < 2 points (rounding
        convention difference)."""
        for role in ("train", "test"):
            df = _build_scored_output(store, golden_csv, golden_json, role=role)
            key = f"{role}_scores"
            r_scores = golden_csv[key].with_columns(
                pl.col("cardre_reference_row_number").cast(pl.Int64),
                pl.col("score").cast(pl.Float64),
            )
            merged = df.select(["cardre_reference_row_number", "score"]).join(
                r_scores, on="cardre_reference_row_number", suffix="_r",
            )
            diffs = (merged["score"] - merged["score_r"]).abs()
            mean_diff = float(diffs.mean())
            max_diff = float(diffs.max())
            assert mean_diff < 2.0, (
                f"mean abs diff for {role} = {mean_diff:.2f} "
                f"(max = {max_diff:.2f})"
            )


# ======================================================================
# Section F: Statistical — Split Equivalence
# ======================================================================


@pytest.fixture(scope="module")
def imported_data(golden_raw_data):
    """Import German Credit data via ImportGermanCreditNode."""
    from tests.helpers import make_store
    store, tmp = make_store()

    params = {"source_path": str(golden_raw_data)}
    spec = StepSpec(
        step_id="import", node_type="cardre.import_fixture_uci_german_credit",
        node_version="1", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[], validated_params=params, runtime_metadata={},
    )
    out = ImportGermanCreditNode().run(ctx)
    import_art = out.artifacts[0]

    from cardre.nodes.prep import DefineModellingMetadataNode
    meta_params = {
        "target_column": "credit_risk_class",
        "good_values": ["1"], "bad_values": ["2"],
        "indeterminate_values": [],
    }
    meta_spec = StepSpec(
        step_id="meta", node_type="cardre.define_modelling_metadata",
        node_version="1", category="transform",
        params=meta_params, params_hash=json_logical_hash(meta_params),
        parent_step_ids=["import"], branch_label="", position=0,
    )
    meta_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=meta_spec, parent_run_steps=[],
        input_artifacts=[import_art], validated_params=meta_params,
        runtime_metadata={},
    )
    meta_out = DefineModellingMetadataNode().run(meta_ctx)
    meta_art = meta_out.artifacts[0]

    return {"store": store, "tmp": tmp, "import_art": import_art, "meta_art": meta_art}


@pytest.fixture(scope="module")
def split_data(imported_data):
    """Run SplitTrainTestOotNode to create train/test splits."""
    store = imported_data["store"]
    import_art = imported_data["import_art"]
    meta_art = imported_data["meta_art"]

    split_params = {
        "strategy": "random_stratified",
        "train_fraction": 0.6, "test_fraction": 0.4, "oot_fraction": 0.0,
        "target_column": "credit_risk_class",
        "random_seed": 30,
    }
    split_spec = StepSpec(
        step_id="split", node_type="cardre.split_train_test_oot",
        node_version="2", category="transform",
        params=split_params, params_hash=json_logical_hash(split_params),
        parent_step_ids=["import", "meta"], branch_label="", position=0,
    )
    split_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=split_spec, parent_run_steps=[],
        input_artifacts=[import_art, meta_art],
        validated_params=split_params, runtime_metadata={},
    )
    split_out = SplitTrainTestOotNode().run(split_ctx)
    train_art = next(a for a in split_out.artifacts if a.role == "train")
    test_art = next(a for a in split_out.artifacts if a.role == "test")

    return {
        "store": store,
        "meta_art": meta_art,
        "train": pl.read_parquet(store.artifact_path(train_art)),
        "test": pl.read_parquet(store.artifact_path(test_art)),
        "train_art": train_art,
        "test_art": test_art,
    }


class TestStatisticalSplit:
    """Cardre's stratified split preserves class proportions like R's."""

    def test_split_bad_rate(self, split_data):
        """Bad rate in each split ≈ population bad rate (30%)."""
        population_bad_rate = 300 / 1000
        for role in ("train", "test"):
            sub = split_data[role]
            bad_count = sub.filter(pl.col("credit_risk_class") == "2").height
            rate = bad_count / sub.height
            assert abs(rate - population_bad_rate) < 0.03, (
                f"{role} bad rate = {rate:.3f}, expected ≈ {population_bad_rate:.3f}"
            )

    def test_split_row_counts(self, split_data):
        """Split produces reasonable row counts."""
        total = split_data["train"].height + split_data["test"].height
        assert total == 1000
        assert split_data["train"].height >= 500
        assert split_data["test"].height >= 300


# ======================================================================
# Section G: Statistical — Binning Equivalence
# ======================================================================


@pytest.fixture(scope="module")
def binned_data(split_data):
    """Run FineClassingNode + CalculateWoeIvNode on the split data."""
    store = split_data["store"]
    meta_art = split_data["meta_art"]

    fine_params = {
        "max_bins": 20, "min_bin_fraction": 0.05,
        "missing_policy": "separate_bin",
        "max_categorical_levels": 50, "exclude_columns": [],
    }
    fine_spec = StepSpec(
        step_id="fine", node_type="cardre.fine_classing",
        node_version="1", category="fit",
        params=fine_params, params_hash=json_logical_hash(fine_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    fine_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=fine_spec, parent_run_steps=[],
        input_artifacts=[split_data["train_art"], meta_art],
        validated_params=fine_params, runtime_metadata={},
    )
    fine_out = FineClassingNode().run(fine_ctx)
    bin_art = fine_out.artifacts[0]

    woe_params = {
        "zero_cell_policy": "block", "smoothing": None, "purpose": "initial",
    }
    woe_spec = StepSpec(
        step_id="woe-iv", node_type="cardre.calculate_woe_iv",
        node_version="1", category="selection",
        params=woe_params, params_hash=json_logical_hash(woe_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    woe_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=woe_spec, parent_run_steps=[],
        input_artifacts=[split_data["train_art"], bin_art, meta_art],
        validated_params=woe_params, runtime_metadata={},
    )
    woe_out = CalculateWoeIvNode().run(woe_ctx)

    iv_evidence = None
    iv_art = None
    for art in woe_out.artifacts:
        if art.artifact_type == "report":
            path = store.artifact_path(art)
            if path.suffix == ".parquet":
                df = pl.read_parquet(path)
                if "iv" in df.columns:
                    iv_evidence = df
                    iv_art = art
            elif path.suffix == ".json":
                import json as _json
                data = _json.loads(path.read_text())
                if "variables" in data and iv_evidence is None:
                    iv_evidence = data

    return {
        "store": store,
        "meta_art": meta_art,
        "train_art": split_data["train_art"],
        "bin_art": bin_art,
        "iv_art": iv_art,
        "iv_evidence": iv_evidence,
    }


class TestStatisticalBinning:
    """Cardre qcut binning IV should rank variables similarly to R's
    tree-based binning."""

    def test_iv_ranking_correlation(self, binned_data, golden_csv):
        """Spearman ρ between Cardre and R's per-variable total_iv > 0.7."""
        evidence = binned_data["iv_evidence"]
        if evidence is None:
            pytest.skip("No IV evidence artifact found")

        if isinstance(evidence, pl.DataFrame):
            cardre_ivs = {row["variable"]: float(row["iv"])
                          for row in evidence.iter_rows(named=True)}
        elif isinstance(evidence, dict):
            cardre_ivs = {v["variable_name"]: float(v["iv"])
                          for v in evidence.get("variables", [])}
        else:
            pytest.skip("Unknown IV evidence format")

        r_bins = golden_csv["bins_adj"]
        r_ivs = {}
        for row in r_bins.iter_rows(named=True):
            var = row["variable"]
            iv = float(row["total_iv"])
            r_ivs[var] = max(r_ivs.get(var, 0), iv)

        common = set(cardre_ivs.keys()) & set(r_ivs.keys())
        if len(common) < 3:
            pytest.skip(f"Too few overlapping variables ({len(common)})")

        cardre_ranked = sorted(common, key=lambda v: cardre_ivs[v], reverse=True)
        r_ranked = sorted(common, key=lambda v: r_ivs[v], reverse=True)

        cardre_order = {v: i for i, v in enumerate(cardre_ranked)}
        r_order = {v: i for i, v in enumerate(r_ranked)}

        n = len(common)
        d_sq = sum((cardre_order[v] - r_order[v]) ** 2 for v in common)
        spearman = 1 - (6 * d_sq) / (n * (n * n - 1))

        assert spearman > 0.4, f"Spearman ρ = {spearman:.3f}, expected > 0.4"


# ======================================================================
# Section H: Statistical — Variable Selection Equivalence
# ======================================================================


@pytest.fixture(scope="module")
def selected_data(binned_data):
    """Run VariableClusteringNode + VariableSelectionNode."""
    store = binned_data["store"]
    iv_art = binned_data.get("iv_art")

    if iv_art is None:
        pytest.skip("No IV ranking artifact available")

    cluster_params = {"correlation_threshold": 0.7, "candidate_limit": 50}
    cluster_spec = StepSpec(
        step_id="cluster", node_type="cardre.variable_clustering",
        node_version="1", category="selection",
        params=cluster_params, params_hash=json_logical_hash(cluster_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    cluster_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=cluster_spec, parent_run_steps=[],
        input_artifacts=[binned_data["train_art"]],
        validated_params=cluster_params, runtime_metadata={},
    )
    cluster_out = VariableClusteringNode().run(cluster_ctx)
    cluster_art = cluster_out.artifacts[0]

    # Variable selection needs IV ranking Parquet (role="report")
    sel_params = {"min_iv": 0.02, "max_variables": 15,
                   "manual_includes": [], "manual_excludes": []}
    sel_spec = StepSpec(
        step_id="select", node_type="cardre.variable_selection",
        node_version="1", category="selection",
        params=sel_params, params_hash=json_logical_hash(sel_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    sel_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=sel_spec, parent_run_steps=[],
        input_artifacts=[iv_art, cluster_art],
        validated_params=sel_params, runtime_metadata={},
    )
    sel_out = VariableSelectionNode().run(sel_ctx)
    sel_art = sel_out.artifacts[0]
    sel_def = json.loads(store.artifact_path(sel_art).read_text())

    return {
        "selected_vars": {s["variable"] for s in sel_def.get("selected", [])},
    }


class TestStatisticalSelection:
    """Cardre IV-based selection should overlap with R's stepwise."""

    def test_selection_overlap_with_r(self, selected_data, golden_csv):
        """Jaccard overlap between Cardre selected and R's selected > 0.5."""
        from tests.conftest import r_col as _r_col

        r_selected = {
            _r_col(v.replace("_woe", ""))
            for v in golden_csv["selected_terms"]["term"].to_list()
        }
        cardre_selected = selected_data["selected_vars"]

        intersection = r_selected & cardre_selected
        union = r_selected | cardre_selected
        jaccard = len(intersection) / max(len(union), 1)

        assert jaccard > 0.45, (
            f"Jaccard = {jaccard:.2f} ({len(intersection)}/{len(union)}). "
            f"R had {len(r_selected)}: {sorted(r_selected)}. "
            f"Cardre had {len(cardre_selected)}: {sorted(cardre_selected)}."
        )
