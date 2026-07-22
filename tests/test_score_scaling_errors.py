from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso

pytestmark = pytest.mark.xfail(reason="Uses old ExecutionContext; needs NodeContext update")


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _register_artifact(store, artifact_id, artifact_type, role, path, schema_version=None):
    metadata = {}
    if schema_version:
        metadata["schema_version"] = schema_version
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, artifact_type, role, path, "phys", "log",
         "application/json", utc_now_iso(), json.dumps(metadata)),
    )


def _seed_project_and_plan(store):
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Score Scaling Test", now, "0.2.0"),
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


class TestScoreScalingRunErrors:
    def test_missing_model_artifact_raises(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_project_and_plan(store)
        from cardre._evidence.kinds import EvidenceNotFoundError
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        from cardre.nodes.build.models import ScoreScalingNode
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=StepSpec(
                step_id="s1", node_type="cardre.score_scaling", node_version="1",
                category="fit", params={}, params_hash="h",
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[],
            validated_params={"base_score": 600, "base_odds": "50:1",
                              "points_to_double_odds": 20.0, "higher_score_is_lower_risk": True},
            runtime_metadata={},
        )
        node = ScoreScalingNode()
        with pytest.raises((EvidenceNotFoundError, ValueError)):
            node.run(ctx)

    def test_empty_bin_def_raises(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_project_and_plan(store)

        model_payload = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "logistic_regression",
            "target_column": "default_flag",
            "source_variables": ["age"],
            "class_mapping": {"good": "0", "bad": "1"},
            "bad_class_label": "1",
            "target_event_value": "1",
            "probability_column_index": 1,
            "feature_contract": {"features": ["age_woe"], "transformation_strategy": "woe",
                                 "order_hash": "abc", "missing_policy": "error",
                                 "unknown_category_policy": "error"},
            "feature_order_hash": "abc",
            "model_payload": {"intercept": -0.5, "coefficients": {"age_woe": 1.2}},
            "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {}},
            "warnings": [],
        }
        model_path = tmp_path / "model.json"
        model_path.write_text(json.dumps(model_payload))
        _register_artifact(store, "model-art", "model", "model", str(model_path),
                           schema_version="cardre.model_artifact.v1")

        bin_def_payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [],
        }
        bin_def_path = tmp_path / "bin_def.json"
        bin_def_path.write_text(json.dumps(bin_def_payload))
        _register_artifact(store, "bin-def-art", "definition", "definition", str(bin_def_path),
                           schema_version="cardre.bin_definition.v1")

        woe_path = tmp_path / "woe.parquet"
        import polars as pl
        pl.DataFrame({"variable": [], "bin_id": [], "woe": []}).write_parquet(woe_path)
        _register_artifact(store, "woe-art", "report", "report", str(woe_path))

        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        from cardre.nodes.build.models import ScoreScalingNode

        def _make_ref(artifact_id, artifact_type, role, path, media_type="application/json"):
            return ArtifactRef(
                artifact_id=artifact_id, artifact_type=artifact_type, role=role,
                path=str(path), physical_hash="ph", logical_hash="lh",
                media_type=media_type,
            )
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=StepSpec(
                step_id="s1", node_type="cardre.score_scaling", node_version="1",
                category="fit", params={}, params_hash="h",
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[],
            input_artifacts=[
                _make_ref("model-art", "model", "model", model_path),
                _make_ref("bin-def-art", "definition", "definition", bin_def_path),
                _make_ref("woe-art", "report", "report", woe_path, "application/vnd.apache.parquet"),
            ],
            validated_params={"base_score": 600, "base_odds": "50:1",
                              "points_to_double_odds": 20.0, "higher_score_is_lower_risk": True},
            runtime_metadata={},
        )
        node = ScoreScalingNode()
        with pytest.raises(ValueError, match="empty bin definition"):
            node.run(ctx)

    def test_diverging_score_direction(self, tmp_path):
        store = _make_store(tmp_path)
        _seed_project_and_plan(store)

        model_payload = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "logistic_regression",
            "target_column": "default_flag",
            "source_variables": ["age"],
            "class_mapping": {"good": "0", "bad": "1"},
            "bad_class_label": "1",
            "target_event_value": "1",
            "probability_column_index": 1,
            "feature_contract": {"features": ["age_woe"], "transformation_strategy": "woe",
                                 "order_hash": "abc", "missing_policy": "error",
                                 "unknown_category_policy": "error"},
            "feature_order_hash": "abc",
            "model_payload": {"intercept": -0.5, "coefficients": {"age_woe": 1.2}},
            "training": {"row_count": 100, "converged": True, "iterations": 15, "params": {}},
            "warnings": [],
        }
        model_path = tmp_path / "model.json"
        model_path.write_text(json.dumps(model_payload))
        _register_artifact(store, "model-art-2", "model", "model", str(model_path),
                           schema_version="cardre.model_artifact.v1")

        bin_def_payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {"variable": "age", "dtype": "numeric", "kind": "fine",
                 "bins": [{"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30}]},
            ],
        }
        bin_def_path = tmp_path / "bin_def.json"
        bin_def_path.write_text(json.dumps(bin_def_payload))
        _register_artifact(store, "bin-def-art-2", "definition", "definition", str(bin_def_path),
                           schema_version="cardre.bin_definition.v1")

        woe_path = tmp_path / "woe.parquet"
        import polars as pl
        pl.DataFrame({"variable": ["age"], "bin_id": ["b1"], "woe": [0.5]}).write_parquet(woe_path)
        _register_artifact(store, "woe-art-2", "report", "report", str(woe_path))

        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        from cardre.nodes.build.models import ScoreScalingNode

        def _make_ref(artifact_id, artifact_type, role, path, media_type="application/json"):
            return ArtifactRef(
                artifact_id=artifact_id, artifact_type=artifact_type, role=role,
                path=str(path), physical_hash="ph", logical_hash="lh",
                media_type=media_type,
            )
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=StepSpec(
                step_id="s1", node_type="cardre.score_scaling", node_version="1",
                category="fit", params={}, params_hash="h",
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[],
            input_artifacts=[
                _make_ref("model-art-2", "model", "model", model_path),
                _make_ref("bin-def-art-2", "definition", "definition", bin_def_path),
                _make_ref("woe-art-2", "report", "report", woe_path, "application/vnd.apache.parquet"),
            ],
            validated_params={"base_score": 600, "base_odds": "50:1",
                              "points_to_double_odds": 20.0, "higher_score_is_lower_risk": False},
            runtime_metadata={},
        )
        node = ScoreScalingNode()
        output = node.run(ctx)
        assert len(output.artifacts) == 1
        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert payload["score_direction"] == "higher_is_better"
        assert payload["base_points"] < 600
