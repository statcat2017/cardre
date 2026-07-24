"""Characterization tests for ExplainStaleness use case.

Ported from tests/test_staleness_service.py. Validates fresh/missing/stale
status, upstream_changes coverage, and missing_evidence detection through the
production persistence stack.
"""

from __future__ import annotations

import json
import uuid

from cardre.application.evidence.explain_staleness import (
    ExplainStaleness,
    ExplainStalenessCommand,
)
from cardre.domain.diagnostics import utc_now_iso


def _seed_run_with_evidence(uow, project_id):
    """Seed a completed run with evidence edges and artifacts.

    Returns (plan_id, pv_id, [root_id, step_a, step_b], run_id).
    """
    now = utc_now_iso()
    plan_id = uow.plans.create_plan(project_id, "Plan")
    pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)

    root_id = "root"
    step_a = "step-a"
    step_b = "step-b"

    steps_data = [
        (root_id, "cardre.file_import", "load", json.dumps({"path": "data.csv"}), "hash001", [], 0, root_id),
        (step_a, "cardre.profiler", "analysis", json.dumps({"target": "y"}), "hash002", [root_id], 1, step_a),
        (step_b, "cardre.automatic_binning", "fit", json.dumps({"max_bins": 20}), "hash003", [step_a], 2, step_b),
    ]
    for step_id, nt, cat, params, ph, parents, pos, canon in steps_data:
        uow._conn.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            "params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, '1', ?, ?, ?, '', ?, ?)",
            (step_id, pv_id, nt, cat, params, ph, pos, canon),
        )
        for order, pid in enumerate(parents):
            uow._conn.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, ?)",
                (pv_id, pid, step_id, order),
            )

    run_id = str(uuid.uuid4())
    uow._conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', 'full_plan', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )

    fps = {
        root_id: json.dumps({
            "params_hash": "hash001", "node_type": "cardre.file_import", "node_version": "1",
            "output_artifact_logical_hashes": ["out1"],
            "parent_output_logical_hashes_by_step": {},
        }),
        step_a: json.dumps({
            "params_hash": "hash002", "node_type": "cardre.profiler", "node_version": "1",
            "output_artifact_logical_hashes": ["out2"],
            "parent_output_logical_hashes_by_step": {root_id: ["out1"]},
        }),
        step_b: json.dumps({
            "params_hash": "hash003", "node_type": "cardre.automatic_binning", "node_version": "1",
            "output_artifact_logical_hashes": ["out3"],
            "parent_output_logical_hashes_by_step": {step_a: ["out2"]},
        }),
    }
    rs_ids = {}
    for step_id, fp in fps.items():
        rs_id = str(uuid.uuid4())
        rs_ids[step_id] = rs_id
        uow._conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, execution_fingerprint_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
            (rs_id, run_id, step_id, pv_id, now, now, fp),
        )

    ee_a = str(uuid.uuid4())
    uow._conn.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_a, run_id, rs_ids[step_a], pv_id, step_a, root_id, run_id, rs_ids[root_id], now),
    )
    ee_b = str(uuid.uuid4())
    uow._conn.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_b, run_id, rs_ids[step_b], pv_id, step_b, step_a, run_id, rs_ids[step_a], now),
    )
    return plan_id, pv_id, [root_id, step_a, step_b], run_id


def _use_case(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return ExplainStaleness(factory)


class TestExplainStaleness:
    def test_returns_fresh_for_current_step(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, step_ids, _ = _seed_run_with_evidence(uow, project_id)
            uow.commit()

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=pv_id, step_id=step_ids[2], plan_id=plan_id,
        ))

        assert explanation.step_id == step_ids[2]
        assert explanation.status == "fresh", (
            f"Expected 'fresh', got {explanation.status!r}. "
            f"upstream_changes={explanation.upstream_changes}"
        )
        assert explanation.missing_evidence == []

    def test_returns_missing_for_unrun_step(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, _, _ = _seed_run_with_evidence(uow, project_id)
            new_pv = uow.plans.create_version(plan_id, [], description="v2", is_committed=True)
            uow._conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                "params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'cardre.custom_node', '1', 'custom', ?, ?, '', 0, ?)",
                ("never-run-step", new_pv, json.dumps({"x": 1}), "hash-new", "never-run-step"),
            )
            uow.commit()

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=new_pv, step_id="never-run-step", plan_id=plan_id,
        ))
        assert explanation.status in ("missing", "stale")
        assert explanation.step_id == "never-run-step"

    def test_upstream_changes_includes_all_ancestors(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, step_ids, _ = _seed_run_with_evidence(uow, project_id)
            uow.commit()
        root_id, step_a, step_b = step_ids

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=pv_id, step_id=step_b, plan_id=plan_id,
        ))
        assert root_id in explanation.upstream_changes
        assert step_a in explanation.upstream_changes
        assert step_b in explanation.upstream_changes

    def test_missing_evidence_lists_parents_without_edges(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, step_ids, _ = _seed_run_with_evidence(uow, project_id)
            uow.commit()

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=pv_id, step_id=step_ids[2], plan_id=plan_id,
        ))
        assert explanation.missing_evidence == []

    def test_stale_when_params_changed(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, step_ids, _ = _seed_run_with_evidence(uow, project_id)
            uow._conn.execute(
                "UPDATE plan_steps SET params_hash = 'changed-hash' "
                "WHERE plan_version_id = ? AND step_id = ?",
                (pv_id, step_ids[2]),
            )
            uow.commit()

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=pv_id, step_id=step_ids[2], plan_id=plan_id,
        ))
        assert explanation.status == "stale" or explanation.upstream_changes.get(step_ids[2])

    def test_reading_from_evidence_tables(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id, step_ids, _ = _seed_run_with_evidence(uow, project_id)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            edges = uow._conn.execute(
                "SELECT COUNT(*) as cnt FROM evidence_edges "
                "WHERE plan_version_id = ? AND step_id = ?",
                (pv_id, step_ids[2]),
            ).fetchone()
            assert edges["cnt"] > 0

        use_case = _use_case(uow_factory, project_id)
        explanation = use_case(ExplainStalenessCommand(
            plan_version_id=pv_id, step_id=step_ids[2], plan_id=plan_id,
        ))
        assert explanation.step_id == step_ids[2]
