"""Tests for Phase 2: Decision Tree Challenger."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.ml_models import DecisionTreeNode
from cardre.nodes.validate import ApplyModelNode, ValidationMetricsNode
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_oot_dataset, make_store
import pytest

pytestmark = pytest.mark.integration



# ======================================================================
# Helpers
# ======================================================================


def make_dt_context(
    store: ProjectStore,
    data_art,
    def_art,
    *,
    params: dict | None = None,
    run_id: str = "test-run",
    step_id: str = "dt-fit",
) -> ExecutionContext:
    if params is None:
        params = {
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "min_samples_leaf": 5,
            "random_seed": 42,
        }
    step_spec = StepSpec(
        step_id=step_id,
        node_type="cardre.decision_tree_classifier",
        node_version="1",
        category="fit",
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    return ExecutionContext(
        store=store,
        run_id=run_id,
        plan_version_id="test-pv",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[data_art, def_art],
        validated_params=params,
        runtime_metadata={},
    )


# ======================================================================
# Parameter Validation
# ======================================================================

class DecisionTreeParameterTests:

    def test_valid_params(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "min_samples_leaf": 5,
            "random_seed": 42,
        })
        assert errors == []

    def test_invalid_feature_strategy(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "invalid"})
        assert len(errors) > 0
        assert any("feature_strategy" in e for e in errors)

    def test_max_depth_zero(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "max_depth": 0})
        assert len(errors) > 0

    def test_min_samples_leaf_zero(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "min_samples_leaf": 0})
        assert len(errors) > 0

    def test_valid_balanced_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "balanced",
        })
        assert errors == []

    def test_valid_dict_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": {0: 1, 1: 5},
        })
        assert errors == []

    def test_invalid_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "invalid",
        })
        assert len(errors) > 0


# ======================================================================
# Core Fitting
# ======================================================================

class DecisionTreeFitTests:

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        assert len(output.artifacts) == 2
        model_art = output.artifacts[0]
        assert model_art.artifact_type == "model"
        assert model_art.role == "model"

        model = json.loads(store.artifact_path(model_art).read_text())
        assert model["schema_version"] == "cardre.model_artifact.v1"
        assert model["model_family"] == "decision_tree"

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        errors = validate_model_artifact(model)
        assert errors == []

    def test_fit_produces_estimator_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        estimator_art = output.artifacts[1]
        assert estimator_art.artifact_type == "estimator"
        assert store.artifact_path(estimator_art).exists()

    def test_fit_exports_tree_rules(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        rules = model["model_payload"]["tree_rules"]
        assert isinstance(rules, list)
        assert len(rules) > 0

        for rule in rules:
            assert "rule_id" in rule
            assert "prediction" in rule
            assert "probability" in rule
            assert "conditions" in rule
            assert "sample_count" in rule

    def test_fit_records_tree_depth_and_leaf_count(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert "tree_depth" in model["model_payload"]
        assert "leaf_count" in model["model_payload"]
        assert model["model_payload"]["tree_depth"] > 0
        assert model["model_payload"]["leaf_count"] > 0

    def test_fit_records_feature_importance(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        importance = model["model_payload"]["feature_importance"]
        assert isinstance(importance, dict)
        assert len(importance) > 0

    def test_fit_records_interpretability_metadata(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        interp = model["interpretability"]
        assert interp["explanation_type"] == "tree_rules"
        assert interp["explanation_level"] == "native_interpretable"
        assert interp["native_importance_available"]

    def test_fit_records_estimator_reference(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        ref = model["estimator_reference"]
        assert ref["artifact_id"]
        assert ref["logical_hash"]
        assert ref["physical_hash"]
        assert ref["estimator_format"] == "joblib"
        assert ref["trusted_load_required"]

    def test_fit_records_class_mapping(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert "class_mapping" in model
        assert "target_event_value" in model
        assert model["target_event_value"] == "bad"

    def test_fit_records_feature_strategy(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert model["feature_strategy"] == "raw_numeric"


# ======================================================================
# Error Handling
# ======================================================================

class DecisionTreeErrorTests:

    def test_rejects_non_numeric_columns(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "category": ["a", "b", "c", "d", "e"] * 20,
            "target": ["good", "bad", "good", "bad", "good"] * 20,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="cat-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="cat-def",
            payload={
                "target_column": "target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with pytest.raises(ValueError) as ctx_mgr:
            node.run(ctx)
        assert "Non-numeric" in str(ctx_mgr.value)

    def test_rejects_missing_target_column(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "feat_b": [5.0, 4.0, 3.0, 2.0, 1.0] * 20,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="no-target-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="no-target-def",
            payload={
                "target_column": "missing_target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with pytest.raises(ValueError):
            node.run(ctx)

    def test_rejects_single_class(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "target": ["good"] * 100,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="single-class-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="single-class-def",
            payload={
                "target_column": "target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with pytest.raises(ValueError) as ctx_mgr:
            node.run(ctx)
        assert "bad-class" in str(ctx_mgr.value)

    def test_include_columns_works(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "include_columns": ["feat_a", "feat_b"],
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert model["features"] == ["feat_a", "feat_b"]

    def test_exclude_columns_works(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "exclude_columns": ["feat_c"],
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert "feat_c" not in model["features"]

    def test_max_depth_controls_tree(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store, n_rows=200)

        ctx_shallow = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output_shallow = node.run(ctx_shallow)

        model_shallow = json.loads(store.artifact_path(output_shallow.artifacts[0]).read_text())
        assert model_shallow["model_payload"]["tree_depth"] <= 2


# ======================================================================
# Integration with ApplyModelNode
# ======================================================================

class DecisionTreeApplyTests:

    def test_apply_model_with_decision_tree(self) -> None:
        """Verify ApplyModelNode can apply a decision tree model."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        # Fit decision tree
        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)

        model_art = dt_output.artifacts[0]
        estimator_art = dt_output.artifacts[1]

        # Create scored datasets using ApplyModelNode
        step_spec = StepSpec(
            step_id="dt-apply",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )

        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)

        assert len(apply_output.artifacts) == 2  # dataset + evidence
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        assert "predicted_bad_probability" in scored_df.columns
        assert "model_artifact_id" in scored_df.columns
        assert "model_family" in scored_df.columns
        assert scored_df["model_family"][0] == "decision_tree"

    def test_apply_produces_valid_probabilities(self) -> None:
        """Verify predicted probabilities are between 0 and 1."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)

        model_art = dt_output.artifacts[0]

        step_spec = StepSpec(
            step_id="dt-apply-2",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )

        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)

        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        probs = scored_df["predicted_bad_probability"].to_list()
        for p in probs:
            assert p >= 0.0
            assert p <= 1.0


# ======================================================================
# Integration with ValidationMetricsNode
# ======================================================================

class DecisionTreeValidationTests:

    def test_validation_metrics_with_decision_tree(self) -> None:
        """Verify ValidationMetricsNode works with decision tree scored data."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        # Fit decision tree
        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)
        model_art = dt_output.artifacts[0]

        # Apply model
        apply_spec = StepSpec(
            step_id="dt-apply-val",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=apply_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )
        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)
        scored_art = apply_output.artifacts[0]

        # Add a synthetic score column since decision tree doesn't produce one
        scored_df = pl.read_parquet(store.artifact_path(scored_art))
        # Score from probability: higher probability = lower score
        score_vals = (1.0 - scored_df["predicted_bad_probability"]) * 1000
        scored_df = scored_df.with_columns(pl.Series("score", score_vals, dtype=pl.Float64))

        from cardre.artifacts import write_parquet_artifact
        scored_with_score = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="scored-with-score", frame=scored_df, metadata={},
        )

        # Validation metrics
        val_spec = StepSpec(
            step_id="dt-validation",
            node_type="cardre.validation_metrics",
            node_version="1",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        val_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=val_spec,
            parent_run_steps=[],
            input_artifacts=[scored_with_score, def_art],
            validated_params={},
            runtime_metadata={},
        )
        val_node = ValidationMetricsNode()
        val_output = val_node.run(val_ctx)

        report = json.loads(store.artifact_path(val_output.artifacts[0]).read_text())
        assert "roles" in report
        train_metrics = report["roles"]["train"]
        assert "auc" in train_metrics
        assert train_metrics["auc"] is not None


# ======================================================================
# Determinism
# ======================================================================

class DecisionTreeDeterminismTests:

    def test_same_seed_produces_same_artifacts(self) -> None:
        """Verify deterministic output with same random seed."""
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_dt_context(store, data_art, def_art, run_id="run-1", step_id="dt-1")
        node1 = DecisionTreeNode()
        out1 = node1.run(ctx1)

        ctx2 = make_dt_context(store, data_art, def_art, run_id="run-2", step_id="dt-2")
        node2 = DecisionTreeNode()
        out2 = node2.run(ctx2)

        model1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        model2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())

        assert model1["model_payload"]["tree_rules"] == model2["model_payload"]["tree_rules"]
        assert model1["model_payload"]["tree_depth"] == model2["model_payload"]["tree_depth"]
        assert model1["model_payload"]["leaf_count"] == model2["model_payload"]["leaf_count"]
