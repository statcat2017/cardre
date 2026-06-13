"""Phase 2B acceptance tests covering WOE transform, logistic regression, score scaling, and build summary."""

from __future__ import annotations

import json
import io
import math
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    table_logical_hash,
    physical_hash,
    relative_path,
)
from cardre.executor import PlanExecutor
from cardre.nodes import (
    WoeTransformTrainNode,
    LogisticRegressionNode,
    ScoreScalingNode,
    BuildSummaryReportNode,
    FineClassingNode,
    ManualBinningNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

from tests.test_phase1 import make_store


# ======================================================================
# Helpers
# ======================================================================

def _make_train_artifact(store, df, role="train"):
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / f"test-{role}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=f"{role}_1", artifact_type="dataset", role=role,
        path=relative_path(path, store.root),
        physical_hash=physical_hash(path),
        logical_hash=table_logical_hash(df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(art)
    return art


def _make_json_artifact(store, payload, role="definition", stem="test"):
    p = store.root / "artifacts" / f"{stem}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, sort_keys=True))
    art = ArtifactRef(
        artifact_id=f"{stem}_1", artifact_type=role, role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=json_logical_hash(payload),
        media_type="application/json", metadata={},
    )
    store.register_artifact(art)
    return art


def _make_parquet_report(store, df, role="report", stem="report"):
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "datasets" / f"{stem}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=f"{stem}_1", artifact_type="report", role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=table_logical_hash(df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(art)
    return art


# ======================================================================
# WOE Transform Train
# ======================================================================

class WoeTransformTrainTests(unittest.TestCase):

    def test_woe_transform_maps_bins_to_woe(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 15.0, 25.0],
            "target": ["good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df)

        bin_def = {
            "variables": [{
                "variable": "var1", "kind": "numeric",
                "bins": [
                    {"bin_id": "v1_b1", "label": "Low", "lower": 0, "upper": 10,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "v1_b2", "label": "High", "lower": 10, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins")

        woe_df = pl.DataFrame({
            "variable": ["var1", "var1"],
            "bin_id": ["v1_b1", "v1_b2"],
            "label": ["Low", "High"],
            "row_count": [2, 2],
            "good_count": [1, 1],
            "bad_count": [1, 1],
            "good_distribution": [0.5, 0.5],
            "bad_distribution": [0.5, 0.5],
            "woe": [0.5, -0.5],
            "iv_component": [0.0, 0.25],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe")

        params = {}
        spec = StepSpec(
            step_id="woe-tf", node_type="cardre.woe_transform_train",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = WoeTransformTrainNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        transformed = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertIn("var1_woe", transformed.columns)
        self.assertEqual(transformed.height, 4)

    def test_woe_transform_deterministic(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "x": [1.0, 2.0, 3.0],
            "target": ["g", "b", "g"],
        })
        train_art = _make_train_artifact(store, df)
        bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 2,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "x_b2", "label": "High", "lower": 2, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins2")

        woe_df = pl.DataFrame({
            "variable": ["x", "x"],
            "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"],
            "row_count": [2, 1], "good_count": [1, 1], "bad_count": [1, 0],
            "good_distribution": [0.5, 0.5], "bad_distribution": [1.0, 0.0],
            "woe": [0.2, -0.3], "iv_component": [0.1, 0.15],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe2")

        params = {}
        spec = StepSpec(
            step_id="wt", node_type="cardre.woe_transform_train",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx1 = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        ctx2 = ExecutionContext(
            store=store, run_id="r2", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = WoeTransformTrainNode()
        out1 = node.run(ctx1)
        out2 = node.run(ctx2)
        self.assertEqual(
            out1.artifacts[0].logical_hash,
            out2.artifacts[0].logical_hash,
        )


# ======================================================================
# Logistic Regression
# ======================================================================

class LogisticRegressionTests(unittest.TestCase):

    def test_logistic_regression_fits_and_records_coefficients(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "x_woe": [0.5, -0.3, 0.5, -0.3],
            "target": ["bad", "good", "bad", "good"],
        })
        train_art = _make_train_artifact(store, df)

        meta = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_art = _make_json_artifact(store, meta, stem="meta")

        params = {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42}
        spec = StepSpec(
            step_id="lr", node_type="cardre.logistic_regression",
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

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "model")
        self.assertEqual(artifact.role, "model")

        model = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("features", model)
        self.assertIn("coefficients", model)
        self.assertIn("intercept", model)
        self.assertIn("class_mapping", model)
        self.assertEqual(model["class_mapping"]["bad"], "bad")
        self.assertIn("training", model)
        self.assertTrue(model["training"]["converged"])

    def test_logistic_regression_needs_woe_columns(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"x": [1, 2, 3], "target": ["g", "b", "g"]})
        train_art = _make_train_artifact(store, df)

        meta = {"target_column": "target", "good_values": ["g"], "bad_values": ["b"]}
        meta_art = _make_json_artifact(store, meta, stem="meta2")

        params = {"C": 1.0, "max_iter": 100, "solver": "lbfgs", "random_seed": 42}
        spec = StepSpec(
            step_id="lr", node_type="cardre.logistic_regression",
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
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Score Scaling
# ======================================================================

class ScoreScalingTests(unittest.TestCase):

    def test_score_scaling_produces_deterministic_points(self) -> None:
        store, tmp = make_store()
        store.initialize()

        model = {
            "target_column": "target",
            "features": ["x_woe"],
            "intercept": -0.5,
            "coefficients": {"x_woe": 0.8},
            "class_mapping": {"good": "g", "bad": "b"},
            "bad_class_label": "b",
            "training": {"row_count": 100, "converged": True, "iterations": 10, "params": {}},
            "warnings": [],
        }
        model_art = _make_json_artifact(store, model, role="model", stem="model")

        bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 10,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 50, "good_count": 40, "bad_count": 10},
                    {"bin_id": "x_b2", "label": "High", "lower": 10, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 50, "good_count": 30, "bad_count": 20},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins")

        woe_df = pl.DataFrame({
            "variable": ["x", "x"],
            "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"],
            "row_count": [50, 50], "good_count": [40, 30], "bad_count": [10, 20],
            "good_distribution": [0.5, 0.5], "bad_distribution": [0.5, 0.5],
            "woe": [0.3, -0.2], "iv_component": [0.1, 0.05],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe")

        params = {
            "base_score": 600, "base_odds": 50.0,
            "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
        }
        spec = StepSpec(
            step_id="ss", node_type="cardre.score_scaling",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[model_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = ScoreScalingNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "scorecard")
        scorecard = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("attributes", scorecard)
        self.assertIn("base_points", scorecard)
        self.assertGreater(scorecard["base_points"], 0)

        factor = 20 / math.log(2)
        offset = 600 - factor * math.log(50)
        intercept = -0.5
        direction = -1.0  # higher_score_is_lower_risk=True
        # base_points = offset + direction * factor * intercept
        expected_base = round(offset + direction * factor * intercept, 2)
        self.assertAlmostEqual(scorecard["base_points"], expected_base, delta=0.1)

        # Parity: score for any row should equal offset + direction * factor * (intercept + sum(coef * woe))
        coef_x = 0.8
        woe_low = 0.3
        expected_score_low = round(offset + direction * factor * (intercept + coef_x * woe_low), 2)
        attr_low = next(a for a in scorecard["attributes"] if a["bin_id"] == "x_b1")
        computed_score = scorecard["base_points"] + attr_low["points"]
        self.assertAlmostEqual(computed_score, expected_score_low, delta=0.1)

    def test_score_scaling_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        model = {"features": [], "coefficients": {}, "intercept": 0}
        model_art = _make_json_artifact(store, model, role="model", stem="model2")
        bin_art = _make_json_artifact(store, {"variables": [], "warnings": []}, stem="bins2")

        params = {
            "base_score": 600, "base_odds": 0,
            "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
        }
        spec = StepSpec(
            step_id="ss", node_type="cardre.score_scaling",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[model_art, bin_art],
            validated_params=params, runtime_metadata={},
        )
        node = ScoreScalingNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Build Summary Report
# ======================================================================

class BuildSummaryReportTests(unittest.TestCase):

    def test_build_summary_created(self) -> None:
        store, tmp = make_store()
        store.initialize()

        scorecard = {
            "base_score": 600, "base_odds": 50,
            "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
            "intercept": -0.5, "base_points": 500, "attributes": [],
            "target_column": "target",
        }
        sc_art = _make_json_artifact(store, scorecard, role="scorecard", stem="sc")

        model = {
            "target_column": "target", "features": ["x_woe"],
            "intercept": -0.5, "coefficients": {"x_woe": 0.8},
            "class_mapping": {"good": "g", "bad": "b"},
            "training": {"row_count": 100, "converged": True, "iterations": 10, "params": {}},
            "warnings": [],
        }
        model_art = _make_json_artifact(store, model, role="model", stem="model3")

        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["Low"],
            "row_count": [50], "good_count": [40], "bad_count": [10],
            "good_distribution": [0.5], "bad_distribution": [0.5],
            "woe": [0.3], "iv_component": [0.1],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe3")

        params = {}
        spec = StepSpec(
            step_id="bsr", node_type="cardre.build_summary_report",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[sc_art, model_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = BuildSummaryReportNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "report")
        report = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("model_summary", report)
        self.assertIn("scorecard_summary", report)
        self.assertIn("woe_iv_references", report)


# ======================================================================
# Phase 2B End-to-End Through Executor
# ======================================================================

class Phase2BEndToEndTests(unittest.TestCase):
    """Runs the full Phase 2A + 2B pathway through the executor."""

    def test_full_phase2b_pathway(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 15.0, 25.0, 5.0, 30.0, 8.0, 20.0],
            "target": ["good", "bad", "good", "bad", "good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_art = _make_json_artifact(store, meta_params, stem="meta")

        fine_params = {
            "max_bins": 5, "min_bin_fraction": 0.01,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 50, "exclude_columns": [],
        }
        fine_spec = StepSpec(
            step_id="fine-classing", node_type="cardre.fine_classing",
            node_version="1", category="fit",
            params=fine_params, params_hash=json_logical_hash(fine_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        fine_ctx = ExecutionContext(
            store=store, run_id="r_fc", plan_version_id="pv1",
            step_spec=fine_spec, parent_run_steps=[],
            input_artifacts=[train_art, meta_art],
            validated_params=fine_params, runtime_metadata={},
        )
        fc_output = FineClassingNode().run(fine_ctx)
        bin_art = fc_output.artifacts[0]

        # WOE/IV (initial + final combined via smoothing for simplicity)
        woe_params = {
            "zero_cell_policy": "block",
            "smoothing": {"method": "additive", "alpha": 0.5,
                          "rationale": "Small test fixture"},
            "purpose": "final",
        }
        woe_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=woe_params, params_hash=json_logical_hash(woe_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        from cardre.nodes import CalculateWoeIvNode
        woe_ctx = ExecutionContext(
            store=store, run_id="r_woe", plan_version_id="pv1",
            step_spec=woe_spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, meta_art],
            validated_params=woe_params, runtime_metadata={},
        )
        woe_output = CalculateWoeIvNode().run(woe_ctx)
        woe_art = woe_output.artifacts[0]  # WOE table

        # Manual binning (passthrough)
        mb_params = {"overrides": []}
        mb_spec = StepSpec(
            step_id="mb", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params=mb_params, params_hash=json_logical_hash(mb_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        mb_ctx = ExecutionContext(
            store=store, run_id="r_mb", plan_version_id="pv1",
            step_spec=mb_spec, parent_run_steps=[],
            input_artifacts=[bin_art],
            validated_params=mb_params, runtime_metadata={},
        )
        mb_output = ManualBinningNode().run(mb_ctx)
        refined_bin_art = mb_output.artifacts[0]

        # WOE transform train
        wt_params = {}
        wt_spec = StepSpec(
            step_id="wt", node_type="cardre.woe_transform_train",
            node_version="1", category="fit",
            params=wt_params, params_hash=json_logical_hash(wt_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        wt_ctx = ExecutionContext(
            store=store, run_id="r_wt", plan_version_id="pv1",
            step_spec=wt_spec, parent_run_steps=[],
            input_artifacts=[train_art, refined_bin_art, woe_art],
            validated_params=wt_params, runtime_metadata={},
        )
        wt_output = WoeTransformTrainNode().run(wt_ctx)
        woe_train_art = wt_output.artifacts[0]

        # Logistic regression
        lr_params = {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42}
        lr_spec = StepSpec(
            step_id="lr", node_type="cardre.logistic_regression",
            node_version="1", category="fit",
            params=lr_params, params_hash=json_logical_hash(lr_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        lr_ctx = ExecutionContext(
            store=store, run_id="r_lr", plan_version_id="pv1",
            step_spec=lr_spec, parent_run_steps=[],
            input_artifacts=[woe_train_art, meta_art],
            validated_params=lr_params, runtime_metadata={},
        )
        lr_output = LogisticRegressionNode().run(lr_ctx)
        model_art = lr_output.artifacts[0]

        # Score scaling
        ss_params = {
            "base_score": 600, "base_odds": 50.0,
            "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
        }
        ss_spec = StepSpec(
            step_id="ss", node_type="cardre.score_scaling",
            node_version="1", category="fit",
            params=ss_params, params_hash=json_logical_hash(ss_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ss_ctx = ExecutionContext(
            store=store, run_id="r_ss", plan_version_id="pv1",
            step_spec=ss_spec, parent_run_steps=[],
            input_artifacts=[model_art, refined_bin_art, woe_art],
            validated_params=ss_params, runtime_metadata={},
        )
        ss_output = ScoreScalingNode().run(ss_ctx)
        scorecard_art = ss_output.artifacts[0]

        # Build summary report
        bsr_params = {}
        bsr_spec = StepSpec(
            step_id="bsr", node_type="cardre.build_summary_report",
            node_version="1", category="fit",
            params=bsr_params, params_hash=json_logical_hash(bsr_params),
            parent_step_ids=[], branch_label="", position=0,
        )
        bsr_ctx = ExecutionContext(
            store=store, run_id="r_bsr", plan_version_id="pv1",
            step_spec=bsr_spec, parent_run_steps=[],
            input_artifacts=[scorecard_art, model_art, woe_art],
            validated_params=bsr_params, runtime_metadata={},
        )
        bsr_output = BuildSummaryReportNode().run(bsr_ctx)

        # Assertions
        self.assertEqual(lr_output.artifacts[0].artifact_type, "model")
        self.assertEqual(ss_output.artifacts[0].artifact_type, "scorecard")
        self.assertEqual(bsr_output.artifacts[0].artifact_type, "report")

        model = json.loads(store.artifact_path(lr_output.artifacts[0]).read_text())
        scorecard = json.loads(store.artifact_path(ss_output.artifacts[0]).read_text())
        self.assertIn("coefficients", model)
        self.assertIn("attributes", scorecard)
        self.assertGreater(len(scorecard["attributes"]), 0)

    def test_woe_transform_train_rejects_test_role(self) -> None:
        from cardre.executor import PlanExecutor, RoleAccessError
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"x": [1.0], "target": ["g"]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        test_art = ArtifactRef(
            artifact_id="test1", artifact_type="dataset", role="test",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(test_art)

        executor = PlanExecutor(NodeRegistry.with_defaults())
        node = WoeTransformTrainNode()
        with self.assertRaises(RoleAccessError):
            executor._validate_leakage_rules(node, [test_art])


if __name__ == "__main__":
    unittest.main()
