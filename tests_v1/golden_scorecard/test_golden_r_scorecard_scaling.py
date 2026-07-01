"""Section D: Oracle tests for ScoreScalingNode.

Uses R's exact model coefficients + R bin definitions + R WOE table
to verify Cardre's scorecard formula produces the same points as R's
scorecard package.
"""

from __future__ import annotations

import json
import math

import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes import ScoreScalingNode
from tests.golden_scorecard.helpers import (
    R_BASE_POINTS,
    R_SCORECARD_PARAMS,
    build_bin_def_from_r_bins,
    build_woe_table_from_r_bins,
    r_woe_col,
)


def _build_model_artifact_from_r(store, golden_csv):
    """Construct a model artifact dict using R's exact coefficients."""
    coefficients = {}
    for row in golden_csv["model_coefficients"].iter_rows(named=True):
        term = row["term"]
        coef = float(row["coefficient"])
        if term == "(Intercept)":
            intercept = coef
        else:
            coefficients[r_woe_col(term)] = coef

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


def _run_scorecard(store, golden_csv, golden_json):
    """Run ScoreScalingNode with R's model + bins + WOE table."""
    model_dict, model_art = _build_model_artifact_from_r(store, golden_csv)

    bin_def = build_bin_def_from_r_bins(golden_json["bins_adj"])
    bin_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-bins", payload=bin_def,
    )

    woe_table = build_woe_table_from_r_bins(golden_json["bins_adj"])
    woe_art = write_parquet_artifact(
        store, artifact_type="report", role="report",
        stem="golden-woe-table", frame=woe_table,
    )

    meta = {
        "target_column": "credit_risk_class",
        "good_values": ["0"], "bad_values": ["1"],
        "indeterminate_values": [],
    }
    meta_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="golden-meta-sc", payload=meta,
    )

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
    out = ScoreScalingNode().run(ctx)
    sc_art = out.artifacts[0]
    scorecard_dict = json.loads(store.artifact_path(sc_art).read_text())
    return scorecard_dict, sc_art


class TestScorecardScalingOracle:
    """Oracle: Cardre scorecard ≈ R scorecard within rounding."""

    def test_base_points_match_r(self, store, golden_csv, golden_json):
        scorecard, _ = _run_scorecard(store, golden_csv, golden_json)
        assert scorecard["base_points"] == pytest.approx(R_BASE_POINTS, abs=0.5)

    def test_base_points_formula(self):
        factor = R_SCORECARD_PARAMS["points_to_double_odds"] / math.log(2)
        base_score = R_SCORECARD_PARAMS["base_score"]
        base_odds = 19.0
        offset = base_score - factor * math.log(base_odds)
        r_intercept = -0.94310901904204
        base_points = offset + (-1.0) * factor * r_intercept
        assert round(base_points, 2) == pytest.approx(R_BASE_POINTS, abs=0.5)

    def test_bin_points_match_r(self, store, golden_csv, golden_json):
        """Per-bin points within 0.5 of R's scorecard."""
        from tests.golden_scorecard.helpers import CARDRE_TO_R

        scorecard, _ = _run_scorecard(store, golden_csv, golden_json)
        r_sc = golden_csv["scorecard"]

        mismatches = []
        for attr in scorecard["attributes"]:
            cardre_var = attr["variable"]
            attr_woe = attr["woe"]
            r_var = CARDRE_TO_R.get(cardre_var, cardre_var)

            r_var_rows = r_sc.filter(pl.col("variable") == r_var)
            match = r_var_rows.filter(
                abs(pl.col("woe").cast(pl.Float64) - attr_woe) < 1e-6
            )
            if match.shape[0] == 0:
                mismatches.append(f"{cardre_var}: no R match for WOE={attr_woe:.6f}")
                continue
            r_points = float(match.select("points").item())
            diff = abs(attr["points"] - r_points)
            if diff >= 0.5:
                mismatches.append(
                    f"{cardre_var} '{attr['label']}': "
                    f"Cardre={attr['points']:.2f} R={r_points:.2f}"
                )
        assert not mismatches, "Bin point mismatches:\n" + "\n".join(mismatches)
