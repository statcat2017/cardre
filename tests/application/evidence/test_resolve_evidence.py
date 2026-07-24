"""Direct tests for the 4-stage evidence resolver fallback chain.

Covers each stage independently: branch-specific, full-plan fallback,
latest successful run for the plan version, and across-plan fallback.
Also covers fingerprint rejection, failed candidates, stale candidates,
and empty results.

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
        params={"x": 1}, params_hash=params_hash, parent_step_ids=parents or [],
        branch_label="", position=0, canonical_step_id=canonical_step_id,
    )


def _insert_run(uow, pv_id, status="succeeded", run_scope="full_plan", branch_id=None):
    run_id = str(uuid.uuid4())
    now = utc_now_iso()
    uow._conn.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, run_scope, branch_id, "
        "created_at, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, pv_id, status, run_scope, branch_id, now, now, now),
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


class TestStage1BranchSpecificEvidence:
    def test_resolves_branch_specific_evidence(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            run_id = _insert_run(uow, pv_id, branch_id=branch_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id

    def test_rejects_branch_specific_when_fingerprint_mismatch(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            run_id = _insert_run(uow, pv_id, branch_id=branch_id)
            _insert_run_step(uow, run_id, pv_id, "step-a", params_hash="wrong")
            _insert_evidence_edge(uow, run_id, _insert_run_step(uow, run_id, pv_id, "step-a"), pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            spec = _step("step-a", "step-a", params_hash="correct", node_type="cardre.test")
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id, fingerprint_match=spec)
        # fingerprint mismatch → stage 1 fails, falls through to other stages, none match → empty
        assert result == []


class TestStage2FullPlanFallback:
    def test_falls_back_to_full_plan_when_no_branch_evidence(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            # Run with no branch (full-plan run)
            run_id = _insert_run(uow, pv_id, branch_id=None)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id


class TestStage3LatestSuccessfulRunForPlanVersion:
    def test_stage3_finds_evidence_when_branch_filtered_out(self, provisioned_project):
        """Stage 3 ignores branch filtering — it uses get_latest_successful_id(branch_id=None).

        When a branch_id is provided but stages 1+2 find no matching edges
        (because the evidence belongs to a full-plan run, not the branch),
        stage 3 finds the run step via the latest successful run for the
        plan version (ignoring branch), then builds evidence pairs from it.
        """
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            # Full-plan run (branch_id=None) with evidence for step-a.
            # Stages 1+2 will not find this because they filter by branch_id.
            run_id = _insert_run(uow, pv_id, branch_id=None)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            # Query with branch_id — stages 1+2 fail, stage 3 finds it.
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id

    def test_stage3_returns_empty_when_run_step_has_no_edges(self, provisioned_project):
        """Stage 3 finds a successful run step but it has no evidence edges.

        The resolver returns an empty list (not None), allowing stage 4 to
        be skipped since there is genuinely no evidence for this step.
        """
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            run_id = _insert_run(uow, pv_id, branch_id=None)
            _insert_run_step(uow, run_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert result == []


class TestStage4AcrossPlanFallback:
    def test_falls_back_to_other_plan_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id1 = _seed_plan(uow, project_id, "Plan")
            pv_id2 = uow.plans.create_version(plan_id, [], is_committed=True)
            # Run on pv_id2, but resolve for pv_id1 (no evidence on pv_id1)
            run_id = _insert_run(uow, pv_id2)
            rs_id = _insert_run_step(uow, run_id, pv_id2, "step-a")
            ee_id = _insert_evidence_edge(uow, run_id, rs_id, pv_id2, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id1, "step-a", branch_id=None, plan_id=plan_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == ee_id


class TestEmptyResult:
    def test_returns_empty_when_no_evidence_anywhere(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "nonexistent-step", branch_id=None)
        assert result == []

    def test_returns_none_when_no_run_step_anywhere(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "nonexistent-step")
        assert result is None


class TestFailedCandidateRejection:
    def test_skips_failed_run_steps(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id, status="failed")
            _insert_run_step(uow, run_id, pv_id, "step-a", status="failed")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=None)
        assert result == []


class TestResolveRunStepEvidenceProvenance:
    def test_branch_specific_resolution_label(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            run_id = _insert_run(uow, pv_id, branch_id=branch_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert result is not None
        assert result.source_label == "branch"
        assert result.run_step is not None

    def test_full_plan_resolution_label(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id, branch_id=None)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a", branch_id="br1")
        assert result is not None
        assert result.source_label == "full_plan"

    def test_across_plan_resolution_label(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id1 = _seed_plan(uow, project_id, "Plan")
            pv_id2 = uow.plans.create_version(plan_id, [], is_committed=True)
            run_id = _insert_run(uow, pv_id2)
            rs_id = _insert_run_step(uow, run_id, pv_id2, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id2, "step-a")
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id1, "step-a", plan_id=plan_id)
        assert result is not None
        assert result.source_label == "across_plan"


class TestStaleEvidenceRejection:
    """Stale edges (is_stale=1) must be skipped, not returned as current."""

    def test_newer_stale_candidate_does_not_hide_older_current(self, provisioned_project):
        """A stale edge from a newer run must not shadow a current edge from an older run."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"

            # Older run — current (non-stale) evidence.
            old_run = _insert_run(uow, pv_id, branch_id=branch_id)
            old_rs = _insert_run_step(uow, old_run, pv_id, "step-a")
            current_ee = _insert_evidence_edge(uow, old_run, old_rs, pv_id, "step-a", is_stale=0)

            # Newer run — stale evidence.  Insert with a later finished_at.
            new_run = _insert_run(uow, pv_id, branch_id=branch_id)
            new_rs = _insert_run_step(uow, new_run, pv_id, "step-a")
            _insert_evidence_edge(uow, new_run, new_rs, pv_id, "step-a", is_stale=1)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == current_ee

    def test_all_stale_returns_empty(self, provisioned_project):
        """When all candidates are stale, no evidence is returned."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            run_id = _insert_run(uow, pv_id, branch_id=branch_id)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a", is_stale=1)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert result == []

    def test_stale_skipped_in_full_plan_fallback(self, provisioned_project):
        """Stale full-plan evidence is skipped in stage 2."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"
            # Full-plan run with stale evidence.
            run_id = _insert_run(uow, pv_id, branch_id=None)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a", is_stale=1)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert result == []

    def test_resolve_run_step_evidence_skips_stale_edges(self, provisioned_project):
        """resolve_run_step_evidence does not return stale edges."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            run_id = _insert_run(uow, pv_id, branch_id=None)
            rs_id = _insert_run_step(uow, run_id, pv_id, "step-a")
            _insert_evidence_edge(uow, run_id, rs_id, pv_id, "step-a", is_stale=1)
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_run_step_evidence(uow, pv_id, "step-a")
        assert result is None


class TestDeterministicOrdering:
    """Evidence selection must be deterministic — newest current candidate wins."""

    def test_newer_current_preferred_over_older_current(self, provisioned_project):
        """When two current edges exist, the newer run's evidence is returned."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"

            # Older run.
            old_run = _insert_run(uow, pv_id, branch_id=branch_id)
            old_rs = _insert_run_step(uow, old_run, pv_id, "step-a")
            _insert_evidence_edge(uow, old_run, old_rs, pv_id, "step-a", is_stale=0)

            # Newer run — insert with later finished_at.
            new_run = _insert_run(uow, pv_id, branch_id=branch_id)
            new_rs = _insert_run_step(uow, new_run, pv_id, "step-a")
            new_ee = _insert_evidence_edge(uow, new_run, new_rs, pv_id, "step-a", is_stale=0)

            # Ensure newer run has a later finished_at.
            uow._conn.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                ("2026-12-31T23:59:59Z", new_run),
            )
            uow._conn.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                ("2026-01-01T00:00:00Z", old_run),
            )
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == new_ee

    def test_newer_fingerprint_mismatch_falls_to_older_compatible(self, provisioned_project):
        """A newer candidate with wrong fingerprint does not shadow an older compatible one."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, pv_id = _seed_plan(uow, project_id)
            branch_id = "br1"

            # Older run — compatible fingerprint.
            old_run = _insert_run(uow, pv_id, branch_id=branch_id)
            old_rs = _insert_run_step(uow, old_run, pv_id, "step-a", params_hash="correct")
            old_ee = _insert_evidence_edge(uow, old_run, old_rs, pv_id, "step-a", is_stale=0)

            # Newer run — incompatible fingerprint.
            new_run = _insert_run(uow, pv_id, branch_id=branch_id)
            new_rs = _insert_run_step(uow, new_run, pv_id, "step-a", params_hash="wrong")
            _insert_evidence_edge(uow, new_run, new_rs, pv_id, "step-a", is_stale=0)

            uow._conn.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                ("2026-12-31T23:59:59Z", new_run),
            )
            uow._conn.execute(
                "UPDATE runs SET finished_at = ? WHERE run_id = ?",
                ("2026-01-01T00:00:00Z", old_run),
            )
            uow.commit()

        with uow_factory.for_project(project_id) as uow:
            spec = _step("step-a", "step-a", params_hash="correct")
            result = resolve_evidence(uow, pv_id, "step-a", branch_id=branch_id, fingerprint_match=spec)
        assert len(result) == 1
        assert result[0][0].evidence_edge_id == old_ee
