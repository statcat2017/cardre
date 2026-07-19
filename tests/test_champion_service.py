"""Tests for champion_service — assign, get, supersede champion branches.

Covers:
- assign_champion: success, empty rationale, missing/inactive/mismatched branch,
  missing comparison/snapshot, not-ready snapshot, stale snapshot,
  branch not in comparison, superseding previous champion
- get_champion: no assignment, active assignment
- supersede_champion_for_branch: no assignment, same plan version, different plan version
"""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError

pytestmark = pytest.mark.governance


def _seed_branch(store, project_id, plan_id, pv_id, branch_id, name="test-branch", status="active"):
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'challenger', ?, "
        " ?, ?, 'test', ?, ?)",
        (branch_id, project_id, plan_id, name, status, pv_id, pv_id, utc_now_iso(), utc_now_iso()),
    )


def _seed_comparison_with_snapshot(store, project_id, plan_id, pv_id, branch_id, ready=True):
    from cardre.store.comparison_repo import ComparisonRepository

    comp_id = ComparisonRepository(store).create_comparison(
        project_id=project_id, plan_id=plan_id, baseline_branch_id=branch_id,
    )
    ComparisonRepository(store).add_challenger_branch(comp_id, branch_id, position=0)

    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("champ-art-1", "comparison", "comparison", "/tmp/comp.json", "ph", "lh", "application/json", utc_now_iso()),
    )
    snap_id = ComparisonRepository(store).create_snapshot(
        comparison_id=comp_id, project_id=project_id, plan_id=plan_id,
        comparison_artifact_id="champ-art-1",
        readiness={"ready": ready},
    )
    ComparisonRepository(store).add_snapshot_plan_version(snap_id, pv_id, branch_id=branch_id)
    return comp_id, snap_id


class TestAssignChampion:
    def _full_setup(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        branch_id = str(uuid.uuid4())
        _seed_branch(store, project_id, plan_id, pv_id, branch_id)
        comp_id, snap_id = _seed_comparison_with_snapshot(store, project_id, plan_id, pv_id, branch_id)
        return project_id, plan_id, pv_id, branch_id, comp_id, snap_id

    def test_assign_champion_success(self, store):
        from cardre.services.champion_service import assign_champion, get_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)

        result = assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="Best performing model",
        )
        assert result["champion_branch_id"] == branch_id
        assert result["plan_id"] == plan_id
        assert result["previous_champion_branch_id"] is None
        assert result["assigned_reason"] == "Best performing model"

        champ = get_champion(store, plan_id)
        assert champ is not None
        assert champ["champion_branch_id"] == branch_id

    def test_empty_rationale_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        with pytest.raises(CardreError, match="CHAMPION_REASON_REQUIRED"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="",
            )

    def test_missing_branch_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        with pytest.raises(CardreError, match="CHAMPION_BRANCH_NOT_FOUND"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id="nonexistent",
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_inactive_branch_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        store.execute("UPDATE plan_branches SET status = 'closed' WHERE branch_id = ?", (branch_id,))
        with pytest.raises(CardreError, match="CHAMPION_BRANCH_INACTIVE"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_branch_project_mismatch_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        other_project = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (other_project, "Other", utc_now_iso(), "0.2.0"),
        )
        with pytest.raises(CardreError, match="CHAMPION_BRANCH_MISMATCH"):
            assign_champion(
                store, project_id=other_project, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_missing_comparison_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        with pytest.raises(CardreError, match="COMPARISON_NOT_FOUND"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id="nonexistent-comp", comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_missing_snapshot_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        with pytest.raises(CardreError, match="COMPARISON_SNAPSHOT_NOT_FOUND"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id="nonexistent-snap",
                assigned_reason="test",
            )

    def test_not_ready_snapshot_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        # Overwrite snapshot with not-ready
        store.execute(
            "UPDATE branch_comparison_snapshots SET readiness_json = ? WHERE comparison_snapshot_id = ?",
            (json.dumps({"ready": False}), snap_id),
        )
        with pytest.raises(CardreError, match="COMPARISON_NOT_READY"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_stale_snapshot_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        # Advance branch head to a plan version not in the snapshot
        new_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 2, 1, ?)",
            (new_pv_id, plan_id, utc_now_iso()),
        )
        store.execute(
            "UPDATE plan_branches SET head_plan_version_id = ? WHERE branch_id = ?",
            (new_pv_id, branch_id),
        )
        with pytest.raises(CardreError, match="STALE_SNAPSHOT"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_branch_not_in_comparison_raises(self, store):
        from cardre.services.champion_service import assign_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)
        # Create a different branch not in the comparison
        other_branch = str(uuid.uuid4())
        _seed_branch(store, project_id, plan_id, pv_id, other_branch, name="other-branch")
        with pytest.raises(CardreError, match="BRANCH_NOT_IN_COMPARISON"):
            assign_champion(
                store, project_id=project_id, plan_id=plan_id, branch_id=other_branch,
                comparison_id=comp_id, comparison_snapshot_id=snap_id,
                assigned_reason="test",
            )

    def test_supersedes_previous_champion(self, store):
        from cardre.services.champion_service import assign_champion, get_champion
        project_id, plan_id, pv_id, branch_id, comp_id, snap_id = self._full_setup(store)

        # First assignment
        result1 = assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="First champion",
        )
        assert result1["previous_champion_branch_id"] is None

        # Second assignment with same branch should supersede
        result2 = assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="Second champion",
        )
        assert result2["previous_champion_branch_id"] is not None

        # Only the latest should be active
        champ = get_champion(store, plan_id)
        assert champ is not None
        assert champ["assigned_reason"] == "Second champion"


class TestGetChampion:
    def test_no_assignment_returns_none(self, store):
        from cardre.services.champion_service import get_champion
        result = get_champion(store, "nonexistent-plan")
        assert result is None

    def test_returns_active_assignment(self, store):
        from cardre.services.champion_service import assign_champion, get_champion
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        branch_id = str(uuid.uuid4())
        _seed_branch(store, project_id, plan_id, pv_id, branch_id)
        comp_id, snap_id = _seed_comparison_with_snapshot(store, project_id, plan_id, pv_id, branch_id)
        assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="test",
        )
        champ = get_champion(store, plan_id)
        assert champ is not None
        assert champ["champion_branch_id"] == branch_id


class TestSupersedeChampionForBranch:
    def test_no_assignment_does_nothing(self, store):
        from cardre.services.champion_service import supersede_champion_for_branch
        supersede_champion_for_branch(store, "nonexistent-branch", "new-pv")
        # Should not raise

    def test_same_plan_version_does_nothing(self, store):
        from cardre.services.champion_service import (
            assign_champion,
            get_champion,
            supersede_champion_for_branch,
        )
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        branch_id = str(uuid.uuid4())
        _seed_branch(store, project_id, plan_id, pv_id, branch_id)
        comp_id, snap_id = _seed_comparison_with_snapshot(store, project_id, plan_id, pv_id, branch_id)
        assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="test",
        )
        supersede_champion_for_branch(store, branch_id, pv_id)
        champ = get_champion(store, plan_id)
        assert champ is not None  # Still active

    def test_different_plan_version_supersedes(self, store):
        from cardre.services.champion_service import (
            assign_champion,
            get_champion,
            supersede_champion_for_branch,
        )
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        branch_id = str(uuid.uuid4())
        _seed_branch(store, project_id, plan_id, pv_id, branch_id)
        comp_id, snap_id = _seed_comparison_with_snapshot(store, project_id, plan_id, pv_id, branch_id)
        assign_champion(
            store, project_id=project_id, plan_id=plan_id, branch_id=branch_id,
            comparison_id=comp_id, comparison_snapshot_id=snap_id,
            assigned_reason="test",
        )
        new_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 2, 1, ?)",
            (new_pv_id, plan_id, now),
        )
        supersede_champion_for_branch(store, branch_id, new_pv_id)
        champ = get_champion(store, plan_id)
        assert champ is None  # Superseded
