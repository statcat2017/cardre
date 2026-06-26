"""Tests for scorecard variable clustering and selection."""

from __future__ import annotations

import io
import json
import unittest
import uuid
from typing import Any

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
            "num3": [1.1, 2.2, 3.3, 4.4, 5.5],
            "num4": [5.0, 4.0, 3.0, 2.0, 1.0],
            "num5": [0.5, 1.0, 1.5, 2.0, 2.5],
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
            "variable": ["num1", "num2", "num3", "num4", "num5", "cat1"],
            "iv": [0.3, 0.25, 0.2, 0.15, 0.1, 0.05],
            "bin_count": [3, 3, 3, 3, 3, 1],
            "zero_cell_count": [0, 0, 0, 0, 0, 0],
            "warning_count": [0, 0, 0, 0, 0, 0],
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

        params = {
            "method": "correlation_threshold",
            "similarity_metric": "pearson",
            "absolute_correlation": True,
            "threshold": 0.7,
            "input_representation": "raw_train",
            "missing_handling": "pairwise",
            "candidate_limit": 50,
            "representative_rule": "highest_iv",
        }
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
        self.assertEqual(payload["schema_version"], "cardre.variable_clustering_evidence.v1")
        self.assertIn("clusters", payload)
        self.assertIn("singleton_variables", payload)
        self.assertIn("method", payload)
        self.assertIn("input_representation", payload)
        self.assertTrue(len(payload["clusters"]) + len(payload["singleton_variables"]) > 0)


    def test_clustering_produces_representatives(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "bureau_score": [1.0, 2.0, 3.0, 4.0, 5.0],
            "bureau_score_v2": [2.0, 4.0, 6.0, 8.0, 10.0],
            "age": [1.0, 4.0, 9.0, 16.0, 25.0],
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
            "variable": ["bureau_score", "bureau_score_v2", "age"],
            "iv": [0.5, 0.3, 0.1],
            "bin_count": [3, 3, 3],
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

        params = {
            "method": "correlation_threshold",
            "similarity_metric": "pearson",
            "absolute_correlation": True,
            "threshold": 0.6,
            "input_representation": "raw_train",
            "missing_handling": "pairwise",
            "candidate_limit": 50,
            "representative_rule": "highest_iv",
        }
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

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        cluster_vars = set()
        for cl in payload["clusters"]:
            for member in cl["variables"]:
                cluster_vars.add(member["variable"])
        self.assertIn("bureau_score", cluster_vars)
        self.assertIn("bureau_score_v2", cluster_vars)
        for cl in payload["clusters"]:
            for member in cl["variables"]:
                self.assertIn("variable", member)
                self.assertIn("iv", member)
                self.assertIn("missing_rate", member)
            if len(cl["variables"]) > 1:
                self.assertTrue(cl["representative_suggestion"])
                self.assertTrue(cl["representative_reason"].startswith("highest IV"))


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
            "schema_version": "cardre.variable_clustering_evidence.v1",
            "method": "correlation_threshold",
            "input_representation": "raw_train",
            "similarity_metric": "pearson",
            "absolute_correlation": True,
            "threshold": 0.7,
            "missing_handling": "pairwise",
            "candidate_limit": 50,
            "representative_rule": "highest_iv",
            "clusters": [],
            "singleton_variables": ["v1", "v2", "v3", "v4"],
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

        params = {
            "min_iv": 0.02, "max_variables": 15,
            "manual_includes": [], "manual_excludes": [],
            "cluster_representative_rule": "none",
            "cluster_representative_overrides": [],
        }
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

        clustering = {
            "schema_version": "cardre.variable_clustering_evidence.v1",
            "method": "correlation_threshold",
            "input_representation": "raw_train",
            "similarity_metric": "pearson",
            "absolute_correlation": True,
            "threshold": 0.7,
            "missing_handling": "pairwise",
            "candidate_limit": 50,
            "representative_rule": "highest_iv",
            "clusters": [],
            "singleton_variables": ["v1", "v2"],
            "warnings": [],
        }
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

        params = {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "none",
            "cluster_representative_overrides": [],
        }
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

    clustering = {
        "schema_version": "cardre.variable_clustering_evidence.v1",
        "method": "correlation_threshold",
        "input_representation": "raw_train",
        "similarity_metric": "pearson",
        "absolute_correlation": True,
        "threshold": 0.7,
        "missing_handling": "pairwise",
        "candidate_limit": 50,
        "representative_rule": "highest_iv",
        "clusters": [],
        "singleton_variables": ["v1"],
        "warnings": [],
    }
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
        "cluster_representative_rule": "none",
        "cluster_representative_overrides": [],
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


# ======================================================================
# Regression tests for cluster representative rules
# ======================================================================


def _build_clustering_artifact(
    store: ProjectStore,
    cluster_list: list[dict],
    singletons: list[str] | None = None,
    **meta: Any,
) -> ArtifactRef:
    payload = {
        "schema_version": "cardre.variable_clustering_evidence.v1",
        "method": meta.get("method", "correlation_threshold"),
        "input_representation": "raw_train",
        "similarity_metric": "pearson",
        "absolute_correlation": True,
        "threshold": meta.get("threshold", 0.7),
        "missing_handling": "pairwise",
        "candidate_limit": 50,
        "representative_rule": "highest_iv",
        "clusters": cluster_list,
        "singleton_variables": singletons or [],
        "warnings": [],
    }
    clust_path = store.root / "artifacts" / "test-clust-evidence.json"
    clust_path.write_text(json.dumps(payload, sort_keys=True))
    art = ArtifactRef(
        artifact_id="ce_" + uuid.uuid4().hex[:8],
        artifact_type="report", role="report",
        path=relative_path(clust_path, store.root),
        physical_hash=physical_hash(clust_path),
        logical_hash=json_logical_hash(payload),
        media_type="application/json",
        metadata={"schema_version": "cardre.variable_clustering_evidence.v1"},
    )
    store.register_artifact(art)
    return art


def _build_iv_artifact(store: ProjectStore, vars_iv: list[tuple[str, float]]) -> ArtifactRef:
    iv_df = pl.DataFrame({
        "variable": [v for v, _ in vars_iv],
        "iv": [iv for _, iv in vars_iv],
        "bin_count": [3] * len(vars_iv),
        "zero_cell_count": [0] * len(vars_iv),
        "warning_count": [0] * len(vars_iv),
    })
    buf = io.BytesIO()
    iv_df.write_parquet(buf)
    iv_path = store.root / "datasets" / "test-iv-selection.parquet"
    iv_path.parent.mkdir(parents=True, exist_ok=True)
    iv_path.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id="iv_" + uuid.uuid4().hex[:8],
        artifact_type="report", role="report",
        path=relative_path(iv_path, store.root),
        physical_hash=physical_hash(iv_path),
        logical_hash=table_logical_hash(iv_df),
        media_type="application/vnd.apache.parquet",
        metadata={},
    )
    store.register_artifact(art)
    return art


def _run_selection(
    store: ProjectStore, iv_art: ArtifactRef, clust_art: ArtifactRef,
    params: dict[str, Any],
) -> dict[str, Any]:
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
        parent_run_steps=[],
        input_artifacts=[iv_art, clust_art],
        validated_params=params, runtime_metadata={},
    )
    node = VariableSelectionNode()
    output = node.run(ctx)
    return json.loads(store.artifact_path(output.artifacts[0]).read_text())


class TestVariableSelectionClusterRules(unittest.TestCase):

    def test_none_ignores_clusters(self) -> None:
        """rule=none should select all vars passing IV threshold, ignoring cluster groups."""
        store, tmp = make_store()
        store.initialize()
        iv_art = _build_iv_artifact(store, [("v1", 0.5), ("v2", 0.4), ("v3", 0.01)])
        clust_art = _build_clustering_artifact(store, [
            {"cluster_id": "c1", "variables": [{"variable": "v1"}, {"variable": "v2"}],
             "representative_suggestion": "v1", "representative_reason": "highest IV",
             "max_pairwise_abs_corr": 0.95, "notes": []},
        ], singletons=["v3"])
        payload = _run_selection(store, iv_art, clust_art, {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "none",
            "cluster_representative_overrides": [],
        })
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v1", selected_vars)
        self.assertIn("v2", selected_vars)
        self.assertNotIn("v3", selected_vars)

    def test_one_per_cluster_highest_iv(self) -> None:
        """Should select exactly one var per cluster (highest IV)."""
        store, tmp = make_store()
        store.initialize()
        iv_art = _build_iv_artifact(store, [("v1", 0.5), ("v2", 0.3), ("v3", 0.2), ("v4", 0.4)])
        clust_art = _build_clustering_artifact(store, [
            {"cluster_id": "c1", "variables": [{"variable": "v1"}, {"variable": "v2"}],
             "representative_suggestion": "v1", "representative_reason": "highest IV",
             "max_pairwise_abs_corr": 0.9, "notes": []},
            {"cluster_id": "c2", "variables": [{"variable": "v3"}, {"variable": "v4"}],
             "representative_suggestion": "v4", "representative_reason": "highest IV",
             "max_pairwise_abs_corr": 0.8, "notes": []},
        ])
        payload = _run_selection(store, iv_art, clust_art, {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "one_per_cluster_highest_iv",
            "cluster_representative_overrides": [],
        })
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v1", selected_vars)
        self.assertIn("v4", selected_vars)
        self.assertNotIn("v2", selected_vars)
        self.assertNotIn("v3", selected_vars)

    def test_one_per_cluster_lowest_missing(self) -> None:
        """Should select one var per cluster using evidence missing rates."""
        store, tmp = make_store()
        store.initialize()
        iv_art = _build_iv_artifact(store, [("v1", 0.5), ("v2", 0.3)])
        clust_art = _build_clustering_artifact(store, [
            {"cluster_id": "c1",
             "variables": [
                 {"variable": "v1", "iv": 0.5, "missing_rate": 0.1},
                 {"variable": "v2", "iv": 0.3, "missing_rate": 0.01},
             ],
             "representative_suggestion": None, "representative_reason": "",
             "max_pairwise_abs_corr": 0.9, "notes": []},
        ])
        payload = _run_selection(store, iv_art, clust_art, {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "one_per_cluster_lowest_missing",
            "cluster_representative_overrides": [],
        })
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v2", selected_vars, "v2 has lower missing rate (0.01 < 0.1)")
        self.assertNotIn("v1", selected_vars)

    def test_manual_override(self) -> None:
        """Manual override should select the override variable even if not highest IV."""
        store, tmp = make_store()
        store.initialize()
        iv_art = _build_iv_artifact(store, [("v1", 0.5), ("v2", 0.3)])
        clust_art = _build_clustering_artifact(store, [
            {"cluster_id": "c1",
             "variables": [{"variable": "v1"}, {"variable": "v2"}],
             "representative_suggestion": "v1", "representative_reason": "highest IV",
             "max_pairwise_abs_corr": 0.9, "notes": []},
        ])
        payload = _run_selection(store, iv_art, clust_art, {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "manual_override",
            "cluster_representative_overrides": [
                {"cluster_id": "c1", "variable": "v2", "reason": "Business preference"},
            ],
        })
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v2", selected_vars)
        self.assertNotIn("v1", selected_vars)
        decisions = payload.get("cluster_decisions", [])
        self.assertTrue(any(
            d["selected_variable"] == "v2" and "Business preference" in d["reason"]
            for d in decisions
        ))

    def test_one_per_cluster_lowest_missing_zero_rate_wins(self) -> None:
        """A variable with missing_rate=0.0 should be preferred over one with missing_rate=0.01."""
        store, tmp = make_store()
        store.initialize()
        iv_art = _build_iv_artifact(store, [("v1", 0.5), ("v2", 0.3)])
        clust_art = _build_clustering_artifact(store, [
            {"cluster_id": "c1",
             "variables": [
                 {"variable": "v1", "iv": 0.5, "missing_rate": 0.01},
                 {"variable": "v2", "iv": 0.3, "missing_rate": 0.0},
             ],
             "representative_suggestion": None, "representative_reason": "",
             "max_pairwise_abs_corr": 0.9, "notes": []},
        ])
        payload = _run_selection(store, iv_art, clust_art, {
            "min_iv": 0.02, "max_variables": 15,
            "cluster_representative_rule": "one_per_cluster_lowest_missing",
            "cluster_representative_overrides": [],
        })
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v2", selected_vars, "v2 has missing_rate=0.0 and should win over v1's 0.01")
        self.assertNotIn("v1", selected_vars)


# ======================================================================
# Regression tests for clustering behaviour
# ======================================================================

class TestClusteringNodeBehaviours(unittest.TestCase):

    def _run_clustering(
        self, store: ProjectStore, df: pl.DataFrame,
        iv_map: dict[str, float], params: dict[str, Any],
    ) -> dict[str, Any]:
        from cardre.nodes.build.clustering import VariableClusteringNode

        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-clustering-behaviour.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train_cl", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        iv_df = pl.DataFrame({
            "variable": list(iv_map.keys()),
            "iv": list(iv_map.values()),
            "bin_count": [3] * len(iv_map),
            "zero_cell_count": [0] * len(iv_map),
            "warning_count": [0] * len(iv_map),
        })
        if not iv_df.is_empty():
            iv_buf = io.BytesIO()
            iv_df.write_parquet(iv_buf)
            iv_path = store.root / "datasets" / "test-clustering-iv.parquet"
            iv_path.write_bytes(iv_buf.getvalue())
            iv_artifact = ArtifactRef(
                artifact_id="iv_cl", artifact_type="report", role="report",
                path=relative_path(iv_path, store.root),
                physical_hash=physical_hash(iv_path),
                logical_hash=table_logical_hash(iv_df),
                media_type="application/vnd.apache.parquet",
                metadata={},
            )
            store.register_artifact(iv_artifact)
            input_arts = [train_artifact, iv_artifact]
        else:
            input_arts = [train_artifact]

        step_spec = StepSpec(
            step_id="cluster-test", node_type="cardre.variable_clustering",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r_cl", plan_version_id="pv_cl",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=input_arts,
            validated_params=params, runtime_metadata={},
        )
        node = VariableClusteringNode()
        output = node.run(ctx)
        return json.loads(store.artifact_path(output.artifacts[0]).read_text())

    def test_correlation_warnings_preserved(self) -> None:
        """Clustering artifact should contain warnings from low-overlap correlation pairs."""
        store, tmp = make_store()
        store.initialize()

        import numpy as np
        import math
        rng = np.random.default_rng(42)
        n = 100
        nan = float("nan")
        # v3 has only 2 non-null rows, well below minimum_pair_count=50
        vals_v3 = [nan] * n
        vals_v3[0] = 1.0
        vals_v3[1] = 2.0
        df = pl.DataFrame({
            "v1": list(rng.normal(size=n)),
            "v2": list(rng.normal(size=n)),
            "v3": vals_v3,
        })

        payload = self._run_clustering(store, df, {}, {
            "method": "correlation_threshold",
            "threshold": 0.7,
            "candidate_limit": 50,
            "minimum_pair_count": 50,
        })

        warning_messages = [w.get("message", "") for w in payload.get("warnings", [])]
        overlap_warnings = [m for m in warning_messages if "joint non-null rows" in m or "NO_PAIRWISE_OVERLAP" in m]
        self.assertGreater(len(overlap_warnings), 0,
                           msg="Expected at least one correlation-pair warning in the artifact")

    def test_zero_overlap_warning(self) -> None:
        """Zero-overlap pairs should produce explicit NO_PAIRWISE_OVERLAP warnings."""
        store, tmp = make_store()
        store.initialize()

        nan = float("nan")
        df = pl.DataFrame({
            "v1": [1.0, 2.0, 3.0],
            "v2": [nan, nan, nan],
        })

        payload = self._run_clustering(store, df, {}, {
            "method": "correlation_threshold",
            "threshold": 0.5,
            "candidate_limit": 50,
            "minimum_pair_count": 1,
        })

        warnings_list = payload.get("warnings", [])
        no_overlap = [w for w in warnings_list if "NO_PAIRWISE_OVERLAP" in str(w)]
        self.assertGreater(len(no_overlap), 0)

    def test_minimum_pair_count_in_artifact(self) -> None:
        """minimum_pair_count should appear in the clustering artifact metadata and payload."""
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"v1": [1.0, 2.0], "v2": [3.0, 4.0]})

        payload = self._run_clustering(store, df, {}, {
            "method": "correlation_threshold",
            "threshold": 0.5,
            "candidate_limit": 50,
            "minimum_pair_count": 15,
        })

        self.assertEqual(payload.get("minimum_pair_count"), 15)

    def test_validate_params_rejects_invalid_method(self) -> None:
        """An invalid method should produce a validation error."""
        from cardre.nodes.build.clustering import VariableClusteringNode
        node = VariableClusteringNode()
        errors = node.validate_params({"method": "nonexistent"})
        self.assertTrue(any("Unknown method" in e for e in errors))

    def test_validate_params_rejects_invalid_cluster_rule(self) -> None:
        """Invalid cluster_representative_rule should produce a validation error."""
        from cardre.nodes.build.selection import VariableSelectionNode
        node = VariableSelectionNode()
        errors = node.validate_params({
            "cluster_representative_rule": "bogus_value",
        })
        self.assertTrue(any("Unknown" in e for e in errors))

    def test_validate_params_legacy_alias(self) -> None:
        """Legacy 'highest_iv' rule should produce a helpful migration error."""
        from cardre.nodes.build.selection import VariableSelectionNode
        node = VariableSelectionNode()
        errors = node.validate_params({
            "cluster_representative_rule": "highest_iv",
        })
        self.assertTrue(any("has been renamed" in e for e in errors))
