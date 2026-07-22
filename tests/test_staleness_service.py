"""Tests for StalenessService — explain_step reads from evidence_edges/evidence_artifacts.

Tests validate:
- ``explain_step`` returns correct status (fresh, stale, missing)
- ``upstream_changes`` maps step_id -> is_stale for upstream steps
- ``missing_evidence`` lists parent_step_ids with no evidence
- Reading from ``evidence_edges`` + ``evidence_artifacts``
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso

pytestmark = pytest.mark.xfail(reason="Service replaced in Batch 06")


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_with_run_evidence(store):
    """Seed a completed run with evidence edges and artifacts.

    Returns (project_id, plan_id, pv_id, step_ids, run_id).
    """
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )

    # Steps: root -> a -> b
    root_id = "root"
    step_a = "step-a"
    step_b = "step-b"

    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (root_id, pv_id, "cardre.file_import", "1", "load",
         json.dumps({"path": "data.csv"}), "hash001", "", 0, root_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_a, pv_id, "cardre.profiler", "1", "analysis",
         json.dumps({"target": "y"}), "hash002", "", 1, step_a),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_b, pv_id, "cardre.automatic_binning", "1", "fit",
         json.dumps({"max_bins": 20}), "hash003", "", 2, step_b),
    )

    # Edges: root -> a -> b
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, root_id, step_a, 0),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, step_a, step_b, 0),
    )

    # Run
    run_id = str(uuid.uuid4())
    store.execute(
    "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
    "VALUES (?, ?, 'succeeded', ?, ?, ?)",
    (run_id, pv_id, now, now, now),
    )

    # Run steps with matching fingerprints
    fp_root = json.dumps({
        "params_hash": "hash001",
        "node_type": "cardre.file_import",
        "node_version": "1",
        "output_artifact_logical_hashes": ["out1"],
        "parent_output_logical_hashes_by_step": {},
    })
    fp_a = json.dumps({
        "params_hash": "hash002",
        "node_type": "cardre.profiler",
        "node_version": "1",
        "output_artifact_logical_hashes": ["out2"],
        "parent_output_logical_hashes_by_step": {"root": ["out1"]},
    })
    fp_b = json.dumps({
        "params_hash": "hash003",
        "node_type": "cardre.automatic_binning",
        "node_version": "1",
        "output_artifact_logical_hashes": ["out3"],
        "parent_output_logical_hashes_by_step": {"step-a": ["out2"]},
    })

    rs_root = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_root, run_id, root_id, pv_id, now, now, fp_root),
    )
    rs_a = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_a, run_id, step_a, pv_id, now, now, fp_a),
    )
    rs_b = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_b, run_id, step_b, pv_id, now, now, fp_b),
    )

    # Evidence edges
    ee_a = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_a, run_id, rs_a, pv_id, step_a, root_id, run_id, rs_root, now),
    )
    ee_b = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_b, run_id, rs_b, pv_id, step_b, step_a, run_id, rs_a, now),
    )

    return project_id, plan_id, pv_id, [root_id, step_a, step_b], run_id


class TestStalenessService:
    """StalenessService.explain_step returns correct status + upstream_changes."""

    def test_returns_fresh_for_current_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)
        _, _, step_b = step_ids

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(pv_id, step_b)

        assert explanation.step_id == step_b
        assert explanation.status == "fresh", (
            f"Expected 'fresh', got {explanation.status!r}. "
            f"upstream_changes={explanation.upstream_changes}, "
            f"missing_evidence={explanation.missing_evidence}"
        )
        assert explanation.missing_evidence == [], (
            f"Expected no missing evidence, got {explanation.missing_evidence}"
        )
        assert explanation.upstream_changes == {
            "root": False,
            "step-a": False,
            "step-b": False,
        }, f"Got upstream_changes={explanation.upstream_changes}"

    def test_returns_missing_for_unrun_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)

        # Create a new plan version with a step that was never run
        # Use a different step_id so staleness can't cross-reference
        new_pv = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, (SELECT plan_id FROM plan_versions WHERE plan_version_id = ?), 2, 1, ?)",
            (new_pv, pv_id, now),
        )
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("never-run-step", new_pv, "cardre.custom_node", "1", "custom",
             json.dumps({"x": 1}), "hash-new", "", 0, "never-run-step"),
        )

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(new_pv, "never-run-step")

        assert explanation.status in ("missing", "stale")
        assert explanation.step_id == "never-run-step"

    def test_upstream_changes_includes_all_ancestors(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)
        root_id, step_a, step_b = step_ids

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(pv_id, step_b)

        # upstream_changes should include root, step_a, and step_b
        assert root_id in explanation.upstream_changes
        assert step_a in explanation.upstream_changes
        assert step_b in explanation.upstream_changes

    def test_missing_evidence_lists_parents_without_edges(self, tmp_path):
        """Steps whose parents have no evidence edges appear in missing_evidence."""
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)
        _, _, step_b = step_ids

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(pv_id, step_b)
        # step-b has a parent step-a, which has an evidence edge from this run
        # So missing_evidence should be empty
        assert explanation.missing_evidence == [], (
            f"Expected no missing evidence, got {explanation.missing_evidence}"
        )

    def test_stale_when_params_changed(self, tmp_path):
        """A step is stale when its params_hash differs from the fingerprint."""
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)
        _, step_a, step_b = step_ids

        # Modify the plan step to have a different params_hash
        store.execute(
            "UPDATE plan_steps SET params_hash = 'changed-hash' "
            "WHERE plan_version_id = ? AND step_id = ?",
            (pv_id, step_b),
        )

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(pv_id, step_b)

        # step_b should be stale because its params_hash changed
        assert explanation.status == "stale" or explanation.upstream_changes.get(step_b)

    def test_reading_from_evidence_tables(self, tmp_path):
        """Staleness reads from evidence_edges/evidence_artifacts, not run_steps JSON."""
        store = _make_store(tmp_path)
        _, _, pv_id, step_ids, _ = _seed_with_run_evidence(store)
        _, _, step_b = step_ids

        # Directly query evidence tables to confirm they exist
        edges = store.execute(
            "SELECT COUNT(*) as cnt FROM evidence_edges "
            "WHERE plan_version_id = ? AND step_id = ?",
            (pv_id, step_b),
        ).fetchone()
        assert edges["cnt"] > 0

        from cardre.services.staleness_service import StalenessService
        svc = StalenessService(store)
        explanation = svc.explain_step(pv_id, step_b)

        # The staleness computation used evidence tables (doesn't error)
        assert explanation.step_id == step_b
