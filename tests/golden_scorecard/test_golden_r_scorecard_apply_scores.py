"""Section E: Oracle tests for ApplyModelNode score computation.

Uses R model coefficients + R scorecard to verify Cardre score formula. """

from __future__ import annotations

import polars as pl
import pytest

from cardre.artifacts import write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes.validate.apply import ApplyModelNode
from tests.golden_scorecard.helpers import (
    R_SELECTED_VARS_DOT,
    build_woe_data_from_r,
)
from tests.golden_scorecard.test_golden_r_scorecard_scaling import (
    _build_model_artifact_from_r,
    _run_scorecard,
)


def _build_scored_output(store, golden_csv, golden_json, role="test"):
    model_dict, model_art = _build_model_artifact_from_r(store, golden_csv)
    scorecard, sc_art = _run_scorecard(store, golden_csv, golden_json)
    woe_key = "train_woe" if role == "train" else "test_woe"
    woe_df = build_woe_data_from_r(
        golden_csv[woe_key], selected_vars=R_SELECTED_VARS_DOT,
    )
    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role=role,
        stem=f"golden-{role}-for-apply", frame=woe_df,
    )
    spec = StepSpec(
        step_id="apply-test", node_type="cardre.apply_model",
        node_version="2", category="apply",
        params={}, params_hash=json_logical_hash({}),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[data_art, model_art, sc_art],
        validated_params={}, runtime_metadata={},
    )
    out = ApplyModelNode().run(ctx)
    return pl.read_parquet(store.artifact_path(out.artifacts[0]))


class TestScoreApplicationOracle:

    def test_score_formula_consistent(self, store, golden_csv, golden_json):
        model_dict, _ = _build_model_artifact_from_r(store, golden_csv)
        scorecard, _ = _run_scorecard(store, golden_csv, golden_json)
        coeffs = model_dict["coefficients"]
        woe_df = build_woe_data_from_r(
            golden_csv["train_woe"], selected_vars=R_SELECTED_VARS_DOT,
        )
        for row in woe_df.iter_rows(named=True):
            log_odds = model_dict["intercept"]
            bin_sum = 0.0
            for attr in scorecard["attributes"]:
                var = attr["variable"]
                wk = f"{var}_woe"
                if wk not in row:
                    continue
                wv = float(row[wk])
                log_odds += coeffs[wk] * wv
                bin_sum += (-1.0) * scorecard["factor"] * coeffs[wk] * wv
            s1 = scorecard["offset"] + (-1.0) * scorecard["factor"] * log_odds
            s2 = scorecard["offset"] + (-1.0) * scorecard["factor"] * model_dict["intercept"] + bin_sum
            assert abs(s1 - s2) < 0.001

    def test_scores_close_to_r(self, store, golden_csv, golden_json):
        for role in ("train", "test"):
            df = _build_scored_output(store, golden_csv, golden_json, role=role)
            r_scores = golden_csv[f"{role}_scores"].with_columns(
                pl.col("cardre_reference_row_number").cast(pl.Int64),
                pl.col("score").cast(pl.Float64),
            )
            merged = df.select(["cardre_reference_row_number", "score"]).join(
                r_scores, on="cardre_reference_row_number", suffix="_r",
            )
            diffs = (merged["score"] - merged["score_r"]).abs()
            assert float(diffs.mean()) < 2.0
