"""Direct tests for the evidence resolver fallback chain.

Covers each stage: latest successful run for the plan version and across-plan
fallback. Also covers fingerprint rejection, failed candidates, stale
candidates, and empty results.

These tests exercise resolve_evidence and resolve_run_step_evidence
through the production persistence stack.
"""

from __future__ import annotations

import json
import uuid

from cardre.application.evidence.evidence_resolver import (
    resolve_evidence,
    resolve_run_step_evidence,
)
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec


def _step(step_id, canonical_step_id, params_hash="h1", node_type="cardre.test", parents=None):
    return StepSpec(
        step_id=step_id, node_type=node_type, node_version="1", category="fit",
        params={"x": 1}, params_hash=params_hash, parent_step_ids=parents or [], position=0, canonical_step_id=canonical_step_id,
    )


def _insert_run(uow, pv_id, status="succeeded", run_scope="full_plan"):
    run_id = str(uuid.uuid4())
    now = utc_now_iso()
    uow._conn.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, run_scope, "
        "created_at, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, pv_id, status, run_scope, now, now, now),
    )
    return run_id


def _insert_run_step(uow, run_id, pv_id, step_id, params_hash="h1", node_type="cardre.test", status="succeeded"):
    rs_id = str(uuid.uuid4())
    now = utc_now_iso()
    fp = json.dumps({"params_hash": params_hash, "node_type": node_type, "node_version": "1",
                     "output_artifact_logical_hashes": [], "parent_output_logical_hashes_by_step": {}})
    uow._conn.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (rs_id, run_id, step_id, pv_id, status, now, now, fp),
    )
    return rs_id


def _insert_evidence_edge(uow, run_id, rs_id, pv_id, step_id, parent_step_id="parent", is_stale=0):
    ee_id = str(uuid.uuid4())
    now = utc_now_iso()
    uow._conn.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'test', 0, ?, ?)",
        (ee_id, run_id, rs_id, pv_id, step_id, parent_step_id, run_id, rs_id, is_stale, now),
    )
    return ee_id


def _seed_plan(uow, project_id, name="Plan"):
    plan_id = uow.plans.create_plan(project_id, name)
    pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
    return plan_id, pv_id


class TestLatestSuccessfulRunForPlanVersion:
    def test_resolves_evidence_for_plan_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a")
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id

    def test_rejects_when_fingerprint_mismatch(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id)
            _insert_run_step(uow, run_id, pv_id, "step-a", params_hash="wrong")
            _insert_evidence_edge(uow, run_id, _insert_run_step(uow, run_id, pv_id, "step-a"), pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            spec = _step("step-a", "step-a", params_hash="correct", node_type="cardre.test")
            result = resolve_evidence(uow, pv_id, "step-a", fingerprint_match=spec)
        assert result == []

    def test_rejects_edge_with_unsuccessful_source(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)

            run_id = _insert_run(uow, pv_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a", status="succeeded")

            parent_run_id = _insert_run(uow, pv_id, status="failed")
            parent_rs_id = _insert_run_step(uow, parent_run_id, pv_id, "parent", status="failed")

            ee_id = str(uuid.uuid4())
            now = utc_now_iso()
            uow._conn.execute(
                "INSERT INTO evidence_edges "
                "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
                " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'test', 0, 0, ?)",
                (ee_id, run_id, rs_id, pv_id, "step-a", "parent", parent_run_id, parent_rs_id, now),
            )
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a")
        assert result == []

    def test_returns_empty_when_run_step_has_no_edges(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id)
            _insert_run_step(uow, run_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a")
        assert result == []


class TestAcrossPlanFallback:
    def test_falls_back_to_latest_successful_run_across_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id1 = _seed_plan(uow, project_id, name="P")
            pv_id2 = uow.plans.create_version(plan_id, [], is_committed=True)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            run_id = _insert_run(uow, pv_id2)
            rs_id = _insert_run_step(uow, run_id, pv_id2, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id2, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id1, "step-a", plan_id=plan_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id

    def test_returns_empty_when_no_evidence_anywhere(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            uow.commit()
        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "nonexistent-step")
        assert result == []


class TestResolveRunStepEvidence:
    def test_resolves_run_step_evidence(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a")
        assert result is not None
        assert result.run_step_id == rs_id

    def test_skips_stale_edges(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a", is_stale=1)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a")
        # All edges are stale, so the resolver does not resurrect this run step.
        assert result is None

    def test_returns_none_when_no_evidence(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            uow.commit()
        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a")
        assert result is None
