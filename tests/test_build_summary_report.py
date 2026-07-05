"""Characterization tests for BuildSummaryReportNode — verifies the report
schema and model/scorecard summary extraction behavior.

Uses the same fixture pattern as test_score_scaling_known_input.py: write
tiny model + bin_def + woe_table artifacts, run ScoreScalingNode to produce
a real scorecard, then feed scorecard + model into BuildSummaryReportNode.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre._evidence.schemas import SCHEMA_MODEL_ARTIFACT, SCHEMA_SCORE_SCALING
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.models import BuildSummaryReportNode, ScoreScalingNode


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_project_and_plan(store) -> tuple[str, str]:
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Build Summary Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    return project_id, pv_id


def _register_artifact(store, artifact_id, artifact_type, role, path, schema_version=None, media_type="application/json"):
    metadata = {}
    if schema_version:
        metadata["schema_version"] = schema_version
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, artifact_type, role, path, "phys", "log",
         media_type, utc_now_iso(), json.dumps(metadata)),
    )


@pytest.fixture
def model_artifact_payload() -> dict:
    return {
        "schema_version": SCHEMA_MODEL_ARTIFACT,
        "model_family": "logistic_regression",
        "target_column": "default_flag",
        "intercept": -0.5,
        "coefficients": {"age_woe": 1.2, "income_woe": -0.8},
        "features": ["age_woe", "income_woe"],
        "source_variables": ["age", "income"],
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "feature_contract": {
            "features": ["age_woe", "income_woe"],
            "transformation_strategy": "woe",
            "order_hash": "abc",
            "missing_policy": "error",
            "unknown_category_policy": "error",
        },
        "feature_order_hash": "abc",
        "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {"C": 1.0}},
        "warnings": [],
    }


@pytest.fixture
def bin_def_payload() -> dict:
    return {
        "schema_version": "cardre.bin_definition.v1",
        "variables": [
            {
                "variable": "age",
                "dtype": "numeric",
                "kind": "fine",
                "bins": [
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30},
                    {"bin_id": "b2", "label": "31-50", "lower": 31, "upper": 50},
                ],
            },
            {
                "variable": "income",
                "dtype": "numeric",
                "kind": "fine",
                "bins": [
                    {"bin_id": "b3", "label": "Low", "lower": 0, "upper": 30000},
                ],
            },
        ],
    }


@pytest.fixture
def woe_table_parquet(tmp_path: Path) -> Path:
    df = pl.DataFrame({
        "variable": ["age", "age", "income"],
        "bin_id": ["b1", "b2", "b3"],
        "woe": [0.5, -0.3, 0.2],
    })
    path = tmp_path / "woe_table.parquet"
    df.write_parquet(path)
    return path


def _build_score_scaling_context(store, tmp_path, model_payload, bin_def_payload, woe_table_path):
    """Set up artifacts and return an ExecutionContext for ScoreScalingNode."""
    _seed_project_and_plan(store)

    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(model_payload))
    _register_artifact(store, "model-art", "model", "model", str(model_path), SCHEMA_MODEL_ARTIFACT)

    bin_def_path = tmp_path / "bin_def.json"
    bin_def_path.write_text(json.dumps(bin_def_payload))
    _register_artifact(store, "bin-def-art", "definition", "definition", str(bin_def_path), "cardre.bin_definition.v1")

    _register_artifact(store, "woe-art", "report", "report", str(woe_table_path), "application/vnd.apache.parquet", "application/vnd.apache.parquet")

    from cardre.domain.artifacts import ArtifactRef
    model_ref = ArtifactRef(artifact_id="model-art", artifact_type="model", role="model",
                            path=str(model_path), physical_hash="ph", logical_hash="lh", media_type="application/json")
    bin_ref = ArtifactRef(artifact_id="bin-def-art", artifact_type="definition", role="definition",
                          path=str(bin_def_path), physical_hash="ph", logical_hash="lh", media_type="application/json")
    woe_ref = ArtifactRef(artifact_id="woe-art", artifact_type="report", role="report",
                          path=str(woe_table_path), physical_hash="ph", logical_hash="lh", media_type="application/vnd.apache.parquet")

    step_spec = StepSpec(
        step_id="score-scaling-1", node_type="cardre.score_scaling", node_version="1",
        category="fit", params={}, params_hash="dummy", parent_step_ids=[],
    )
    return ExecutionContext(
        store=store, run_id="run-1", plan_version_id="pv-1",
        step_spec=step_spec, parent_run_steps=[],
        input_artifacts=[model_ref, bin_ref, woe_ref],
        validated_params={"base_score": 600, "base_odds": "50:1", "points_to_double_odds": 20.0,
                          "higher_score_is_lower_risk": True},
        runtime_metadata={},
    )


class TestBuildSummaryReportNode:
    def test_happy_path_produces_report(
        self, tmp_path, store, model_artifact_payload, bin_def_payload, woe_table_parquet,
    ):
        """Run ScoreScalingNode then BuildSummaryReportNode and verify the report payload."""
        # 1. Run ScoreScalingNode to produce a real scorecard artifact
        sc_ctx = _build_score_scaling_context(
            store, tmp_path, model_artifact_payload, bin_def_payload, woe_table_parquet,
        )
        sc_output = ScoreScalingNode().run(sc_ctx)
        assert len(sc_output.artifacts) == 1
        scorecard_art = sc_output.artifacts[0]
        assert scorecard_art.role == "scorecard"

        # 2. Build context for BuildSummaryReportNode with scorecard + model + woe
        from cardre.domain.artifacts import ArtifactRef
        model_ref = ArtifactRef(
            artifact_id="model-art", artifact_type="model", role="model",
            path=str(tmp_path / "model.json"), physical_hash="ph", logical_hash="lh",
            media_type="application/json",
        )
        scorecard_ref = ArtifactRef(
            artifact_id=scorecard_art.artifact_id, artifact_type="scorecard", role="scorecard",
            path=store.artifact_path(scorecard_art), physical_hash="ph", logical_hash="lh",
            media_type="application/json",
        )
        woe_ref = ArtifactRef(
            artifact_id="woe-art", artifact_type="report", role="report",
            path=str(woe_table_parquet), physical_hash="ph", logical_hash="lh",
            media_type="application/vnd.apache.parquet",
        )

        step_spec = StepSpec(
            step_id="build-summary-1", node_type="cardre.build_summary_report", node_version="1",
            category="fit", params={}, params_hash="dummy", parent_step_ids=[],
        )
        ctx = ExecutionContext(
            store=store, run_id="run-1", plan_version_id="pv-1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[scorecard_ref, model_ref, woe_ref],
            validated_params={}, runtime_metadata={},
        )

        # 3. Run BuildSummaryReportNode
        output = BuildSummaryReportNode().run(ctx)
        assert len(output.artifacts) == 1
        report_art = output.artifacts[0]
        assert report_art.artifact_type == "report"
        assert report_art.role == "report"

        # 4. Verify report payload
        report_path = store.artifact_path(report_art)
        report = json.loads(report_path.read_bytes())

        assert "model_summary" in report
        assert "scorecard_summary" in report
        assert "woe_iv_references" in report
        assert "warnings" in report

        model_summary = report["model_summary"]
        assert model_summary["target_column"] == "default_flag"
        assert model_summary["features"] == ["age_woe", "income_woe"]
        assert model_summary["intercept"] == -0.5
        assert model_summary["coefficient_count"] == 2
        assert model_summary["converged"] is True
        assert model_summary["row_count"] == 100

        sc_summary = report["scorecard_summary"]
        assert sc_summary["base_score"] == 600
        assert sc_summary["base_odds"] == 50.0
        assert sc_summary["points_to_double_odds"] == 20.0
        assert sc_summary["attribute_count"] == 3  # age b1, age b2, income b3

        assert isinstance(report["woe_iv_references"], list)

    def test_missing_scorecard_raises(self, tmp_path, store):
        """BuildSummaryReportNode raises when no scorecard artifact is provided."""
        step_spec = StepSpec(
            step_id="bs-1", node_type="cardre.build_summary_report", node_version="1",
            category="fit", params={}, params_hash="h", parent_step_ids=[],
        )
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[], validated_params={}, runtime_metadata={},
        )
        with pytest.raises(ValueError, match="requires a scorecard artifact"):
            BuildSummaryReportNode().run(ctx)

    def test_missing_model_raises(self, tmp_path, store, model_artifact_payload):
        """BuildSummaryReportNode raises when no model artifact is provided."""
        # Write a scorecard artifact so the first check passes
        scorecard_payload = {
            "schema_version": SCHEMA_SCORE_SCALING,
            "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20.0,
            "factor": 28.85, "offset": 487.0, "higher_score_is_lower_risk": True,
            "intercept": -0.5, "base_points": 500.0, "attributes": [],
        }
        sc_path = tmp_path / "scorecard.json"
        sc_path.write_text(json.dumps(scorecard_payload))
        _register_artifact(store, "sc-art", "scorecard", "scorecard", str(sc_path), SCHEMA_SCORE_SCALING)

        from cardre.domain.artifacts import ArtifactRef
        sc_ref = ArtifactRef(
            artifact_id="sc-art", artifact_type="scorecard", role="scorecard",
            path=str(sc_path), physical_hash="ph", logical_hash="lh",
            media_type="application/json",
        )
        step_spec = StepSpec(
            step_id="bs-2", node_type="cardre.build_summary_report", node_version="1",
            category="fit", params={}, params_hash="h", parent_step_ids=[],
        )
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[sc_ref], validated_params={}, runtime_metadata={},
        )
        with pytest.raises(ValueError, match="requires a model artifact"):
            BuildSummaryReportNode().run(ctx)
