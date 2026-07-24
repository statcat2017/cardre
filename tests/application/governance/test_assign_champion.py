"""Characterization tests for AssignChampion use case.

Ported from tests/test_champion_service.py. Covers assign_champion behaviors:
success, empty rationale, missing/inactive/mismatched branch, missing
comparison/snapshot, not-ready snapshot, stale snapshot, branch not in
comparison, and superseding a previous champion.

get_champion / supersede_champion_for_branch were read/maintenance helpers
not ported as use cases in Batch 06; champion state is read back via
ChampionRepo for assertions.
"""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.application.governance.assign_champion import AssignChampion, AssignChampionCommand
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError


def _seed_branch(uow, project_id, plan_id, pv_id, branch_id, name="test-branch", status="active"):
    uow._conn.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'challenger', ?, ?, ?, 'test', ?, ?)",
        (branch_id, project_id, plan_id, name, status, pv_id, pv_id, utc_now_iso(), utc_now_iso()),
    )


def _seed_comparison_with_snapshot(uow, project_id, plan_id, pv_id, branch_id, ready=True):
    comp_id = str(uuid.uuid4())
    now = utc_now_iso()
    uow._conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, "
        "physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("champ-art-1", "comparison", "comparison", "/tmp/comp.json",
         "ph", "lh", "application/json", now),
    )
    uow._conn.execute(
        "INSERT INTO branch_comparisons "
        "(comparison_id, project_id, plan_id, baseline_branch_id, "
        " comparison_spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (comp_id, project_id, plan_id, branch_id, json.dumps({}), now),
    )
    uow._conn.execute(
        "INSERT INTO comparison_challenger_branches (comparison_id, branch_id, position) "
        "VALUES (?, ?, ?)",
        (comp_id, branch_id, 0),
    )
    snap_id = str(uuid.uuid4())
    uow._conn.execute(
        "INSERT INTO branch_comparison_snapshots "
        "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
        " comparison_artifact_id, readiness_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (snap_id, comp_id, project_id, plan_id, "champ-art-1",
         json.dumps({"ready": ready}), now),
    )
    uow._conn.execute(
        "INSERT INTO comparison_snapshot_plan_versions "
        "(comparison_snapshot_id, plan_version_id, branch_id) VALUES (?, ?, ?)",
        (snap_id, pv_id, branch_id),
    )
    return comp_id, snap_id


def _full_setup(uow, project_id):
    now = utc_now_iso()
    plan_id = str(uuid.uuid4())
    uow._conn.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    uow._conn.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    branch_id = str(uuid.uuid4())
    _seed_branch(uow, project_id, plan_id, pv_id, branch_id)
    comp_id, snap_id = _seed_comparison_with_snapshot(uow, project_id, plan_id, pv_id, branch_id)
    return project_id, plan_id, pv_id, branch_id, comp_id, snap_id


class TestAssignChampion:
    def test_assign_champion_success(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        result = use_case(AssignChampionCommand(
            project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="Best performing model",
        ))

        assert result.champion_branch_id == branch_id
        assert result.plan_id == plan_id
        assert result.previous_champion_branch_id is None
        assert result.assigned_reason == "Best performing model"

        with uow_factory.for_project(project_id) as uow:
            champ = uow.champion.get_champion_assignment(plan_id)
        assert champ is not None
        assert champ["champion_branch_id"] == branch_id

    def test_empty_rationale_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="CHAMPION_REASON_REQUIRED"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="",
            ))

    def test_missing_branch_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="CHAMPION_BRANCH_NOT_FOUND"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id="nonexistent",
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_inactive_branch_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow._conn.execute(
                "UPDATE plan_branches SET status = 'closed' WHERE branch_id = ?", (branch_id,)
            )
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="CHAMPION_BRANCH_INACTIVE"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_missing_comparison_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="COMPARISON_NOT_FOUND"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id="nonexistent-comp", comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_missing_snapshot_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="COMPARISON_SNAPSHOT_NOT_FOUND"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id="nonexistent-snap",
                assigned_reason="test",
            ))

    def test_not_ready_snapshot_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow._conn.execute(
                "UPDATE branch_comparison_snapshots SET readiness_json = ? "
                "WHERE comparison_snapshot_id = ?",
                (json.dumps({"ready": False}), snap_id),
            )
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="COMPARISON_NOT_READY"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_stale_snapshot_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            new_pv_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
                "VALUES (?, ?, 2, 1, ?)",
                (new_pv_id, plan_id, utc_now_iso()),
            )
            uow._conn.execute(
                "UPDATE plan_branches SET head_plan_version_id = ? WHERE branch_id = ?",
                (new_pv_id, branch_id),
            )
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="STALE_SNAPSHOT"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_branch_not_in_comparison_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            other_branch = str(uuid.uuid4())
            _seed_branch(uow, project_id, plan_id, pv_id, other_branch, name="other-branch")
            uow.commit()

        use_case = AssignChampion(uow_factory)
        with pytest.raises(CardreError, match="BRANCH_NOT_IN_COMPARISON"):
            use_case(AssignChampionCommand(
                project_id=project_id, plan_id=plan_id, branch_id=other_branch,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            ))

    def test_supersedes_previous_champion(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            project_id, plan_id, pv_id, branch_id, comp_id, snap_id = _full_setup(uow, project_id)
            uow.commit()

        use_case = AssignChampion(uow_factory)
        result1 = use_case(AssignChampionCommand(
            project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="First champion",
        ))
        assert result1.previous_champion_branch_id is None

        result2 = use_case(AssignChampionCommand(
            project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="Second champion",
        ))
        assert result2.previous_champion_branch_id is not None

        with uow_factory.for_project(project_id) as uow:
            champ = uow.champion.get_champion_assignment(plan_id)
        assert champ is not None
        assert champ["assigned_reason"] == "Second champion"
