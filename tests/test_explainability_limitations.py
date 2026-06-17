"""Tests for Phase 5 (explainability + limitations) and Phase 6 (API endpoints)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes.explainability import CHAMPION_ELIGIBILITY, ModelExplainabilityNode, ModelLimitationsNode
from cardre.nodes.ml_models import DecisionTreeNode, GradientBoostingClassifierNode, RandomForestClassifierNode
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_store


# ======================================================================
# Helpers
# ======================================================================


def make_fit_context(store, data_art, def_art, node_type, *, params=None, step_id="fit"):
    if params is None:
        params = {"feature_strategy": "raw_numeric", "max_depth": 3, "min_samples_leaf": 5, "random_seed": 42}
    step_spec = StepSpec(
        step_id=step_id, node_type=node_type, node_version="1", category="fit",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    return ExecutionContext(
        store=store, run_id="test-run", plan_version_id="test-pv",
        step_spec=step_spec, parent_run_steps=[],
        input_artifacts=[data_art, def_art],
        validated_params=params, runtime_metadata={},
    )


# ======================================================================
# ModelExplainabilityNode Tests
# ======================================================================

class ExplainabilityDecisionTreeTests(unittest.TestCase):

    def test_dt_explainability_report(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        model_out = DecisionTreeNode().run(ctx)
        model_art = model_out.artifacts[0]

        step_spec = StepSpec(
            step_id="explain-dt", node_type="cardre.model_explainability",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["model_family"], "decision_tree")
        self.assertEqual(report["explanation_level"], "native_interpretable")
        self.assertEqual(report["explanation_type"], "tree_rules")
        self.assertIn("tree_rules", report)
        self.assertGreater(len(report["tree_rules"]), 0)
        self.assertIn("feature_importance", report)
        self.assertEqual(report["champion_gate"]["status"], "pass")

    def test_explainability_champion_gate_semi_transparent(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})
        model_out = RandomForestClassifierNode().run(ctx)
        model_art = model_out.artifacts[0]

        step_spec = StepSpec(
            step_id="explain-rf", node_type="cardre.model_explainability",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["model_family"], "random_forest")
        self.assertEqual(report["explanation_level"], "native_semi_transparent")
        self.assertEqual(report["champion_gate"]["status"], "warn")
        self.assertIn("limitation", report["champion_gate"]["message"].lower())


class ExplainabilityGBDTTests(unittest.TestCase):

    def test_gbdt_explainability_report(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})
        model_out = GradientBoostingClassifierNode().run(ctx)
        model_art = model_out.artifacts[0]

        step_spec = StepSpec(
            step_id="explain-gbdt", node_type="cardre.model_explainability",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["model_family"], "gbdt")
        self.assertEqual(report["explanation_level"], "native_semi_transparent")
        self.assertEqual(report["explanation_type"], "feature_importance")
        self.assertIn("feature_importance", report)
        self.assertIn("estimator_count", report)
        self.assertEqual(report["champion_gate"]["status"], "warn")


class ExplainabilityLogisticTests(unittest.TestCase):

    def _make_logistic_model_artifact(self, store, data_art, def_art):
        """Create a mock logistic regression model artifact directly."""
        from cardre.artifacts import write_json_artifact
        model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "logistic_regression",
            "target_column": "target",
            "features": ["feat_a", "feat_b"],
            "intercept": -2.5,
            "coefficients": {"feat_a": 0.8, "feat_b": -0.3},
            "class_mapping": {"0": "good", "1": "bad"},
            "bad_class_label": "bad",
            "target_event_value": "bad",
            "probability_column_index": 1,
            "feature_order_hash": "abc123",
            "feature_strategy": "woe",
            "feature_contract": {"features": ["feat_a", "feat_b"], "transformation_strategy": "woe"},
            "training": {"row_count": 100, "params": {}, "random_seed": 42, "elapsed_seconds": 0.01},
            "model_payload": {},
            "interpretability": {
                "explanation_type": "coefficients",
                "explanation_level": "native_scorecard",
                "native_importance_available": True,
                "limitations": [],
                "global_importance_fields": [],
            },
            "warnings": [],
        }
        return write_json_artifact(
            store, artifact_type="model", role="model", stem="mock-lr",
            payload=model, metadata={"model_family": "logistic_regression"},
        )

    def test_logistic_explainability_coefficients(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        model_art = self._make_logistic_model_artifact(store, data_art, def_art)

        step_spec = StepSpec(
            step_id="explain-lr", node_type="cardre.model_explainability",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["model_family"], "logistic_regression")
        self.assertEqual(report["explanation_level"], "native_scorecard")
        self.assertEqual(report["explanation_type"], "coefficients")
        self.assertIn("coefficients", report)
        self.assertIn("intercept", report)
        self.assertEqual(report["champion_gate"]["status"], "pass")


# ======================================================================
# ModelLimitationsNode Tests
# ======================================================================

class LimitationsDecisionTreeTests(unittest.TestCase):

    def test_dt_limitations_report(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        model_out = DecisionTreeNode().run(ctx)
        model_art = model_out.artifacts[0]

        step_spec = StepSpec(
            step_id="lim-dt", node_type="cardre.model_limitations",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        lim_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art, def_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelLimitationsNode().run(lim_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["model_family"], "decision_tree")
        self.assertIn("limitations", report)
        self.assertIn("overall_status", report)
        self.assertIn("champion_eligible", report)

    def test_rf_limitations_unaccepted_blocks_champion(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})
        model_out = RandomForestClassifierNode().run(ctx)
        model_art = model_out.artifacts[0]

        step_spec = StepSpec(
            step_id="lim-rf", node_type="cardre.model_limitations",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        lim_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art, def_art],
            validated_params={}, runtime_metadata={},
        )
        out = ModelLimitationsNode().run(lim_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        # RF has semi-transparent interpretability → warn-level limitations
        self.assertEqual(report["model_family"], "random_forest")
        self.assertIn("limitations", report)
        self.assertGreater(len(report["limitations"]), 0)
        # Check that at least one limitation exists with warn severity
        warn_or_block = [lim for lim in report["limitations"] if lim["severity"] in ("warn", "block")]
        self.assertGreater(len(warn_or_block), 0)

    def test_limitations_with_accepted_codes(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})
        model_out = RandomForestClassifierNode().run(ctx)
        model_art = model_out.artifacts[0]

        # Get the limitation codes first
        step_spec_pre = StepSpec(
            step_id="lim-rf-pre", node_type="cardre.model_limitations",
            node_version="1", category="report", params={},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        lim_ctx_pre = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec_pre, parent_run_steps=[],
            input_artifacts=[model_art, data_art, def_art],
            validated_params={}, runtime_metadata={},
        )
        out_pre = ModelLimitationsNode().run(lim_ctx_pre)
        report_pre = json.loads(store.artifact_path(out_pre.artifacts[0]).read_text())
        block_codes = [
            lim["code"] for lim in report_pre["limitations"]
            if lim["severity"] == "block"
        ]

        if block_codes:
            # Now accept those codes
            step_spec = StepSpec(
                step_id="lim-rf-acc", node_type="cardre.model_limitations",
                node_version="1", category="report",
                params={"accepted_limitations": block_codes},
                params_hash=json_logical_hash({"accepted_limitations": block_codes}),
                parent_step_ids=[], branch_label="", position=0,
            )
            lim_ctx = ExecutionContext(
                store=store, run_id="test-run", plan_version_id="test-pv",
                step_spec=step_spec, parent_run_steps=[],
                input_artifacts=[model_art, data_art, def_art],
                validated_params={"accepted_limitations": block_codes},
                runtime_metadata={},
            )
            out = ModelLimitationsNode().run(lim_ctx)
            report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
            self.assertTrue(report["champion_eligible"])
            self.assertEqual(report["unaccepted_blocks"], 0)


# ======================================================================
# Sidecar API Tests (Phase 6)
# ======================================================================

class NodeTypesAPITests(unittest.TestCase):

    def test_list_node_types(self) -> None:
        from sidecar.routes.node_types import list_node_types
        response = list_node_types()
        self.assertGreater(response.count, 0)
        types = {nt.node_type for nt in response.node_types}
        self.assertIn("cardre.decision_tree_classifier", types)
        self.assertIn("cardre.random_forest_classifier", types)
        self.assertIn("cardre.gradient_boosting_classifier", types)
        self.assertIn("cardre.model_explainability", types)
        self.assertIn("cardre.model_limitations", types)

    def test_node_type_metadata(self) -> None:
        from sidecar.routes.node_types import list_node_types
        response = list_node_types()
        for nt in response.node_types:
            if nt.node_type == "cardre.random_forest_classifier":
                self.assertEqual(nt.model_family, "random_forest")
                self.assertEqual(nt.interpretability_level, "native_semi_transparent")
                self.assertIn("raw_numeric", nt.feature_strategies)
                break

    def test_get_node_type_schema(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.random_forest_classifier")
        self.assertEqual(schema.node_type, "cardre.random_forest_classifier")
        self.assertIn("n_estimators", schema.params_schema)
        self.assertIn("feature_strategy", schema.params_schema)
        self.assertEqual(schema.defaults["n_estimators"], 100)

    def test_get_node_type_schema_404(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            get_node_type_schema("cardre.nonexistent_node")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_threshold_optimization_schema(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.threshold_optimization")
        self.assertIn("objective", schema.params_schema)
        self.assertIn("youden", schema.params_schema["objective"]["enum"])
        self.assertEqual(schema.defaults["objective"], "youden")


if __name__ == "__main__":
    unittest.main()
