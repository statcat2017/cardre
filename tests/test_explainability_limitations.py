"""Tests for Phase 5 (explainability + limitations) and Phase 6 (API endpoints)."""

from __future__ import annotations

import json
import os

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes.explainability import ModelExplainabilityNode, ModelLimitationsNode
from cardre.nodes.ml_models import DecisionTreeNode, GradientBoostingClassifierNode, RandomForestClassifierNode

from tests.helpers import make_numeric_dataset, make_store
import pytest

_LAUNCH_MODE = os.environ.get("CARDRE_LAUNCH_MODE", "1").strip().lower() in ("1", "true")
_skip_if_launch = pytest.mark.skipif(_LAUNCH_MODE, reason="GBDT is deferred at launch simplification")

pytestmark = pytest.mark.integration



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

class ExplainabilityDecisionTreeTests:

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

        assert report["model_family"] == "decision_tree"
        assert report["explanation_level"] == "native_interpretable"
        assert report["explanation_type"] == "tree_rules"
        assert "tree_rules" in report
        assert len(report["tree_rules"]) > 0
        assert "feature_importance" in report
        assert report["champion_gate"]["status"] == "pass"

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

        assert report["model_family"] == "random_forest"
        assert report["explanation_level"] == "native_semi_transparent"
        assert report["champion_gate"]["status"] == "warn"
        assert "limitation" in report["champion_gate"]["message"].lower()

    def test_explainability_requires_typed_model_evidence(self) -> None:
        store, tmp = make_store()
        data_art, _, _ = make_numeric_dataset(store)
        from cardre.artifacts import write_json_artifact

        model_art = write_json_artifact(
            store,
            artifact_type="model",
            role="model",
            stem="bad-model",
            payload={
                "target_column": "target",
                "features": ["feat_a", "feat_b"],
                "intercept": -1.0,
                "coefficients": {"feat_a": 0.4, "feat_b": -0.2},
            },
            metadata={"schema_version": "cardre.not_a_model_schema.v1"},
        )

        step_spec = StepSpec(
            step_id="explain-bad-model",
            node_type="cardre.model_explainability",
            node_version="1",
            category="report",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        exp_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[model_art, data_art],
            validated_params={},
            runtime_metadata={},
        )

        out = ModelExplainabilityNode().run(exp_ctx)
        assert len(out.artifacts) > 0
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        assert report.get("model_family") is not None


@_skip_if_launch
class ExplainabilityGBDTTests:

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

        assert report["model_family"] == "gbdt"
        assert report["explanation_level"] == "native_semi_transparent"
        assert report["explanation_type"] == "feature_importance"
        assert "feature_importance" in report
        assert "estimator_count" in report
        assert report["champion_gate"]["status"] == "warn"


class ExplainabilityPermutationDataRoleTests:

    def _make_test_data_artifact(self, store):
        rng = np.random.RandomState(99)
        df = pl.DataFrame({
            "feat_a": rng.randn(20) * 10 + 50,
            "feat_b": rng.randn(20) * 5 + 20,
            "feat_c": rng.randn(20) * 2 + 10,
            "target": ["bad" if rng.rand() > 0.6 else "good" for _ in range(20)],
        })
        from cardre.artifacts import write_parquet_artifact
        return write_parquet_artifact(
            store, artifact_type="dataset", role="test",
            stem="synthetic-test", frame=df, metadata={},
        )

    def test_permutation_importance_with_test_data_role(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        model_out = DecisionTreeNode().run(ctx)
        model_art = model_out.artifacts[0]

        test_art = self._make_test_data_artifact(store)

        step_spec = StepSpec(
            step_id="explain-dt-perm-test",
            node_type="cardre.model_explainability",
            node_version="1", category="report",
            params={"include_permutation_importance": True, "permutation_data_role": "test"},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art, test_art],
            validated_params={"include_permutation_importance": True, "permutation_data_role": "test"},
            runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        assert "permutation_importance" in report
        assert report["permutation_importance"]["data_role"] == "test"
        assert "importance_mean" in report["permutation_importance"]

    def test_permutation_importance_with_oot_data_role(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        model_out = DecisionTreeNode().run(ctx)
        model_art = model_out.artifacts[0]

        from tests.helpers import make_oot_dataset
        _, _, oot_df = make_numeric_dataset(store, n_rows=30, seed=99)
        oot_art, _ = make_oot_dataset(store, oot_df)

        step_spec = StepSpec(
            step_id="explain-dt-perm-oot",
            node_type="cardre.model_explainability",
            node_version="1", category="report",
            params={"include_permutation_importance": True, "permutation_data_role": "oot"},
            params_hash=json_logical_hash({}), parent_step_ids=[],
            branch_label="", position=0,
        )
        exp_ctx = ExecutionContext(
            store=store, run_id="test-run", plan_version_id="test-pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[model_art, data_art, oot_art],
            validated_params={"include_permutation_importance": True, "permutation_data_role": "oot"},
            runtime_metadata={},
        )
        out = ModelExplainabilityNode().run(exp_ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        assert "permutation_importance" in report
        assert report["permutation_importance"]["data_role"] == "oot"


class ExplainabilityLogisticTests:

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

        assert report["model_family"] == "logistic_regression"
        assert report["explanation_level"] == "native_scorecard"
        assert report["explanation_type"] == "coefficients"
        assert "coefficients" in report
        assert "intercept" in report
        assert report["champion_gate"]["status"] == "pass"


# ======================================================================
# ModelLimitationsNode Tests
# ======================================================================

class LimitationsDecisionTreeTests:

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

        assert report["model_family"] == "decision_tree"
        assert "limitations" in report
        assert "overall_status" in report
        assert "champion_eligible" in report

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
        assert report["model_family"] == "random_forest"
        assert "limitations" in report
        assert len(report["limitations"]) > 0
        # Check that at least one limitation exists with warn severity
        warn_or_block = [lim for lim in report["limitations"] if lim["severity"] in ("warn", "block")]
        assert len(warn_or_block) > 0

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
            assert report["champion_eligible"]
            assert report["unaccepted_blocks"] == 0


# ======================================================================
# Sidecar API Tests (Phase 6)
# ======================================================================

class NodeTypesAPITests:

    def test_list_node_types(self) -> None:
        from sidecar.routes.node_types import list_node_types
        response = list_node_types()
        assert response.count > 0
        types = {nt.node_type for nt in response.node_types}
        assert "cardre.decision_tree_classifier" in types
        assert "cardre.random_forest_classifier" in types
        assert "cardre.gradient_boosting_classifier" in types
        assert "cardre.model_explainability" in types
        assert "cardre.model_limitations" in types

    def test_node_type_metadata(self) -> None:
        from sidecar.routes.node_types import list_node_types
        response = list_node_types()
        for nt in response.node_types:
            if nt.node_type == "cardre.random_forest_classifier":
                assert nt.model_family == "random_forest"
                assert nt.interpretability_level == "native_semi_transparent"
                assert "raw_numeric" in nt.feature_strategies
                break

    def test_get_node_type_schema(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.random_forest_classifier")
        assert schema.node_type == "cardre.random_forest_classifier"
        assert "n_estimators" in schema.params_schema
        assert "feature_strategy" in schema.params_schema
        assert schema.defaults["n_estimators"] == 100

    def test_get_node_type_schema_404(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ctx:
            get_node_type_schema("cardre.nonexistent_node")
        assert ctx.value.status_code == 404

    def test_threshold_optimization_schema(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.threshold_optimization")
        assert "objective" in schema.params_schema
        assert "youden" in schema.params_schema["objective"]["enum"]
        assert schema.defaults["objective"] == "youden"

    def test_hyperparameter_tuning_listed(self) -> None:
        from sidecar.routes.node_types import list_node_types
        response = list_node_types()
        types = {nt.node_type for nt in response.node_types}
        assert "cardre.hyperparameter_tuning" in types

    def test_hyperparameter_tuning_schema(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.hyperparameter_tuning")
        assert schema.node_type == "cardre.hyperparameter_tuning"
        assert "estimator_type" in schema.params_schema
        assert "search_method" in schema.params_schema
        assert "param_grid" in schema.params_schema
        assert "cv_folds" in schema.params_schema
        assert schema.params_schema["cv_folds"]["minimum"] == 2
        assert schema.params_schema["estimator_type"]["enum"] == ["decision_tree", "random_forest", "gbdt", "logistic_regression"]

    def test_hyperparameter_tuning_schema_has_enum(self) -> None:
        from sidecar.routes.node_types import get_node_type_schema
        schema = get_node_type_schema("cardre.hyperparameter_tuning")
        assert "grid" in schema.params_schema["search_method"]["enum"]
        assert "randomized" in schema.params_schema["search_method"]["enum"]
