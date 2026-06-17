"""Tests for Phase 8 (optional boosting) and Phase 9 (fairness/proxy/alt-data)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.fairness import (
    AlternativeDataManifestNode,
    FairnessReportNode,
    ProxyRiskReportNode,
)
from cardre.nodes.ml_models import DecisionTreeNode
from cardre.store import ProjectStore

from tests.helpers import make_store


# ======================================================================
# Helpers
# ======================================================================


def make_dataset_with_sensitive(
    store: ProjectStore,
    n_rows: int = 200,
    seed: int = 42,
) -> tuple:
    rng = np.random.RandomState(seed)
    feat_a = rng.randn(n_rows) * 10 + 50
    feat_b = rng.randn(n_rows) * 5 + 20
    gender = rng.choice(["M", "F"], size=n_rows).tolist()
    age_group = rng.choice(["young", "middle", "senior"], size=n_rows).tolist()
    target = ["bad" if feat_a[i] > 55 and feat_b[i] > 22 else "good" for i in range(n_rows)]

    df = pl.DataFrame({
        "feat_a": feat_a,
        "feat_b": feat_b,
        "gender": gender,
        "age_group": age_group,
        "target": target,
    })

    from cardre.artifacts import write_json_artifact, write_parquet_artifact
    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="sensitive-train", frame=df, metadata={},
    )
    def_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="sensitive-def",
        payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
        metadata={},
    )
    return data_art, def_art, df


def make_scored_dataset(store, data_art, def_art, step_id="score"):
    """Fit a decision tree and apply it to produce scored data."""
    from cardre.nodes.ml_models import DecisionTreeNode
    from cardre.nodes.validate import ApplyModelNode

    dt_ctx = ExecutionContext(
        store=store, run_id="test-run", plan_version_id="test-pv",
        step_spec=StepSpec(step_id=step_id + "-dt", node_type="cardre.decision_tree_classifier",
                           node_version="1", category="fit",
                           params={"feature_strategy": "raw_numeric", "max_depth": 3, "random_seed": 42,
                                   "include_columns": ["feat_a", "feat_b"]},
                           params_hash=json_logical_hash({"feature_strategy": "raw_numeric", "max_depth": 3, "random_seed": 42,
                                                          "include_columns": ["feat_a", "feat_b"]}),
                           parent_step_ids=[], branch_label="", position=0),
        parent_run_steps=[], input_artifacts=[data_art, def_art],
        validated_params={"feature_strategy": "raw_numeric", "max_depth": 3, "random_seed": 42,
                          "include_columns": ["feat_a", "feat_b"]},
        runtime_metadata={},
    )
    dt_out = DecisionTreeNode().run(dt_ctx)
    model_art = dt_out.artifacts[0]

    apply_ctx = ExecutionContext(
        store=store, run_id="test-run", plan_version_id="test-pv",
        step_spec=StepSpec(step_id=step_id + "-apply", node_type="cardre.apply_model",
                           node_version="2", category="apply", params={},
                           params_hash=json_logical_hash({}), parent_step_ids=[],
                           branch_label="", position=0),
        parent_run_steps=[], input_artifacts=[data_art, model_art],
        validated_params={}, runtime_metadata={},
    )
    apply_out = ApplyModelNode().run(apply_ctx)

    # Add score column
    scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
    score_vals = (1.0 - scored_df["predicted_bad_probability"]) * 1000
    scored_df = scored_df.with_columns(pl.Series("score", score_vals, dtype=pl.Float64))

    from cardre.artifacts import write_parquet_artifact
    scored_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem=f"scored-{step_id}", frame=scored_df, metadata={},
    )
    return scored_art, model_art


def make_ctx(store, artifacts, node_type, *, params=None, step_id="step", category="report"):
    if params is None:
        params = {}
    step_spec = StepSpec(
        step_id=step_id, node_type=node_type, node_version="1", category=category,
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    return ExecutionContext(
        store=store, run_id="test-run", plan_version_id="test-pv",
        step_spec=step_spec, parent_run_steps=[],
        input_artifacts=artifacts,
        validated_params=params, runtime_metadata={},
    )


# ======================================================================
# Phase 8: Optional Boosting Tests
# ======================================================================

class OptionalBoostingImportTests(unittest.TestCase):

    def test_xgboost_import_error(self) -> None:
        """Verify clear error message when xgboost is not installed."""
        from cardre.nodes.boosting import _check_optional_dependency
        try:
            __import__("xgboost")
            self.skipTest("xgboost is installed")
        except ImportError:
            with self.assertRaises(ImportError) as cm:
                _check_optional_dependency("xgboost", "xgboost")
            self.assertIn("xgboost", str(cm.exception))

    def test_lightgbm_import_error(self) -> None:
        from cardre.nodes.boosting import _check_optional_dependency
        try:
            __import__("lightgbm")
            self.skipTest("lightgbm is installed")
        except ImportError:
            with self.assertRaises(ImportError) as cm:
                _check_optional_dependency("lightgbm", "lightgbm")
            self.assertIn("lightgbm", str(cm.exception))

    def test_catboost_import_error(self) -> None:
        from cardre.nodes.boosting import _check_optional_dependency
        try:
            __import__("catboost")
            self.skipTest("catboost is installed")
        except ImportError:
            with self.assertRaises(ImportError) as cm:
                _check_optional_dependency("catboost", "catboost")
            self.assertIn("catboost", str(cm.exception))


class XGBoostParameterTests(unittest.TestCase):
    """Tests that work regardless of whether xgboost is installed."""

    def test_validate_params(self) -> None:
        from cardre.nodes.boosting import XGBoostClassifierNode
        node = XGBoostClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "n_estimators": 100,
            "max_depth": 6,
            "learning_rate": 0.1,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_invalid_feature_strategy(self) -> None:
        from cardre.nodes.boosting import XGBoostClassifierNode
        node = XGBoostClassifierNode()
        errors = node.validate_params({"feature_strategy": "invalid"})
        self.assertGreater(len(errors), 0)


class LightGBMParameterTests(unittest.TestCase):

    def test_validate_params(self) -> None:
        from cardre.nodes.boosting import LightGBMClassifierNode
        node = LightGBMClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "n_estimators": 100,
            "max_depth": -1,
            "learning_rate": 0.1,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])


class CatBoostParameterTests(unittest.TestCase):

    def test_validate_params(self) -> None:
        from cardre.nodes.boosting import CatBoostClassifierNode
        node = CatBoostClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "iterations": 100,
            "depth": 6,
            "learning_rate": 0.1,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])


# ======================================================================
# Phase 9: Fairness Report Tests
# ======================================================================

class FairnessReportParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = FairnessReportNode()
        errors = node.validate_params({"sensitive_columns": ["gender"], "cutoff": 0.5})
        self.assertEqual(errors, [])

    def test_empty_sensitive_columns(self) -> None:
        node = FairnessReportNode()
        errors = node.validate_params({"sensitive_columns": []})
        self.assertGreater(len(errors), 0)


class FairnessReportRunTests(unittest.TestCase):

    def test_fairness_report_by_gender(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)
        scored_art, _ = make_scored_dataset(store, data_art, def_art, "fair-gender")

        ctx = make_ctx(store, [scored_art, def_art], "cardre.fairness_report",
                       params={"sensitive_columns": ["gender"], "cutoff": 0.5})
        out = FairnessReportNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertIn("roles", report)
        self.assertIn("train", report["roles"])
        self.assertIn("group_metrics", report["roles"]["train"])
        self.assertIn("gender", report["roles"]["train"]["group_metrics"])

        gender_metrics = report["roles"]["train"]["group_metrics"]["gender"]
        for group_val, metrics in gender_metrics.items():
            if isinstance(metrics, dict) and metrics.get("status") != "insufficient_evidence":
                self.assertIn("approval_rate", metrics)
                self.assertIn("bad_rate", metrics)
                self.assertIn("precision", metrics)
                self.assertIn("recall", metrics)

    def test_fairness_report_parity_summary(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)
        scored_art, _ = make_scored_dataset(store, data_art, def_art, "fair-parity")

        ctx = make_ctx(store, [scored_art, def_art], "cardre.fairness_report",
                       params={"sensitive_columns": ["gender", "age_group"], "cutoff": 0.5})
        out = FairnessReportNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertIn("parity_summary", report)
        self.assertIn("gender", report["parity_summary"])

    def test_small_groups_suppressed(self) -> None:
        store, tmp = make_store()
        rng = np.random.RandomState(42)
        df = pl.DataFrame({
            "feat_a": rng.randn(100) * 10 + 50,
            "predicted_bad_probability": rng.uniform(0, 1, 100),
            "score": rng.uniform(300, 800, 100),
            "gender": ["M"] * 95 + ["F"] * 5,  # F group too small
            "target": ["good"] * 90 + ["bad"] * 10,
        })
        from cardre.artifacts import write_json_artifact, write_parquet_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="small-group", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="small-group-def",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={},
        )

        ctx = make_ctx(store, [data_art, def_art], "cardre.fairness_report",
                       params={"sensitive_columns": ["gender"], "min_group_size": 30})
        out = FairnessReportNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        gender_metrics = report["roles"]["train"]["group_metrics"]["gender"]
        f_metrics = gender_metrics.get("F", {})
        self.assertEqual(f_metrics.get("status"), "insufficient_evidence")


# ======================================================================
# Phase 9: Proxy Risk Report Tests
# ======================================================================

class ProxyRiskReportParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = ProxyRiskReportNode()
        errors = node.validate_params({
            "sensitive_columns": ["gender"],
            "correlation_threshold": 0.3,
        })
        self.assertEqual(errors, [])


class ProxyRiskReportRunTests(unittest.TestCase):

    def test_proxy_risk_low_when_no_correlation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)
        scored_art, model_art = make_scored_dataset(store, data_art, def_art, "proxy-low")

        ctx = make_ctx(store, [scored_art, model_art], "cardre.proxy_risk_report",
                       params={"sensitive_columns": ["gender"], "correlation_threshold": 0.3})
        out = ProxyRiskReportNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertIn("proxy_flags", report)
        self.assertIn("overall_risk", report)

    def test_proxy_risk_detects_direct_sensitive_in_model(self) -> None:
        """If a sensitive column is in model features, it should be flagged."""
        store, tmp = make_store()
        rng = np.random.RandomState(42)
        df = pl.DataFrame({
            "feat_a": rng.randn(100) * 10 + 50,
            "gender_num": rng.choice([0, 1], size=100),
            "predicted_bad_probability": rng.uniform(0, 1, 100),
            "score": rng.uniform(300, 800, 100),
            "target": ["good"] * 90 + ["bad"] * 10,
        })
        from cardre.artifacts import write_json_artifact, write_parquet_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="proxy-sens", frame=df, metadata={},
        )
        # Create a model artifact that uses gender_num as a feature
        model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "decision_tree",
            "features": ["feat_a", "gender_num"],
            "model_payload": {"feature_importance": {"feat_a": 0.6, "gender_num": 0.4}},
            "interpretability": {"limitations": []},
            "warnings": [],
        }
        model_art = write_json_artifact(
            store, artifact_type="model", role="model",
            stem="proxy-model", payload=model, metadata={},
        )

        ctx = make_ctx(store, [data_art, model_art], "cardre.proxy_risk_report",
                       params={"sensitive_columns": ["gender_num"], "correlation_threshold": 0.3})
        out = ProxyRiskReportNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        # gender_num is directly in model features → high risk
        self.assertEqual(report["overall_risk"], "high")
        self.assertTrue(any(f["risk_level"] == "high" for f in report["proxy_flags"]))


# ======================================================================
# Phase 9: Alternative Data Manifest Tests
# ======================================================================

class AlternativeDataManifestParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = AlternativeDataManifestNode()
        errors = node.validate_params({
            "data_sources": [{
                "source_name": "telco",
                "consent_basis": "explicit_opt_in",
                "permitted_use": "credit_scoring",
            }],
        })
        self.assertEqual(errors, [])

    def test_missing_consent_basis(self) -> None:
        node = AlternativeDataManifestNode()
        errors = node.validate_params({
            "data_sources": [{
                "source_name": "telco",
                "permitted_use": "credit_scoring",
            }],
        })
        self.assertGreater(len(errors), 0)

    def test_missing_permitted_use(self) -> None:
        node = AlternativeDataManifestNode()
        errors = node.validate_params({
            "data_sources": [{
                "source_name": "telco",
                "consent_basis": "explicit_opt_in",
            }],
        })
        self.assertGreater(len(errors), 0)


class AlternativeDataManifestRunTests(unittest.TestCase):

    def test_manifest_with_valid_sources(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)

        ctx = make_ctx(store, [data_art, def_art], "cardre.alternative_data_manifest",
                       params={
                           "data_sources": [{
                               "source_name": "telco_data",
                               "source_type": "alternative",
                               "consent_basis": "explicit_opt_in",
                               "permitted_use": "credit_scoring",
                               "retention_policy": "2 years",
                               "columns": ["feat_a", "feat_b"],
                           }],
                       })
        out = AlternativeDataManifestNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertTrue(report["consent_verified"])
        self.assertTrue(report["all_use_permitted"])
        self.assertTrue(report["champion_eligible"])
        self.assertEqual(len(report["promotion_blocks"]), 0)

    def test_manifest_blocks_without_consent(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)

        ctx = make_ctx(store, [data_art, def_art], "cardre.alternative_data_manifest",
                       params={
                           "data_sources": [{
                               "source_name": "scraped_data",
                               "source_type": "alternative",
                               "consent_basis": "",
                               "permitted_use": "credit_scoring",
                           }],
                       })
        out = AlternativeDataManifestNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertFalse(report["consent_verified"])
        self.assertFalse(report["champion_eligible"])
        self.assertGreater(len(report["promotion_blocks"]), 0)

    def test_manifest_records_coverage(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_dataset_with_sensitive(store)

        ctx = make_ctx(store, [data_art, def_art], "cardre.alternative_data_manifest",
                       params={
                           "data_sources": [{
                               "source_name": "telco",
                               "consent_basis": "opt_in",
                               "permitted_use": "scoring",
                               "columns": ["feat_a", "feat_b"],
                           }],
                       })
        out = AlternativeDataManifestNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        source = report["data_sources"][0]
        self.assertIn("coverage", source)
        self.assertIn("missingness", source)
        self.assertGreater(source["coverage"].get("feat_a", 0), 0.9)


if __name__ == "__main__":
    unittest.main()
