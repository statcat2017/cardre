"""Tests for champion assignment service (v2)."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
import cardre.services.champion_service as champion_service
from cardre.store.branch_repo import BranchRepository
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.plan_repo import PlanRepository

pytestmark = pytest.mark.unit


def _setup_basic_fixture(store):
    """Create project, plan, branches, comparison, and snapshot."""
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "test", utc_now_iso(), "0.2.0"),
    )
    plan_repo = PlanRepository(store)
    plan_id = plan_repo.create_plan(project_id, "test-plan")
    pv_id = plan_repo.create_version(plan_id, [], description="v1")

    branches_repo = BranchRepository(store)
    baseline_id = branches_repo.create_branch(
        project_id, plan_id, "baseline", "baseline",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="Baseline.",
    )
    challenger_id = branches_repo.create_branch(
        project_id, plan_id, "challenger", "challenger",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="Challenger.",
    )

    # Create an artifact for the snapshot to reference
    artifact_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, "branch_comparison", "comparison", "/tmp/comp.json",
         "abc", "def", "application/json", utc_now_iso()),
    )

    # Create comparison via repo
    comparison_repo = ComparisonRepository(store)
    comparison_id = comparison_repo.create_comparison(
        project_id=project_id,
        plan_id=plan_id,
        baseline_branch_id=baseline_id,
        created_reason="Test.",
    )
    comparison_repo.add_challenger_branch(comparison_id, challenger_id, position=0)

    # Create snapshot via repo
    snapshot_id = comparison_repo.create_snapshot(
        comparison_id=comparison_id,
        project_id=project_id,
        plan_id=plan_id,
        comparison_artifact_id=artifact_id,
        readiness={"ready": True, "missing": []},
        created_reason="Test snapshot",
    )

    # Add source plan versions
    comparison_repo.add_snapshot_plan_version(snapshot_id, pv_id, branch_id=baseline_id)
    comparison_repo.add_snapshot_plan_version(snapshot_id, pv_id, branch_id=challenger_id)

    # Update comparison with latest snapshot
    store.execute(
        "UPDATE branch_comparisons SET latest_snapshot_id = ?, latest_ready = 1 WHERE comparison_id = ?",
        (snapshot_id, comparison_id),
    )

    return {
        "project_id": project_id,
        "plan_id": plan_id,
        "pv_id": pv_id,
        "baseline_id": baseline_id,
        "challenger_id": challenger_id,
        "comparison_id": comparison_id,
        "snapshot_id": snapshot_id,
        "artifact_id": artifact_id,
    }


class TestAssignChampion:
    def test_assign_champion_success(self, store):
        fix = _setup_basic_fixture(store)

        result = champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["challenger_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            scope_type="project",
            scope_key="default",
            assigned_reason="Best performing model.",
        )

        assert result["champion_assignment_id"] is not None
        assert result["champion_branch_id"] == fix["challenger_id"]
        assert result["assigned_reason"] == "Best performing model."
        assert result["previous_champion_branch_id"] is None

    def test_assign_champion_empty_reason(self, store):
        fix = _setup_basic_fixture(store)
        with pytest.raises(ValueError, match="CHAMPION_REASON_REQUIRED"):
            champion_service.assign_champion(
                store,
                project_id=fix["project_id"],
                plan_id=fix["plan_id"],
                branch_id=fix["challenger_id"],
                comparison_id=fix["comparison_id"],
                comparison_snapshot_id=fix["snapshot_id"],
                assigned_reason="",
            )

    def test_assign_champion_branch_not_found(self, store):
        fix = _setup_basic_fixture(store)
        with pytest.raises(ValueError, match="CHAMPION_BRANCH_NOT_FOUND"):
            champion_service.assign_champion(
                store,
                project_id=fix["project_id"],
                plan_id=fix["plan_id"],
                branch_id="nonexistent",
                comparison_id=fix["comparison_id"],
                comparison_snapshot_id=fix["snapshot_id"],
                assigned_reason="Should fail.",
            )

    def test_assign_champion_branch_inactive(self, store):
        fix = _setup_basic_fixture(store)
        # Deactivate the branch
        store.execute(
            "UPDATE plan_branches SET status = 'archived' WHERE branch_id = ?",
            (fix["challenger_id"],),
        )
        with pytest.raises(ValueError, match="CHAMPION_BRANCH_INACTIVE"):
            champion_service.assign_champion(
                store,
                project_id=fix["project_id"],
                plan_id=fix["plan_id"],
                branch_id=fix["challenger_id"],
                comparison_id=fix["comparison_id"],
                comparison_snapshot_id=fix["snapshot_id"],
                assigned_reason="Should fail.",
            )

    def test_assign_champion_comparison_not_found(self, store):
        fix = _setup_basic_fixture(store)
        with pytest.raises(ValueError, match="COMPARISON_NOT_FOUND"):
            champion_service.assign_champion(
                store,
                project_id=fix["project_id"],
                plan_id=fix["plan_id"],
                branch_id=fix["challenger_id"],
                comparison_id="nonexistent",
                comparison_snapshot_id=fix["snapshot_id"],
                assigned_reason="Should fail.",
            )

    def test_assign_champion_supersedes_previous(self, store):
        fix = _setup_basic_fixture(store)

        # Assign first champion
        first = champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["challenger_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            assigned_reason="First champion.",
        )

        # Assign second champion with baseline branch
        second = champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["baseline_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            assigned_reason="Superseding champion.",
        )

        assert second["previous_champion_branch_id"] == first["champion_assignment_id"]

        # First should be superseded
        row = store.execute(
            "SELECT superseded_at FROM champion_assignments WHERE champion_assignment_id = ?",
            (first["champion_assignment_id"],),
        ).fetchone()
        assert row is not None
        assert row["superseded_at"] is not None


class TestGetChampion:
    def test_get_champion_returns_active(self, store):
        fix = _setup_basic_fixture(store)
        champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["challenger_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            assigned_reason="Get test.",
        )

        champ = champion_service.get_champion(store, fix["plan_id"])
        assert champ is not None
        assert champ["champion_branch_id"] == fix["challenger_id"]

    def test_get_champion_no_assignment(self, store):
        champ = champion_service.get_champion(store, "nonexistent-plan")
        assert champ is None


class TestSupersedeChampionForBranch:
    def test_supersedes_when_head_advances(self, store):
        fix = _setup_basic_fixture(store)
        champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["challenger_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            assigned_reason="Will be superseded.",
        )

        # Advance branch head to a new plan version
        new_pv_id = PlanRepository(store).create_version(fix["plan_id"], [], description="v2")

        champion_service.supersede_champion_for_branch(store, fix["challenger_id"], new_pv_id)

        # Champion should be superseded
        assignment = BranchRepository(store).get_champion_assignment_by_branch(fix["challenger_id"])
        # Since it's superseded, get_champion_assignment_by_branch returns None
        # (because it filters WHERE superseded_at IS NULL)
        assert assignment is None

    def test_noop_when_same_version(self, store):
        fix = _setup_basic_fixture(store)
        champion_service.assign_champion(
            store,
            project_id=fix["project_id"],
            plan_id=fix["plan_id"],
            branch_id=fix["challenger_id"],
            comparison_id=fix["comparison_id"],
            comparison_snapshot_id=fix["snapshot_id"],
            assigned_reason="Will stay.",
        )

        # Call with same plan version — should be a no-op
        champion_service.supersede_champion_for_branch(store, fix["challenger_id"], fix["pv_id"])

        # Champion should still be active
        assignment = BranchRepository(store).get_champion_assignment_by_branch(fix["challenger_id"])
        assert assignment is not None
