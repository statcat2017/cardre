"""Tests for scorecard model fitting, scoring, and end-to-end pathways."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.executor import PlanExecutor
from cardre.nodes import (
    ApplyModelNode,
    BuildSummaryReportNode,
    CalculateWoeIvNode,
    FineClassingNode,
    LogisticRegressionNode,
    ManualBinningNode,
    ScoreScalingNode,
    WoeTransformTrainNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

import pytest

from tests.helpers import (
    SAMPLE_GERMAN_CREDIT_LINES,
    _make_json_artifact,
    _make_parquet_report,
    _make_train_artifact,
    make_store,
)

pytestmark = pytest.mark.integration



def make_full_german_credit_download(tmp: Path) -> Path:
    """Create a larger German Credit fixture with 10 rows for more meaningful testing."""
    lines = SAMPLE_GERMAN_CREDIT_LINES * 5
    p = tmp / "german_full.data"
    p.write_text("\n".join(lines))
    return p


# ======================================================================
# Workstream 12: End-to-End Scorecard Pathway Test
# ======================================================================


    def test_full_phase2a_pathway_import_through_manifest(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "scorecard-test")
        source = make_full_german_credit_download(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_fixture_uci_german_credit",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="define-metadata", node_type="cardre.define_modelling_metadata",
                node_version="1", category="transform",
                params={
                    "target_column": "credit_risk_class",
                    "good_values": ["1"], "bad_values": ["2"],
                    "indeterminate_values": [], "population": "",
                    "product": "", "segment": "",
                    "observation_window": None, "performance_window": None,
                },
                params_hash=json_logical_hash({
                    "target_column": "credit_risk_class",
                    "good_values": ["1"], "bad_values": ["2"],
                    "indeterminate_values": [], "population": "",
                    "product": "", "segment": "",
                    "observation_window": None, "performance_window": None,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="apply-exclusions", node_type="cardre.apply_exclusions",
                node_version="1", category="transform",
                params={"rules": []},
                params_hash=json_logical_hash({"rules": []}),
                parent_step_ids=["import", "define-metadata"], branch_label="", position=2,
            ),
            StepSpec(
                step_id="profile", node_type="cardre.profile_dataset",
                node_version="1", category="transform",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["apply-exclusions"], branch_label="", position=3,
            ),
            StepSpec(
                step_id="validate-target", node_type="cardre.validate_binary_target",
                node_version="1", category="transform",
                params={"target_column": "credit_risk_class"},
                params_hash=json_logical_hash({"target_column": "credit_risk_class"}),
                parent_step_ids=["apply-exclusions", "define-metadata"], branch_label="", position=4,
            ),
            StepSpec(
                step_id="sample-definition", node_type="cardre.development_sample_definition",
                node_version="1", category="transform",
                params={
                    "sample_method": "full_population",
                    "weight_column": None, "population_bad_rate": None,
                    "prior_probability_adjustment": None,
                },
                params_hash=json_logical_hash({
                    "sample_method": "full_population",
                    "weight_column": None, "population_bad_rate": None,
                    "prior_probability_adjustment": None,
                }),
                parent_step_ids=["apply-exclusions", "define-metadata"], branch_label="", position=5,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="2", category="transform",
                params={
                    "strategy": "random_stratified",
                    "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                    "target_column": "credit_risk_class", "role_column": None,
                    "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "strategy": "random_stratified",
                    "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                    "target_column": "credit_risk_class", "role_column": None,
                    "random_seed": 42,
                }),
                parent_step_ids=["apply-exclusions", "sample-definition"], branch_label="", position=6,
            ),
            StepSpec(
                step_id="explicit-missing-outlier-treatment",
                node_type="cardre.explicit_missing_outlier_treatment",
                node_version="1", category="apply",
                params={"imputations": {}, "caps": {}, "floors": {}},
                params_hash=json_logical_hash({"imputations": {}, "caps": {}, "floors": {}}),
                parent_step_ids=["split"], branch_label="", position=7,
            ),
            StepSpec(
                step_id="binning", node_type="cardre.binning",
                node_version="1", category="fit",
                params={
                    "method": "fine_classing",
                    "max_bins": 20, "min_bin_fraction": 0.05,
                    "missing_policy": "separate_bin",
                    "max_categorical_levels": 50, "exclude_columns": [],
                },
                params_hash=json_logical_hash({
                    "method": "fine_classing",
                    "max_bins": 20, "min_bin_fraction": 0.05,
                    "missing_policy": "separate_bin",
                    "max_categorical_levels": 50, "exclude_columns": [],
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "define-metadata"],
                branch_label="", position=8,
            ),
            StepSpec(
                step_id="initial-woe-iv", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={
                    "zero_cell_policy": "block", "smoothing": None, "purpose": "initial",
                },
                params_hash=json_logical_hash({
                    "zero_cell_policy": "block", "smoothing": None, "purpose": "initial",
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "binning", "define-metadata"],
                branch_label="", position=9,
            ),
            StepSpec(
                step_id="variable-clustering", node_type="cardre.variable_clustering",
                node_version="1", category="selection",
                params={"method": "correlation_threshold", "threshold": 0.7, "candidate_limit": 50},
                params_hash=json_logical_hash({"method": "correlation_threshold", "threshold": 0.7, "candidate_limit": 50}),
                parent_step_ids=["explicit-missing-outlier-treatment", "initial-woe-iv"],
                branch_label="", position=10,
            ),
            StepSpec(
                step_id="variable-selection", node_type="cardre.variable_selection",
                node_version="1", category="selection",
                params={
                    "min_iv": 0.02, "max_variables": 15,
                    "manual_includes": [], "manual_excludes": [],
                },
                params_hash=json_logical_hash({
                    "min_iv": 0.02, "max_variables": 15,
                    "manual_includes": [], "manual_excludes": [],
                }),
                parent_step_ids=["initial-woe-iv", "variable-clustering"],
                branch_label="", position=11,
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["binning", "variable-selection"],
                branch_label="", position=12,
            ),
            StepSpec(
                step_id="final-woe-iv", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={
                    "zero_cell_policy": "block",
                    "smoothing": {
                        "method": "additive",
                        "alpha": 0.5,
                        "rationale": "Small sample test fixture with sparse bins",
                    },
                    "purpose": "final",
                },
                params_hash=json_logical_hash({
                    "zero_cell_policy": "block",
                    "smoothing": {
                        "method": "additive",
                        "alpha": 0.5,
                        "rationale": "Small sample test fixture with sparse bins",
                    },
                    "purpose": "final",
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"],
                branch_label="", position=13,
            ),
            StepSpec(
                step_id="technical-manifest-stub",
                node_type="cardre.technical_manifest_export",
                node_version="1", category="transform",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=[
                    "define-metadata", "sample-definition", "split",
                    "explicit-missing-outlier-treatment", "binning",
                    "variable-selection", "manual-binning", "final-woe-iv",
                ],
                branch_label="", position=14,
            ),
        ]

        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(store, pv_id)


        run_steps = store.get_run_steps(run_id)
        run_steps_by_id = {rs.step_id: rs for rs in run_steps}

        # Verify all steps succeeded
        for step in steps:
            rs = run_steps_by_id.get(step.step_id)
            self.assertIsNotNone(rs, f"No run step for {step.step_id}")
            self.assertEqual(
                rs.status, "succeeded",
                f"Step {step.step_id} failed: {rs.errors}",
            )

        # Verify key artifacts exist
        artifact_types_by_step = {
            "define-metadata": "definition",
            "binning": "definition",
            "variable-selection": "definition",
            "manual-binning": "definition",
            "technical-manifest-stub": "manifest",
        }
        for step_id, expected_type in artifact_types_by_step.items():
            rs = run_steps_by_id[step_id]
            for aid in rs.output_artifact_ids:
                art = store.get_artifact(aid)
                if art and art.artifact_type == expected_type:
                    break
            else:
                self.fail(f"No {expected_type} artifact found for step {step_id}")

        # Verify initial and final WOE/IV produce report artifacts
        for woe_step in ("initial-woe-iv", "final-woe-iv"):
            rs = run_steps_by_id[woe_step]
            report_found = any(
                store.get_artifact(aid) and store.get_artifact(aid).artifact_type == "report"
                for aid in rs.output_artifact_ids
            )
            self.assertTrue(report_found, f"No report artifact for {woe_step}")


# ======================================================================
# Logistic Regression
# ======================================================================

class LogisticRegressionTests:

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

        assert len(output.artifacts) == 1
        artifact = output.artifacts[0]
        assert artifact.artifact_type == "model"
        assert artifact.role == "model"

        model = json.loads(store.artifact_path(artifact).read_text())
        assert "features" in model
        assert "coefficients" in model
        assert "intercept" in model
        assert "class_mapping" in model
        assert model["class_mapping"]["bad"] == "bad"
        assert "training" in model
        assert model["training"]["converged"]

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
        with pytest.raises(ValueError):
            node.run(ctx)


# ======================================================================
# Score Scaling
# ======================================================================

class ScoreScalingTests:

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

        assert len(output.artifacts) == 1
        artifact = output.artifacts[0]
        assert artifact.artifact_type == "scorecard"
        scorecard = json.loads(store.artifact_path(artifact).read_text())
        assert "attributes" in scorecard
        assert "base_points" in scorecard
        assert scorecard["base_points"] > 0

        factor = 20 / math.log(2)
        offset = 600 - factor * math.log(50)
        intercept = -0.5
        direction = -1.0  # higher_score_is_lower_risk=True
        # base_points = offset + direction * factor * intercept
        expected_base = round(offset + direction * factor * intercept, 2)
        assert scorecard["base_points"] == pytest.approx(expected_base, abs=0.1)

        # Parity: score for any row should equal offset + direction * factor * (intercept + sum(coef * woe))
        coef_x = 0.8
        woe_low = 0.3
        expected_score_low = round(offset + direction * factor * (intercept + coef_x * woe_low), 2)
        attr_low = next(a for a in scorecard["attributes"] if a["bin_id"] == "x_b1")
        computed_score = scorecard["base_points"] + attr_low["points"]
        assert computed_score == pytest.approx(expected_score_low, abs=0.1)

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
        with pytest.raises(ValueError):
            node.run(ctx)


# ======================================================================
# Phase 2B End-to-End Through Executor
# ======================================================================

class Phase2BEndToEndTests:
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
            "method": "fine_classing",
            "max_bins": 5, "min_bin_fraction": 0.01,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 50, "exclude_columns": [],
        }
        fine_spec = StepSpec(
            step_id="binning", node_type="cardre.binning",
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
        assert lr_output.artifacts[0].artifact_type == "model"
        assert ss_output.artifacts[0].artifact_type == "scorecard"
        assert bsr_output.artifacts[0].artifact_type == "report"

        model = json.loads(store.artifact_path(lr_output.artifacts[0]).read_text())
        scorecard = json.loads(store.artifact_path(ss_output.artifacts[0]).read_text())
        assert "coefficients" in model
        assert "attributes" in scorecard
        assert len(scorecard["attributes"]) > 0

    def test_woe_transform_selects_only_selected_vars(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 40.0],
            "income": [50000.0, 60000.0, 70000.0, 80000.0],
            "target": ["good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df)
        meta_art = _make_json_artifact(
            store, {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}, stem="meta"
        )

        bin_def = {
            "variables": [
                {"variable": "age", "kind": "numeric",
                 "bins": [{"bin_id": "age_b1", "label": "Young", "lower": 0, "upper": 30,
                           "lower_inclusive": True, "upper_inclusive": True,
                           "categories": None, "is_missing_bin": False,
                           "row_count": 2, "good_count": 1, "bad_count": 1},
                          {"bin_id": "age_b2", "label": "Old", "lower": 30, "upper": None,
                           "lower_inclusive": False, "upper_inclusive": True,
                           "categories": None, "is_missing_bin": False,
                           "row_count": 2, "good_count": 1, "bad_count": 1}]},
                {"variable": "income", "kind": "numeric",
                 "bins": [{"bin_id": "inc_b1", "label": "Low", "lower": 0, "upper": 60000,
                           "lower_inclusive": True, "upper_inclusive": True,
                           "categories": None, "is_missing_bin": False,
                           "row_count": 2, "good_count": 1, "bad_count": 1},
                          {"bin_id": "inc_b2", "label": "High", "lower": 60000, "upper": None,
                           "lower_inclusive": False, "upper_inclusive": True,
                           "categories": None, "is_missing_bin": False,
                           "row_count": 2, "good_count": 1, "bad_count": 1}]},
            ],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins")

        woe_df = pl.DataFrame({
            "variable": ["age", "age", "income", "income"],
            "bin_id": ["age_b1", "age_b2", "inc_b1", "inc_b2"],
            "label": ["Young", "Old", "Low", "High"],
            "row_count": [2, 2, 2, 2], "good_count": [1, 1, 1, 1], "bad_count": [1, 1, 1, 1],
            "good_distribution": [0.5, 0.5, 0.5, 0.5], "bad_distribution": [0.5, 0.5, 0.5, 0.5],
            "woe": [0.2, -0.2, 0.3, -0.3], "iv_component": [0.0, 0.0, 0.0, 0.0],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe")

        selection = {"selected": [{"variable": "age", "reason": "IV above threshold"}],
                     "rejected": [{"variable": "income", "reason": "Lower IV"}]}
        sel_art = _make_json_artifact(store, selection, stem="selection")

        params = {}
        spec = StepSpec(step_id="wt", node_type="cardre.woe_transform_train", node_version="1", category="fit",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[train_art, bin_art, woe_art, sel_art, meta_art],
                               validated_params=params, runtime_metadata={})
        output = WoeTransformTrainNode().run(ctx)

        transformed = pl.read_parquet(store.artifact_path(output.artifacts[0]))
