from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.nodes.build.models import BuildSummaryReportNode, DummyFitNode, NoopNode


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _register_artifact(store, artifact_id, artifact_type, role, path):
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, artifact_type, role, path, "phys", "log", "application/json", utc_now_iso()),
    )


def _make_artifact_ref(artifact_id, role):
    from cardre.domain.artifacts import ArtifactRef
    return ArtifactRef(artifact_id=artifact_id, artifact_type="scorecard", role=role, path="/tmp/fake",
                       physical_hash="phys", logical_hash="log")


class TestBuildSummaryReportNode:
    def test_missing_scorecard_raises(self, tmp_path):
        store = _make_store(tmp_path)
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        ctx = ExecutionContext(
            store=store, run_id="run-1", plan_version_id="pv-1",
            step_spec=StepSpec(
                step_id="s1", node_type="cardre.build_summary_report", node_version="1",
                category="fit", params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[], validated_params={}, runtime_metadata={},
        )
        node = BuildSummaryReportNode()
        with pytest.raises(ValueError, match="requires a scorecard artifact"):
            node.run(ctx)

    def test_missing_model_raises(self, tmp_path):
        store = _make_store(tmp_path)
        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        scorecard_path = tmp_path / "scorecard.json"
        scorecard_path.write_text(json.dumps({
            "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20.0,
            "factor": 28.85, "offset": 487.0, "higher_score_is_lower_risk": True,
            "intercept": -0.5, "base_points": 500.0, "attributes": [],
        }))
        art_id = "sc-art-1"
        _register_artifact(store, art_id, "scorecard", "scorecard", str(scorecard_path))
        ctx = ExecutionContext(
            store=store, run_id="run-1", plan_version_id="pv-1",
            step_spec=StepSpec(
                step_id="s1", node_type="cardre.build_summary_report", node_version="1",
                category="fit", params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[], input_artifacts=[ArtifactRef(artifact_id=art_id, artifact_type="scorecard", role="scorecard", path=str(scorecard_path), physical_hash="ph", logical_hash="lh")],
            validated_params={}, runtime_metadata={},
        )
        node = BuildSummaryReportNode()
        with pytest.raises(ValueError, match="requires a model artifact"):
            node.run(ctx)


class TestNoopNode:
    def test_run_returns_empty(self):
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        node = NoopNode()
        step_spec = StepSpec(
            step_id="n1", node_type="cardre.noop", node_version="1",
            category="transform", params={}, params_hash="h",
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=None, run_id="r", plan_version_id="pv",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[], validated_params={}, runtime_metadata={},
        )
        output = node.run(ctx)
        assert output.artifacts == []
        assert output.metrics == {}


class TestDummyFitNode:
    def test_run_with_valid_input(self, tmp_path):
        store = _make_store(tmp_path)
        from cardre.domain.artifacts import ArtifactRef
        from cardre.domain.step import StepSpec
        from cardre.execution.context import ExecutionContext
        node = DummyFitNode()
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("a,b\n1,2\n3,4\n")
        import polars as pl
        parquet_path = tmp_path / "data.parquet"
        pl.DataFrame({"a": [1, 2], "b": [3, 4]}).write_parquet(parquet_path)
        art_id = "dummy-input"
        _register_artifact(store, art_id, "dataset", "train", str(parquet_path))
        ctx = ExecutionContext(
            store=store, run_id="r", plan_version_id="pv",
            step_spec=StepSpec(
                step_id="d1", node_type="cardre.dummy_fit", node_version="1",
                category="fit", params={"dummy_param": 42}, params_hash="h",
                parent_step_ids=[], branch_label="", position=0,
            ),
            parent_run_steps=[],
            input_artifacts=[ArtifactRef(artifact_id=art_id, artifact_type="dataset", role="train", path=str(parquet_path), physical_hash="ph", logical_hash="lh")],
            validated_params={"dummy_param": 42}, runtime_metadata={},
        )
        output = node.run(ctx)
        assert len(output.artifacts) == 1
        assert output.artifacts[0].role == "definition"
        assert output.metrics["row_count"] == 2
