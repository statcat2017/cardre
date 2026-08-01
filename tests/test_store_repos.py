from __future__ import annotations

import uuid

import pytest

from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStatus


@pytest.fixture
def committed_plan_version(provisioned_project):
    project_id, uow_factory, registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        uow.commit()
    return project_id, plan_id, pv_id, uow_factory, root


class TestRunRepo:
    def test_get_nonexistent_run(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            run = uow.runs.get("nonexistent")
        assert run is None

    def test_create_and_get_run(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id, run_scope="full_plan", force=True)
            run = uow.runs.get(run_id)
            assert run is not None
            assert run.status == "created"
            assert run.run_scope == "full_plan"

    def test_transition_updates_status(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            assert uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
            assert uow.runs.transition(run_id, RunStatus.INTERRUPTED)
            run = uow.runs.get(run_id)
            assert run.status == "interrupted"

    def test_finish_updates_status(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            assert uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
            assert uow.runs.transition(run_id, RunStatus.SUCCEEDED)
            run = uow.runs.get(run_id)
            assert run.status == "succeeded"
            assert run.finished_at is not None

    def test_transition_returns_false_when_not_running(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            assert uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
            assert uow.runs.transition(run_id, RunStatus.SUCCEEDED)
            assert not uow.runs.transition(run_id, RunStatus.FAILED)

    def test_transition_rejects_illegal_move(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            with pytest.raises(ValueError, match="Invalid run state transition"):
                uow.runs.transition(run_id, RunStatus.CREATED)

    def test_transition_expected_from_guards(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            assert uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
            assert uow.runs.transition(run_id, RunStatus.SUCCEEDED)
            assert not uow.runs.transition(run_id, RunStatus.FAILED, expected_from=(RunStatus.RUNNING,))

    def test_list_for_plan_version_all(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            runs = uow.runs.list_for_plan_version()
        assert isinstance(runs, list)

    def test_get_step_from_run(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        now = utc_now_iso()
        with uow_factory.for_project(project_id) as uow:
            uow._conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
                ("step-a", pv_id, "step-a"),
            )
            run_id = uow.runs.create(pv_id)
            rs_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (rs_id, run_id, "step-a", pv_id, now, now),
            )
            step = uow.run_steps.get(rs_id)
            assert step is not None
            assert step.step_id == "step-a"
            assert uow.run_steps.get("nonexistent") is None

    def test_diagnostics_round_trip(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            uow.runs.append_diagnostic(run_id, {
                "code": "TEST_DIAG", "message": "test", "severity": "error",
                "extra_field": "val",
            })
            diags = uow.runs.get_diagnostics(run_id)
            assert len(diags) == 1
            assert diags[0]["code"] == "TEST_DIAG"
            assert diags[0]["extra_field"] == "val"

    def test_run_repo_empty_queries(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            assert uow.runs.get("nonexistent") is None
            assert uow.runs.get_active_step("nonexistent") is None
            assert uow.runs.get_latest_successful_id_for_plan("nonexistent") is None
            assert uow.run_steps.get("nonexistent") is None
            assert uow.runs.get_latest_successful_step_across_plan("nonexistent", "step") is None
            assert uow.runs.get_latest_successful_id("nonexistent") is None

    def test_run_repo_set_active_step(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            assert uow.runs.get_active_step(run_id) is None
            uow.runs.set_active_step(run_id, "step-a")
            assert uow.runs.get_active_step(run_id) == "step-a"
            uow.runs.set_active_step(run_id, None)
            assert uow.runs.get_active_step(run_id) is None

    def test_run_step_repo_latest_successful(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        now = utc_now_iso()
        with uow_factory.for_project(project_id) as uow:
            uow._conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
                ("step-x", pv_id, "step-x"),
            )
            run_id = uow.runs.create(pv_id)
            assert uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
            assert uow.runs.transition(run_id, RunStatus.SUCCEEDED)
            rs_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (rs_id, run_id, "step-x", pv_id, now, now),
            )
            rs = uow.run_steps.get_latest_successful_step(pv_id, "step-x")
            assert rs is not None
            assert rs.step_id == "step-x"
            assert uow.run_steps.get_latest_successful_step("nonexistent-pv", "step-x") is None

    def test_run_step_repo_get_and_get_for_run(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        now = utc_now_iso()
        with uow_factory.for_project(project_id) as uow:
            run_id = uow.runs.create(pv_id)
            rs_id = str(uuid.uuid4())
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, 's1', ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (rs_id, run_id, pv_id, now, now),
            )
            rs = uow.run_steps.get(rs_id)
            assert rs is not None
            assert rs.step_id == "s1"
            assert uow.run_steps.get("nonexistent") is None
            all_steps = uow.run_steps.get_for_run(run_id)
            assert len(all_steps) == 1
            assert uow.run_steps.get_for_run("nonexistent") == []


class TestStepRepo:
    def test_get_steps_empty(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            steps = uow.steps.get_steps("nonexistent")
        assert steps == []

    def test_insert_and_get_edges(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            for sid in ("parent-a", "child-b", "child-c"):
                uow._conn.execute(
                    "INSERT OR IGNORE INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                    " params_json, params_hash, branch_label, position, canonical_step_id) "
                    "VALUES (?, ?, 'test', '1', 'fit', '{}', 'h', '', 0, ?)",
                    (sid, pv_id, sid),
                )
            uow._conn.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, 0)",
                (pv_id, "parent-a", "child-b"),
            )
            uow._conn.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, 1)",
                (pv_id, "parent-a", "child-c"),
            )
            parent_edges = uow.steps.get_parent_edges(pv_id, "child-b")
            assert len(parent_edges) == 1
            assert parent_edges[0]["parent_step_id"] == "parent-a"
            child_edges = uow.steps.get_child_edges(pv_id, "parent-a")
            assert len(child_edges) == 2
            assert child_edges[0]["edge_order"] == 0

    def test_get_distinct_node_types(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            uow._conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
                ("s1", pv_id, "s1"),
            )
            types = uow.steps.get_distinct_node_types(project_id)
        assert any(t["node_type"] == "cardre.noop" for t in types)

    def test_get_all_edges(self, committed_plan_version):
        project_id, _, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            for sid in ("a", "b"):
                uow._conn.execute(
                    "INSERT OR IGNORE INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                    " params_json, params_hash, branch_label, position, canonical_step_id) "
                    "VALUES (?, ?, 'test', '1', 'fit', '{}', 'h', '', 0, ?)",
                    (sid, pv_id, sid),
                )
            uow._conn.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, 0)",
                (pv_id, "a", "b"),
            )
            all_edges = uow.steps.get_all_edges(pv_id)
            assert len(all_edges) == 1
            assert all_edges[0]["parent_step_id"] == "a"
            assert all_edges[0]["child_step_id"] == "b"


@pytest.mark.governance
class TestBranchRepo:
    def test_get_nonexistent_branch(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            branch = uow.branches.get_branch("nonexistent")
        assert branch is None

    def test_get_plan_version_ids(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            ids = uow.branches.get_plan_version_ids("nonexistent-branch")
        assert ids == []

    def test_get_step_map_empty(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            step_map = uow.branches.get_step_map("nonexistent-branch", "nonexistent-pv")
        assert step_map == []

    def test_create_and_list_branches(self, committed_plan_version):
        project_id, plan_id, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            branch_id = uow.branches.create_branch(
                project_id, plan_id, "test-branch", "challenger",
                base_plan_version_id=pv_id, head_plan_version_id=pv_id,
                created_reason="test",
                branch_point_step_id="step-a",
            )
            branch = uow.branches.get_branch(branch_id)
            assert branch is not None
            assert branch["name"] == "test-branch"
            assert branch["branch_type"] == "challenger"

            branches = uow.branches.list_branches(project_id=project_id)
            assert len(branches) >= 1

            branches_by_plan = uow.branches.list_branches(project_id=project_id, plan_id=plan_id)
            assert len(branches_by_plan) >= 1

            branches_by_type = uow.branches.list_branches(project_id=project_id, branch_type="challenger")
            assert len(branches_by_type) >= 1
            branches_by_wrong_type = uow.branches.list_branches(project_id=project_id, branch_type="baseline")
            assert len(branches_by_wrong_type) == 0

    def test_create_step_map_and_get(self, committed_plan_version):
        project_id, plan_id, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            branch_id = uow.branches.create_branch(
                project_id, plan_id, "step-map-test", "challenger",
                base_plan_version_id=pv_id, head_plan_version_id=pv_id,
                created_reason="test",
            )
            uow.branches.create_step_map(branch_id, pv_id, "canon-a", "step-a",
                                         is_shared_upstream=True, is_branch_owned=False)
            step_map = uow.branches.get_step_map(branch_id, pv_id)
            assert len(step_map) == 1
            assert step_map[0]["canonical_step_id"] == "canon-a"
            assert step_map[0]["step_id"] == "step-a"
            assert step_map[0]["is_shared_upstream"] == 1
            assert step_map[0]["is_branch_owned"] == 0

    def test_comparison_repo_edge_cases(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            assert uow.comparisons.get_comparison("nonexistent") is None
            assert uow.comparisons.get_challenger_branches("nonexistent") == []
            assert uow.comparisons.get_snapshot_plan_versions("nonexistent") == []
            assert uow.comparisons.list_for_project("nonexistent") == []

    def test_branch_repo_list_with_status(self, committed_plan_version):
        project_id, plan_id, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            uow.branches.create_branch(project_id, plan_id, "test", "challenger",
                                       base_plan_version_id=pv_id, head_plan_version_id=pv_id,
                                       created_reason="test")
            branches = uow.branches.list_branches(project_id=project_id, status="active")
            assert len(branches) >= 1

    def test_branch_repo_update_head(self, committed_plan_version):
        project_id, plan_id, pv_id, uow_factory, _ = committed_plan_version
        with uow_factory.for_project(project_id) as uow:
            branch_id = uow.branches.create_branch(
                project_id, plan_id, "head-test", "challenger",
                base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
            )
            new_pv_id = uow.plans.create_version(plan_id, [], is_committed=False)
            uow.branches.update_head(branch_id, new_pv_id)
            branch = uow.branches.get_branch(branch_id)
            assert branch["head_plan_version_id"] == new_pv_id

    def test_branch_repo_champion_and_comparison_methods(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            assert uow.champion.get_champion_assignment_for_project("nonexistent") is None
            assert uow.champion.get_champion_assignment("nonexistent-plan") is None
            assert uow.champion.get_champion_assignment("nonexistent-plan", champion_branch_id="b1") is None
            assert uow.champion.get_champion_assignment_by_branch("nonexistent-branch") is None
            assert uow.comparisons.get_comparison("nonexistent") is None
            assert uow.comparisons.get_comparison_snapshot("nonexistent") is None
            assert uow.comparisons.get_comparison_snapshots("nonexistent") == []

    def test_comparison_repo_full_lifecycle(self, committed_plan_version):
        project_id, plan_id, pv_id, uow_factory, _ = committed_plan_version
        now = utc_now_iso()
        with uow_factory.for_project(project_id) as uow:
            baseline_id = uow.branches.create_branch(
                project_id, plan_id, "baseline", "baseline",
                base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
            )
            challenger_id = uow.branches.create_branch(
                project_id, plan_id, "challenger", "challenger",
                base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
            )

            comp_id = uow.comparisons.create_comparison(
                project_id=project_id, plan_id=plan_id, baseline_branch_id=baseline_id,
                comparison_spec_json="{}",
            )
            uow.comparisons.add_challenger_branch(comp_id, challenger_id, position=0)

            challengers = uow.comparisons.get_challenger_branches(comp_id)
            assert len(challengers) == 1
            assert challengers[0]["branch_id"] == challenger_id

            uow.artifacts.register(ArtifactRef(
                artifact_id="comp-art-1", artifact_type="comparison", role="comparison",
                path="/tmp/comp.json", physical_hash="ph", logical_hash="lh",
                media_type="application/json", created_at=now,
            ))
            snapshot_id = uow.comparisons.create_snapshot(
                comp_id, project_id=project_id, plan_id=plan_id,
                comparison_artifact_id="comp-art-1", readiness_json="{}",
            )
            assert snapshot_id is not None

            snapshots = uow.comparisons.get_comparison_snapshots(comp_id)
            assert len(snapshots) == 1

            snapshot = uow.comparisons.get_comparison_snapshot(snapshot_id)
            assert snapshot is not None

            uow.comparisons.add_snapshot_plan_version(snapshot_id, pv_id, branch_id=challenger_id)
            versions = uow.comparisons.get_snapshot_plan_versions(snapshot_id)
            assert len(versions) == 1


class TestRepoEdgeCases:
    """Generic repository edge-case tests — not governance-related."""

    def test_evidence_repo_edge_cases(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            assert uow.evidence.get_edge_for_child_parent("rs", "parent") is None
            assert uow.evidence.get_edges_for_plan_step("pv", "step") == []

    def test_project_registry_edge_cases(self, tmp_path):
        registry = JsonProjectRegistry(tmp_path / "registry.json")
        assert registry.list_all() == {}
        assert registry.resolve_root("nonexistent") is None

    def test_project_repo_edge_cases(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            pid = uow.projects.create("Test")
            p = uow.projects.get(pid)
            assert p is not None
            assert uow.projects.get("nonexistent") is None
            projects = uow.projects.list_all()
            assert any(x.project_id == pid for x in projects)
