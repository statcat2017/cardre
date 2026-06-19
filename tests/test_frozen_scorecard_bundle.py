from __future__ import annotations

import json
import math

import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    StepSpec,
    json_logical_hash,
)
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_WOE_TABLE,
)
from cardre.nodes.build.freeze import FrozenScorecardBundleNode
from tests.helpers import make_store


def _make_model_artifact(store, features, *, target_column="target", intercept=-0.5, coeffs=None):
    """Create a properly tagged model artifact and return the ArtifactRef."""
    if coeffs is None:
        coeffs = {f: 0.8 for f in features}
    raw_fc = {
        "features": features,
        "transformation_strategy": "woe",
        "order_hash": json_logical_hash({"features": features}),
        "missing_policy": "error",
        "unknown_category_policy": "error",
    }
    model = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "logistic_regression",
        "target_column": target_column,
        "features": features,
        "intercept": intercept,
        "coefficients": coeffs,
        "class_mapping": {"good": "good", "bad": "bad"},
        "bad_class_label": "bad",
        "target_event_value": "bad",
        "probability_column_index": 1,
        "feature_contract": raw_fc,
        "feature_order_hash": json_logical_hash({"features": features}),
        "training": {"row_count": 100, "converged": True, "iterations": 10, "params": {}},
        "warnings": [],
    }
    return write_json_artifact(
        store, artifact_type="model", role="model",
        stem="model",
        payload=model,
        metadata={
            "feature_count": len(features),
            "target_column": target_column,
            "schema_version": SCHEMA_MODEL_ARTIFACT,
        },
    )


def _make_scorecard_artifact(store, *, target_column="target", intercept=-0.5,
                              base_score=600, base_odds=50.0, pdo=20.0,
                              higher_is_lower=True, attributes=None):
    """Create a properly tagged scorecard artifact."""
    factor = pdo / math.log(2)
    offset = base_score - factor * math.log(base_odds)
    direction = -1.0 if higher_is_lower else 1.0
    if attributes is None:
        attributes = []
    scorecard = {
        "schema_version": "cardre.score_scaling.v1",
        "base_score": base_score,
        "base_odds": base_odds,
        "points_to_double_odds": pdo,
        "factor": round(factor, 6),
        "offset": round(offset, 6),
        "higher_score_is_lower_risk": higher_is_lower,
        "intercept": intercept,
        "base_points": round(offset + direction * factor * intercept, 2),
        "attributes": attributes,
        "target_column": target_column,
    }
    return write_json_artifact(
        store, artifact_type="scorecard", role="scorecard",
        stem="scorecard",
        payload=scorecard,
        metadata={
            "base_score": base_score,
            "attribute_count": len(attributes),
            "schema_version": SCHEMA_SCORE_SCALING,
        },
    )


# ======================================================================
# Happy path
# ======================================================================


class TestFrozenScorecardBundleHappyPath:

    def test_emits_single_bundle_with_selection(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={
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
            },
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["x", "x"],
            "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"],
            "row_count": [50, 50], "good_count": [40, 30], "bad_count": [10, 20],
            "good_distribution": [0.5, 0.5], "bad_distribution": [0.5, 0.5],
            "woe": [0.3, -0.2], "iv_component": [0.1, 0.05],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        sel_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="sel_def",
            payload={"selected": [{"variable": "x"}], "method": "iv"},
            metadata={"schema_version": SCHEMA_SELECTION_DEFINITION},
        )
        model_art = _make_model_artifact(store, ["x_woe"])
        scorecard_art = _make_scorecard_artifact(
            store,
            attributes=[
                {"variable": "x", "bin_id": "x_b1", "label": "Low",
                 "woe": 0.3, "coefficient": 0.8, "points": -28.85},
                {"variable": "x", "bin_id": "x_b2", "label": "High",
                 "woe": -0.2, "coefficient": 0.8, "points": 19.24},
            ],
        )

        params = {}
        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, sel_art, model_art, scorecard_art],
            validated_params=params, runtime_metadata={},
        )
        output = FrozenScorecardBundleNode().run(ctx)

        assert len(output.artifacts) == 1
        artifact = output.artifacts[0]
        assert artifact.artifact_type == "scorecard"
        assert artifact.role == "scorecard"

        bundle = json.loads(store.artifact_path(artifact).read_text())

        assert bundle["schema_version"] == "cardre.frozen_scorecard_bundle.v1"
        assert bundle["bundle_type"] == "scorecard_application"
        assert bundle["created_from"]["run_id"] == "r1"
        assert bundle["created_from"]["step_id"] == "freeze"
        assert bundle["created_from"]["canonical_step_id"] == "freeze"

        assert bundle["target"]["target_column"] == "target"
        assert bundle["target"]["good_values"] == ["good"]
        assert bundle["target"]["bad_values"] == ["bad"]
        assert bundle["target"]["event_convention"] == "bad"

        comps = bundle["components"]
        assert comps["bin_definition_logical_hash"] == bin_art.logical_hash
        assert comps["bin_definition_physical_hash"] == bin_art.physical_hash
        assert comps["woe_table_logical_hash"] == woe_art.logical_hash
        assert comps["woe_table_physical_hash"] == woe_art.physical_hash
        assert comps["model_logical_hash"] == model_art.logical_hash
        assert comps["model_physical_hash"] == model_art.physical_hash
        assert comps["scorecard_logical_hash"] == scorecard_art.logical_hash
        assert comps["scorecard_physical_hash"] == scorecard_art.physical_hash
        assert comps["selection_logical_hash"] == sel_art.logical_hash
        assert comps["selection_physical_hash"] == sel_art.physical_hash
        assert "bin_definition_artifact_id" not in comps

        fc = bundle["feature_contract"]
        assert fc["features"] == ["x_woe"]
        assert fc["source_variables"] == ["x"]
        assert fc["transformation_strategy"] == "woe"
        assert fc["order_hash"] == json_logical_hash({"features": ["x_woe"]})
        assert fc["missing_policy"] == "error"
        assert fc["unknown_category_policy"] == "error"

        ss = bundle["score_scaling"]
        assert ss["base_score"] == 600
        assert ss["base_odds"] == 50.0
        assert ss["points_to_double_odds"] == 20.0
        assert ss["higher_score_is_lower_risk"] is True
        assert ss["intercept"] == -0.5

        assert len(bundle["warnings"]) == 0

        assert artifact.metadata["schema_version"] == SCHEMA_FROZEN_SCORECARD_BUNDLE
        assert artifact.metadata["model_artifact_id"] == model_art.artifact_id
        assert artifact.metadata["scorecard_artifact_id"] == scorecard_art.artifact_id
        assert artifact.metadata["bin_definition_artifact_id"] == bin_art.artifact_id
        assert artifact.metadata["woe_table_artifact_id"] == woe_art.artifact_id
        assert artifact.metadata["selection_artifact_id"] == sel_art.artifact_id
        assert artifact.metadata["feature_count"] == 1

    def test_emits_bundle_without_selection(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={
                "variables": [{
                    "variable": "x", "kind": "numeric",
                    "bins": [
                        {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 10,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 50, "good_count": 40, "bad_count": 10},
                    ],
                }],
                "warnings": [],
            },
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["Low"],
            "row_count": [50], "good_count": [40], "bad_count": [10],
            "good_distribution": [1.0], "bad_distribution": [1.0],
            "woe": [0.3], "iv_component": [0.1],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        model_art = _make_model_artifact(store, ["x_woe"])
        scorecard_art = _make_scorecard_artifact(
            store,
            attributes=[
                {"variable": "x", "bin_id": "x_b1", "label": "Low",
                 "woe": 0.3, "coefficient": 0.8, "points": -28.85},
            ],
        )

        params = {}
        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params=params, runtime_metadata={},
        )
        output = FrozenScorecardBundleNode().run(ctx)

        assert len(output.artifacts) == 1
        bundle = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        comps = bundle["components"]
        assert "selection_logical_hash" not in comps
        assert "selection_physical_hash" not in comps
        assert "selection_artifact_id" not in output.artifacts[0].metadata

    def test_zero_warnings_on_consistent_inputs(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        model_art = _make_model_artifact(store, ["age_woe", "income_woe"], intercept=0.0)

        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={
                "variables": [
                    {"variable": "age", "kind": "numeric", "bins": []},
                    {"variable": "income", "kind": "numeric", "bins": []},
                ],
                "warnings": [],
            },
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["age", "income"],
            "bin_id": ["age_b1", "inc_b1"],
            "label": ["Young", "Low"],
            "row_count": [50, 50], "good_count": [40, 40], "bad_count": [10, 10],
            "good_distribution": [0.5, 0.5], "bad_distribution": [0.5, 0.5],
            "woe": [0.3, 0.2], "iv_component": [0.1, 0.05],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        scorecard_art = _make_scorecard_artifact(store, intercept=0.0)

        params = {}
        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params=params, runtime_metadata={},
        )
        output = FrozenScorecardBundleNode().run(ctx)
        bundle = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert len(bundle["warnings"]) == 0

    def test_bundle_findable_via_evidence_reader(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={
                "variables": [{"variable": "x", "kind": "numeric", "bins": []}],
                "warnings": [],
            },
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["x"],
            "row_count": [1], "good_count": [1], "bad_count": [0],
            "good_distribution": [1.0], "bad_distribution": [0.0],
            "woe": [0.0], "iv_component": [0.0],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        model_art = _make_model_artifact(store, ["x_woe"])
        scorecard_art = _make_scorecard_artifact(store)

        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params={}, runtime_metadata={},
        )
        output = FrozenScorecardBundleNode().run(ctx)
        bundle_art = output.artifacts[0]

        reader = ArtifactEvidenceReader(store)
        found = reader.find([bundle_art], EvidenceKind.FROZEN_SCORECARD_BUNDLE)
        assert found is not None
        assert found["schema_version"] == "cardre.frozen_scorecard_bundle.v1"


# ======================================================================
# Warning / mismatch tests
# ======================================================================


class TestFrozenScorecardBundleWarnings:

    def test_raises_on_target_mismatch(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "other_target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={"variables": [], "warnings": []},
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["x"],
            "row_count": [1], "good_count": [1], "bad_count": [0],
            "good_distribution": [1.0], "bad_distribution": [0.0],
            "woe": [0.0], "iv_component": [0.0],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        model_art = _make_model_artifact(store, ["x_woe"], target_column="target")
        scorecard_art = _make_scorecard_artifact(store, target_column="target")

        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params={}, runtime_metadata={},
        )
        with pytest.raises(ValueError, match="metadata target"):
            FrozenScorecardBundleNode().run(ctx)

    def test_raises_on_intercept_mismatch(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={
                "variables": [{"variable": "x", "kind": "numeric", "bins": []}],
                "warnings": [],
            },
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["x"],
            "row_count": [1], "good_count": [1], "bad_count": [0],
            "good_distribution": [1.0], "bad_distribution": [0.0],
            "woe": [0.0], "iv_component": [0.0],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        model_art = _make_model_artifact(store, ["x_woe"], intercept=-0.5)
        scorecard_art = _make_scorecard_artifact(store, intercept=0.5)

        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params={}, runtime_metadata={},
        )
        with pytest.raises(ValueError, match="intercept"):
            FrozenScorecardBundleNode().run(ctx)

    def test_raises_on_feature_missing_in_woe_mapping(self):
        store, tmp = make_store()
        store.initialize()

        meta_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="meta",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={"schema_version": SCHEMA_MODELLING_METADATA},
        )
        bin_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="bin_def",
            payload={"variables": [{"variable": "missing_var", "kind": "numeric", "bins": []}], "warnings": []},
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        woe_df = pl.DataFrame({
            "variable": ["other"], "bin_id": ["o_b1"], "label": ["Other"],
            "row_count": [50], "good_count": [40], "bad_count": [10],
            "good_distribution": [1.0], "bad_distribution": [1.0],
            "woe": [0.5], "iv_component": [0.2],
        })
        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem="woe_table",
            frame=woe_df,
            metadata={"schema_version": SCHEMA_WOE_TABLE},
        )
        model_art = _make_model_artifact(store, ["x_woe"])
        scorecard_art = _make_scorecard_artifact(store)

        spec = StepSpec(
            step_id="freeze", node_type="cardre.freeze_scorecard_bundle",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[meta_art, bin_art, woe_art, model_art, scorecard_art],
            validated_params={}, runtime_metadata={},
        )
        with pytest.raises(ValueError, match="WOE mapping"):
            FrozenScorecardBundleNode().run(ctx)
