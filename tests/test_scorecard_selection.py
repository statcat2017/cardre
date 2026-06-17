"""Tests for scorecard variable clustering and selection."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

import polars as pl

import pytest

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.nodes import (
    VariableClusteringNode,
    VariableSelectionNode,
)
from cardre.store import ProjectStore

from tests.helpers import make_store


# ======================================================================
# Workstream 8: Variable Clustering
# ======================================================================

class VariableClusteringTests(unittest.TestCase):

    def test_clustering_produces_clusters(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "num1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "num2": [2.0, 4.0, 6.0, 8.0, 10.0],
            "cat1": ["a", "b", "a", "b", "a"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        iv_df = pl.DataFrame({
            "variable": ["num1", "num2", "cat1"],
            "iv": [0.3, 0.25, 0.1],
            "bin_count": [2, 2, 1],
            "zero_cell_count": [0, 0, 0],
            "warning_count": [0, 0, 0],
        })
        iv_buf = io.BytesIO()
        iv_df.write_parquet(iv_buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.write_bytes(iv_buf.getvalue())
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        params = {"correlation_threshold": 0.7, "candidate_limit": 50}
        step_spec = StepSpec(
            step_id="clustering", node_type="cardre.variable_clustering",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, iv_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableClusteringNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("clusters", payload)
        self.assertGreater(len(payload["clusters"]), 0)


# ======================================================================
# Workstream 9: Variable Selection
# ======================================================================

class VariableSelectionTests(unittest.TestCase):

    def test_selection_includes_by_iv_threshold(self) -> None:
        store, tmp = make_store()
        store.initialize()

        iv_df = pl.DataFrame({
            "variable": ["v1", "v2", "v3", "v4"],
            "iv": [0.5, 0.03, 0.01, 0.4],
            "bin_count": [3, 3, 3, 3],
            "zero_cell_count": [0, 0, 0, 0],
            "warning_count": [0, 0, 0, 0],
        })
        buf = io.BytesIO()
        iv_df.write_parquet(buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.parent.mkdir(parents=True, exist_ok=True)
        iv_path.write_bytes(buf.getvalue())
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        clustering = {
            "correlation_threshold": 0.7,
            "candidate_limit": 50,
            "total_candidates": 4,
            "clusters": [
                {"cluster_id": "c1", "variables": ["v1"], "reason": "Singleton"},
                {"cluster_id": "c2", "variables": ["v2"], "reason": "Singleton"},
                {"cluster_id": "c3", "variables": ["v3"], "reason": "Singleton"},
                {"cluster_id": "c4", "variables": ["v4"], "reason": "Singleton"},
            ],
            "warnings": [],
        }
        clust_path = store.root / "artifacts" / "test-clust.json"
        clust_path.write_text(json.dumps(clustering, sort_keys=True))
        clust_artifact = ArtifactRef(
            artifact_id="clust1", artifact_type="report", role="report",
            path=relative_path(clust_path, store.root),
            physical_hash=physical_hash(clust_path),
            logical_hash=json_logical_hash(clustering),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(clust_artifact)

        params = {"min_iv": 0.02, "max_variables": 15, "manual_includes": [], "manual_excludes": []}
        step_spec = StepSpec(
            step_id="selection", node_type="cardre.variable_selection",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[iv_artifact, clust_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableSelectionNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v1", selected_vars)
        self.assertIn("v4", selected_vars)
        self.assertNotIn("v3", selected_vars)

    def test_every_selection_has_reason(self) -> None:
        store, tmp = make_store()
        store.initialize()

        iv_df = pl.DataFrame({
            "variable": ["v1", "v2"],
            "iv": [0.3, 0.02],
            "bin_count": [2, 2],
            "zero_cell_count": [0, 0],
            "warning_count": [0, 0],
        })
        buf = io.BytesIO()
        iv_df.write_parquet(buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.parent.mkdir(parents=True, exist_ok=True)
        iv_path.write_bytes(buf.getvalue())
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        clustering = {"clusters": [
            {"cluster_id": "c1", "variables": ["v1"], "reason": "Single"},
            {"cluster_id": "c2", "variables": ["v2"], "reason": "Single"},
        ], "warnings": []}
        clust_path = store.root / "artifacts" / "test-clust.json"
        clust_path.write_text(json.dumps(clustering, sort_keys=True))
        clust_artifact = ArtifactRef(
            artifact_id="clust2", artifact_type="report", role="report",
            path=relative_path(clust_path, store.root),
            physical_hash=physical_hash(clust_path),
            logical_hash=json_logical_hash(clustering),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(clust_artifact)

        params = {"min_iv": 0.02, "max_variables": 15}
        step_spec = StepSpec(
            step_id="sel", node_type="cardre.variable_selection",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[iv_artifact, clust_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableSelectionNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        for entry in payload["selected"] + payload["rejected"]:
            self.assertIn("reason", entry)
            self.assertTrue(entry["reason"])


def test_variable_selection_requires_reasons_for_dict_entries() -> None:
    store, tmp = make_store()
    store.initialize()
    iv_df = pl.DataFrame({
        "variable": ["v1"], "iv": [0.3], "bin_count": [2],
        "zero_cell_count": [0], "warning_count": [0],
    })
    buf = io.BytesIO()
    iv_df.write_parquet(buf)
    iv_path = store.root / "datasets" / "iv.parquet"
    iv_path.parent.mkdir(parents=True, exist_ok=True)
    iv_path.write_bytes(buf.getvalue())
    iv_art = ArtifactRef(
        artifact_id="iv1", artifact_type="report", role="report",
        path=relative_path(iv_path, store.root),
        physical_hash=physical_hash(iv_path),
        logical_hash=table_logical_hash(iv_df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(iv_art)

    clustering = {"clusters": [{"cluster_id": "c1", "variables": ["v1"], "reason": "Single"}], "warnings": []}
    clust_path = store.root / "artifacts" / "clust.json"
    clust_path.write_text(json.dumps(clustering, sort_keys=True))
    clust_art = ArtifactRef(
        artifact_id="cl1", artifact_type="report", role="report",
        path=relative_path(clust_path, store.root),
        physical_hash=physical_hash(clust_path),
        logical_hash=json_logical_hash(clustering),
        media_type="application/json", metadata={},
    )
    store.register_artifact(clust_art)

    params = {
        "min_iv": 0.02, "max_variables": 15,
        "manual_includes": ["v1"],
        "manual_excludes": [],
    }
    spec = StepSpec(
        step_id="sel", node_type="cardre.variable_selection",
        node_version="1", category="selection",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[iv_art, clust_art],
        validated_params=params, runtime_metadata={},
    )
    node = VariableSelectionNode()
    with pytest.raises(ValueError):
        node.run(ctx)
