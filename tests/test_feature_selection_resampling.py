"""Tests for Phase 7: Feature selection + class-imbalance controls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes.feature_selection import (
    FeatureSelectionEmbeddedNode,
    FeatureSelectionFilterNode,
    ResampleTrainingDataNode,
    SmoteTrainingDataNode,
)
from cardre.store import ProjectStore


# ======================================================================
# Helpers
# ======================================================================

def make_store() -> tuple[ProjectStore, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_imbalanced_dataset(
    store: ProjectStore,
    n_good: int = 90,
    n_bad: int = 10,
    seed: int = 42,
) -> tuple:
    """Create an imbalanced dataset for testing resampling."""
    rng = np.random.RandomState(seed)
    feat_a = np.concatenate([rng.randn(n_good) * 5 + 20, rng.randn(n_bad) * 5 + 50])
    feat_b = np.concatenate([rng.randn(n_good) * 2 + 10, rng.randn(n_bad) * 2 + 30])
    feat_c = np.concatenate([rng.randn(n_good) * 1 + 5, rng.randn(n_bad) * 1 + 15])
    target = ["good"] * n_good + ["bad"] * n_bad

    df = pl.DataFrame({"feat_a": feat_a, "feat_b": feat_b, "feat_c": feat_c, "target": target})

    from cardre.artifacts import write_json_artifact, write_parquet_artifact
    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="imbalanced-train", frame=df, metadata={},
    )
    def_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="imbalanced-def",
        payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
        metadata={},
    )
    return data_art, def_art, df


def make_context(
    store, artifacts, node_type, *, params=None, step_id="step", category="selection",
):
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
# FeatureSelectionFilterNode Tests
# ======================================================================

class FeatureSelectionFilterParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = FeatureSelectionFilterNode()
        errors = node.validate_params({
            "min_iv": 0.02,
            "max_missingness": 0.5,
            "max_correlation": 0.85,
            "min_variance": 1e-6,
        })
        self.assertEqual(errors, [])

    def test_negative_min_iv(self) -> None:
        node = FeatureSelectionFilterNode()
        errors = node.validate_params({"min_iv": -0.1})
        self.assertGreater(len(errors), 0)

    def test_missingness_out_of_range(self) -> None:
        node = FeatureSelectionFilterNode()
        errors = node.validate_params({"max_missingness": 1.5})
        self.assertGreater(len(errors), 0)


class FeatureSelectionFilterRunTests(unittest.TestCase):

    def test_selects_features_above_iv_threshold(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_filter",
                           params={"min_iv": 0.0, "target_column": "target"})
        out = FeatureSelectionFilterNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        # After merge, selected is inside selection_filter
        selection_filter = report.get("selection_filter", report)
        self.assertIn("selected", selection_filter)
        self.assertGreater(selection_filter["selected_count"], 0)

    def test_rejects_high_missingness(self) -> None:
        store, tmp = make_store()
        rng = np.random.RandomState(42)
        df = pl.DataFrame({
            "good_feature": rng.randn(50),
            "bad_feature": [None] * 40 + rng.randn(10).tolist(),
            "target": ["good"] * 40 + ["bad"] * 10,
        })
        from cardre.artifacts import write_json_artifact, write_parquet_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="missing-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="missing-def",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={},
        )
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_filter",
                           params={"max_missingness": 0.3, "target_column": "target"})
        out = FeatureSelectionFilterNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        # After merge, rejected is inside selection_filter
        selection_filter = report.get("selection_filter", report)
        rejected_reasons = [r["reason"] for r in selection_filter.get("rejected", [])]
        self.assertTrue(any("Missingness" in r for r in rejected_reasons))

    def test_max_features_limits_selection(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_filter",
                           params={"min_iv": 0.0, "max_features": 2, "target_column": "target"})
        out = FeatureSelectionFilterNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        selection_filter = report.get("selection_filter", report)
        self.assertLessEqual(selection_filter["selected_count"], 2)


# ======================================================================
# FeatureSelectionEmbeddedNode Tests
# ======================================================================

class FeatureSelectionEmbeddedParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = FeatureSelectionEmbeddedNode()
        errors = node.validate_params({
            "importance_threshold": 0.01,
            "estimator": "decision_tree",
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_invalid_estimator(self) -> None:
        node = FeatureSelectionEmbeddedNode()
        errors = node.validate_params({"estimator": "svm"})
        self.assertGreater(len(errors), 0)


class FeatureSelectionEmbeddedRunTests(unittest.TestCase):

    def test_dt_embedded_selection(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_embedded",
                           params={"importance_threshold": 0.0, "estimator": "decision_tree"})
        out = FeatureSelectionEmbeddedNode().run(ctx)
        self.assertEqual(len(out.artifacts), 2)  # definition + report

        sel = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        self.assertIn("selected", sel)
        self.assertGreater(sel["selected_count"], 0)

        report = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertIn("feature_importance", report)
        self.assertEqual(report["estimator"], "decision_tree")

    def test_rf_embedded_selection(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_embedded",
                           params={"importance_threshold": 0.0, "estimator": "random_forest"})
        out = FeatureSelectionEmbeddedNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertEqual(report["estimator"], "random_forest")

    def test_max_features_limits_embedded(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)
        ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_embedded",
                           params={"importance_threshold": 0.0, "max_features": 1})
        out = FeatureSelectionEmbeddedNode().run(ctx)
        sel = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        self.assertLessEqual(sel["selected_count"], 1)


# ======================================================================
# ResampleTrainingDataNode Tests
# ======================================================================

class ResampleTrainingDataParameterTests(unittest.TestCase):

    def test_valid_combined(self) -> None:
        node = ResampleTrainingDataNode()
        errors = node.validate_params({"strategy": "combined", "sampling_ratio": 1.0})
        self.assertEqual(errors, [])

    def test_valid_undersample(self) -> None:
        node = ResampleTrainingDataNode()
        errors = node.validate_params({"strategy": "undersample_majority"})
        self.assertEqual(errors, [])

    def test_valid_oversample(self) -> None:
        node = ResampleTrainingDataNode()
        errors = node.validate_params({"strategy": "oversample_minority"})
        self.assertEqual(errors, [])

    def test_invalid_strategy(self) -> None:
        node = ResampleTrainingDataNode()
        errors = node.validate_params({"strategy": "invalid"})
        self.assertGreater(len(errors), 0)


class ResampleTrainingDataRunTests(unittest.TestCase):

    def test_undersample_reduces_majority(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=90, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.resample_training_data",
                           params={"strategy": "undersample_majority", "sampling_ratio": 0.5},
                           category="transform")
        out = ResampleTrainingDataNode().run(ctx)
        report_art = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertLess(report_art["resampled"]["good"], report_art["original"]["good"])

    def test_oversample_increases_minority(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=90, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.resample_training_data",
                           params={"strategy": "oversample_minority", "sampling_ratio": 1.0},
                           category="transform")
        out = ResampleTrainingDataNode().run(ctx)
        report_art = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertGreater(report_art["resampled"]["bad"], report_art["original"]["bad"])

    def test_synthetic_rows_flagged(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=50, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.resample_training_data",
                           params={"strategy": "oversample_minority", "sampling_ratio": 1.0},
                           category="transform")
        out = ResampleTrainingDataNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertGreater(report["synthetic_rows_added"], 0)

    def test_single_class_raises(self) -> None:
        store, tmp = make_store()
        df = pl.DataFrame({
            "feat_a": [1.0] * 50,
            "target": ["good"] * 50,
        })
        from cardre.artifacts import write_json_artifact, write_parquet_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="single-class", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="single-class-def",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={},
        )
        ctx = make_context(store, [data_art, def_art], "cardre.resample_training_data",
                           params={"strategy": "combined"}, category="transform")
        with self.assertRaises(ValueError):
            ResampleTrainingDataNode().run(ctx)

    def test_resampled_data_trains_model(self) -> None:
        """Verify resampled data can train a decision tree."""
        from cardre.nodes.ml_models import DecisionTreeNode
        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=50, n_bad=10)

        # Resample first
        res_ctx = make_context(store, [data_art, def_art], "cardre.resample_training_data",
                               params={"strategy": "oversample_minority", "sampling_ratio": 1.0},
                               category="transform")
        res_out = ResampleTrainingDataNode().run(res_ctx)
        resampled_art = res_out.artifacts[0]

        # Fit model on resampled data
        dt_ctx = make_context(store, [resampled_art, def_art], "cardre.decision_tree_classifier",
                              params={"feature_strategy": "raw_numeric", "max_depth": 3, "random_seed": 42},
                              step_id="dt-fit", category="fit")
        dt_out = DecisionTreeNode().run(dt_ctx)
        model = json.loads(store.artifact_path(dt_out.artifacts[0]).read_text())
        self.assertEqual(model["model_family"], "decision_tree")


# ======================================================================
# SmoteTrainingDataNode Tests
# ======================================================================

class SmoteTrainingDataParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = SmoteTrainingDataNode()
        errors = node.validate_params({
            "k_neighbors": 5,
            "sampling_ratio": 1.0,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_k_neighbors_zero(self) -> None:
        node = SmoteTrainingDataNode()
        errors = node.validate_params({"k_neighbors": 0})
        self.assertGreater(len(errors), 0)


class SmoteTrainingDataRunTests(unittest.TestCase):

    def test_smote_increases_minority(self) -> None:
        try:
            from imblearn.over_sampling import SMOTE  # noqa: F401
        except ImportError:
            self.skipTest("imbalanced-learn not installed")

        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=50, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.smote_training_data",
                           params={"k_neighbors": 3, "sampling_ratio": 1.0},
                           category="transform")
        out = SmoteTrainingDataNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertGreater(report["resampled"]["bad"], report["original"]["bad"])
        self.assertGreater(report["synthetic_rows_added"], 0)

    def test_smote_synthetic_flagged(self) -> None:
        try:
            from imblearn.over_sampling import SMOTE  # noqa: F401
        except ImportError:
            self.skipTest("imbalanced-learn not installed")

        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=50, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.smote_training_data",
                           params={"k_neighbors": 3, "sampling_ratio": 1.0},
                           category="transform")
        out = SmoteTrainingDataNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[1]).read_text())
        self.assertGreater(report["synthetic_rows_added"], 0)

    def test_smote_import_error(self) -> None:
        """Test that missing imbalanced-learn gives clear error."""
        import unittest.mock
        import sys

        # Temporarily remove imblearn from import path
        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "imblearn.over_sampling":
                raise ImportError("No module named 'imblearn'")
            return real_import(name, *args, **kwargs)

        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store, n_good=50, n_bad=10)
        ctx = make_context(store, [data_art, def_art], "cardre.smote_training_data",
                           params={"k_neighbors": 3}, category="transform")

        with unittest.mock.patch("builtins.__import__", side_effect=mock_import):
            with self.assertRaises(ImportError) as cm:
                SmoteTrainingDataNode().run(ctx)
            self.assertIn("imbalanced-learn", str(cm.exception))


# ======================================================================
# Integration: Filter → Model pipeline
# ======================================================================

class FeatureSelectionIntegrationTests(unittest.TestCase):

    def test_filter_then_fit_decision_tree(self) -> None:
        """Verify filter selection output can be used as model input."""
        from cardre.nodes.ml_models import DecisionTreeNode

        store, tmp = make_store()
        data_art, def_art, _ = make_imbalanced_dataset(store)

        # Filter selection
        filter_ctx = make_context(store, [data_art, def_art], "cardre.feature_selection_filter",
                                  params={"min_iv": 0.0, "target_column": "target"})
        filter_out = FeatureSelectionFilterNode().run(filter_ctx)
        sel_art = filter_out.artifacts[0]

        # Fit decision tree with selected features
        dt_ctx = make_context(store, [data_art, sel_art], "cardre.decision_tree_classifier",
                              params={"feature_strategy": "raw_numeric", "max_depth": 3, "random_seed": 42},
                              step_id="dt-fit", category="fit")
        dt_out = DecisionTreeNode().run(dt_ctx)
        model = json.loads(store.artifact_path(dt_out.artifacts[0]).read_text())
        self.assertEqual(model["model_family"], "decision_tree")
        self.assertGreater(len(model["features"]), 0)


if __name__ == "__main__":
    unittest.main()
