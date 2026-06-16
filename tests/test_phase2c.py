"""Phase 2C tests: apply WOE, apply model, validation metrics, cutoff analysis."""

from __future__ import annotations

import io
import json
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
    ApplyWoeMappingNode,
    ApplyModelNode,
    ValidationMetricsNode,
    CutoffAnalysisNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

from tests.test_phase1 import make_store
from tests.test_phase2b import _make_train_artifact, _make_json_artifact, _make_parquet_report


# ======================================================================
# Apply WOE Mapping
# ======================================================================

class ApplyWoeMappingTests(unittest.TestCase):

    def setUp(self):
        self.store, self.tmp = make_store()
        self.store.initialize()
        self.df_train = pl.DataFrame({"x": [1.0, 2.0, 3.0], "target": ["g", "b", "g"]})
        self.df_test = pl.DataFrame({"x": [4.0, 5.0], "target": ["b", "g"]})
        self.train_art = _make_train_artifact(self.store, self.df_train, role="train")
        self.test_art = _make_train_artifact(self.store, self.df_test, role="test")
        self.bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 3,
                     "lower_inclusive": True, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "x_b2", "label": "High", "lower": 3, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
            "warnings": [],
        }
        self.bin_art = _make_json_artifact(self.store, self.bin_def, stem="bins")
        self.woe_df = pl.DataFrame({
            "variable": ["x", "x"], "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"], "row_count": [2, 1],
            "good_count": [1, 1], "bad_count": [1, 0],
            "good_distribution": [0.5, 0.5], "bad_distribution": [1.0, 0.0],
            "woe": [0.5, -0.3], "iv_component": [0.25, 0.15],
        })
        self.woe_art = _make_parquet_report(self.store, self.woe_df, stem="woe")

    def test_applies_woe_to_all_roles(self):
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, self.test_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        data_arts = [a for a in out.artifacts if a.role != "report"]
        report_arts = [a for a in out.artifacts if a.role == "report"]
        self.assertEqual(len(data_arts), 2)
        self.assertEqual(len(report_arts), 1)
        for art in data_arts:
            df = pl.read_parquet(self.store.artifact_path(art))
            self.assertIn("x_woe", df.columns)

    def test_unmatched_rows_fail_policy_raises(self):
        df_oot = pl.DataFrame({"x": [-1.0, -2.0], "target": ["g", "b"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "fail"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("did not match any bin", str(cm.exception))

    def test_unmatched_rows_invalid_policy_fails_validation(self):
        params = {"woe_unmatched_policy": "invalid"}
        self.assertIn("woe_unmatched_policy", ApplyWoeMappingNode().validate_params(params)[0])

    def test_unmatched_rows_warn_policy_fills_zero(self):
        df_oot = pl.DataFrame({"x": [-1.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[1]))
        self.assertEqual(df["x_woe"][0], 0.0)

    def test_unseen_category_in_oot_fails_with_fail_policy(self):
        store, tmp = make_store()
        store.initialize()
        df_train = pl.DataFrame({"cat": ["a", "b", "c"], "target": ["g", "b", "g"]})
        df_oot = pl.DataFrame({"cat": ["z"], "target": ["g"]})
        train_art = _make_train_artifact(store, df_train, role="train")
        oot_art = _make_train_artifact(store, df_oot, role="oot")
        bin_def = {
            "variables": [{
                "variable": "cat", "kind": "categorical",
                "bins": [
                    {"bin_id": "cat_b1", "label": "a", "categories": ["a"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 1, "bad_count": 0},
                    {"bin_id": "cat_b2", "label": "b", "categories": ["b"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 0, "bad_count": 1},
                    {"bin_id": "cat_b3", "label": "c", "categories": ["c"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="cat_bins")
        woe_df = pl.DataFrame({
            "variable": ["cat", "cat", "cat"],
            "bin_id": ["cat_b1", "cat_b2", "cat_b3"],
            "label": ["a", "b", "c"],
            "row_count": [1, 1, 1], "good_count": [1, 0, 1], "bad_count": [0, 1, 0],
            "good_distribution": [0.5, 0.0, 0.5], "bad_distribution": [0.0, 1.0, 0.0],
            "woe": [0.5, -0.5, 0.5], "iv_component": [0.25, 0.5, 0.25],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="cat_woe")
        params = {"woe_unmatched_policy": "fail"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[train_art, oot_art, bin_art, woe_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("did not match any bin", str(cm.exception))

    def test_below_min_numeric_value_fills_zero_by_default(self):
        df_oot = pl.DataFrame({"x": [-5.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[1]))
        self.assertEqual(df["x_woe"][0], 0.0)


# ======================================================================
# Apply Model
# ======================================================================

class ApplyModelTests(unittest.TestCase):

    def setUp(self):
        self.store, self.tmp = make_store()
        self.store.initialize()

        self.df = pl.DataFrame({
            "x_woe": [0.5, -0.3, 0.5],
            "target": ["g", "b", "g"],
        })
        self.train_art = _make_train_artifact(self.store, self.df, role="train")
        self.model = {
            "target_column": "target", "features": ["x_woe"],
            "intercept": -0.5, "coefficients": {"x_woe": 0.8},
            "class_mapping": {"good": "g", "bad": "b"}, "bad_class_label": "b",
            "training": {"row_count": 3, "converged": True, "iterations": 5, "params": {}},
            "warnings": [],
        }
        self.model_art = _make_json_artifact(self.store, self.model, role="model", stem="m1")
        self.scorecard = {
            "base_score": 600, "base_odds": 50, "points_to_double_odds": 20,
            "factor": round(20 / math.log(2), 6), "offset": round(600 - (20 / math.log(2)) * math.log(50), 6),
            "higher_score_is_lower_risk": True, "intercept": -0.5, "base_points": 500,
            "attributes": [], "target_column": "target",
        }
        self.sc_art = _make_json_artifact(self.store, self.scorecard, role="scorecard", stem="sc1")

    def test_produces_prediction_and_score_columns(self):
        params = {}
        spec = StepSpec(step_id="am", node_type="cardre.apply_model", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, self.model_art, self.sc_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyModelNode().run(ctx)
        self.assertEqual(len(out.artifacts), 1)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[0]))
        self.assertIn("predicted_bad_probability", df.columns)
        self.assertIn("score", df.columns)

    def test_missing_feature_fails(self):
        store, tmp = make_store()
        store.initialize()
        bad_df = pl.DataFrame({"wrong_col": [1.0], "target": ["g"]})
        buf = io.BytesIO()
        bad_df.write_parquet(buf)
        p = store.root / "datasets" / "bad-train.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(buf.getvalue())
        bad_art = ArtifactRef(
            artifact_id="bad-train-1", artifact_type="dataset", role="train",
            path=relative_path(p, store.root),
            physical_hash=physical_hash(p), logical_hash=table_logical_hash(bad_df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(bad_art)

        model_art = _make_json_artifact(store, self.model, role="model", stem="m2")
        sc_art = _make_json_artifact(store, self.scorecard, role="scorecard", stem="sc2")

        params = {}
        spec = StepSpec(step_id="am", node_type="cardre.apply_model", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r2", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[bad_art, model_art, sc_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError):
            ApplyModelNode().run(ctx)


# ======================================================================
# Validation Metrics
# ======================================================================

class ValidationMetricsTests(unittest.TestCase):

    def test_metrics_match_known_fixture(self):
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "target": ["good", "good", "bad", "bad", "good"],
            "predicted_bad_probability": [0.1, 0.2, 0.8, 0.9, 0.3],
            "score": [700, 650, 400, 350, 600],
        })
        train_art = _make_train_artifact(store, df, role="train")
        meta_art = _make_json_artifact(
            store, {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}, stem="meta"
        )

        params = {}
        spec = StepSpec(step_id="vm", node_type="cardre.validation_metrics", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[train_art, meta_art],
                               validated_params=params, runtime_metadata={})
        out = ValidationMetricsNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        role_report = report.get("train", {})
        self.assertIn("auc", role_report)
        self.assertIsNotNone(role_report["auc"])
        self.assertIn("gini", role_report)
        self.assertIn("ks", role_report)
        self.assertIn("calibration", role_report)
        self.assertIn("score_distribution", role_report)

    def test_psi_computed_when_multiple_roles(self):
        store, tmp = make_store()
        store.initialize()

        df_train = pl.DataFrame({
            "target": ["good"] * 20 + ["bad"] * 10,
            "predicted_bad_probability": [0.1]*10 + [0.9]*20,
            "score": [600]*30,
        })
        df_test = pl.DataFrame({
            "target": ["good"] * 5 + ["bad"] * 5,
            "predicted_bad_probability": [0.1]*5 + [0.9]*5,
            "score": [550]*10,
        })
        train_art = _make_train_artifact(store, df_train, role="train")
        test_art = _make_train_artifact(store, df_test, role="test")
        meta_art = _make_json_artifact(
            store, {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}, stem="meta"
        )

        params = {}
        spec = StepSpec(step_id="vm", node_type="cardre.validation_metrics", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[train_art, test_art, meta_art],
                               validated_params=params, runtime_metadata={})
        out = ValidationMetricsNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        self.assertIn("psi", report)


# ======================================================================
# Cutoff Analysis
# ======================================================================

class CutoffAnalysisTests(unittest.TestCase):

    def test_cutoff_produces_bands(self):
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "target": ["good"] * 3 + ["bad"] * 3,
            "predicted_bad_probability": [0.1, 0.2, 0.3, 0.7, 0.8, 0.9],
            "score": [700, 650, 600, 400, 350, 300],
        })
        train_art = _make_train_artifact(store, df, role="train")

        params = {"band_count": 3}
        spec = StepSpec(step_id="ca", node_type="cardre.cutoff_analysis", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[train_art],
                               validated_params=params, runtime_metadata={})
        out = CutoffAnalysisNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        train_report = report.get("train", {})
        self.assertIn("bands", train_report)
        self.assertGreater(len(train_report["bands"]), 0)
        for b in train_report["bands"]:
            self.assertIn("approval_rate", b)
            self.assertIn("bad_rate", b)
            self.assertIn("capture_rate", b)

    def test_band_count_validation(self):
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"score": [1.0, 2.0], "predicted_bad_probability": [0.1, 0.9]})
        art = _make_train_artifact(store, df, role="train")
        params = {"band_count": 1}
        spec = StepSpec(step_id="ca", node_type="cardre.cutoff_analysis", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError):
            CutoffAnalysisNode().run(ctx)


if __name__ == "__main__":
    unittest.main()
