from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso


class TestRunRepo:
    def test_get_nonexistent_run(self, store):
        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get("nonexistent")
        assert run is None

    def test_create_and_get_run(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        run_id = repo.create(pv_id, run_scope="full_plan", force=True)
        run = repo.get(run_id)
        assert run is not None
        assert run["status"] == "running"
        assert run["run_scope"] == "full_plan"

    def test_transition_updates_status(self, store):
        from cardre.domain.run import RunStatus
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = repo.create(pv_id)
        repo.transition(run_id, RunStatus.INTERRUPTED)
        run = repo.get(run_id)
        assert run["status"] == "interrupted"

    def test_finish_updates_status(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        run_id = repo.create(pv_id)
        repo.finish(run_id, "succeeded")
        run = repo.get(run_id)
        assert run["status"] == "succeeded"
        assert run["finished_at"] is not None

    def test_transition_returns_false_when_not_running(self, store):
        from cardre.domain.run import RunStatus
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = repo.create(pv_id)
        # First transition succeeds
        assert repo.transition(run_id, RunStatus.SUCCEEDED)
        # Second transition returns False — run is already succeeded
        assert not repo.transition(run_id, RunStatus.FAILED)

    def test_transition_rejects_illegal_move(self, store):
        from cardre.domain.run import RunStatus
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = repo.create(pv_id)
        import pytest
        with pytest.raises(ValueError, match="Invalid run state transition"):
            repo.transition(run_id, RunStatus.CREATED)

    def test_transition_expected_from_guards(self, store):
        from cardre.domain.run import RunStatus
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = repo.create(pv_id)
        # First transition to SUCCEEDED
        assert repo.transition(run_id, RunStatus.SUCCEEDED)
        # Now try to transition from RUNNING — SQL won't match (run is SUCCEEDED)
        assert not repo.transition(run_id, RunStatus.FAILED, expected_from=(RunStatus.RUNNING,))

    def test_list_for_plan_version_all(self, store):
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        runs = repo.list_for_plan_version()
        assert isinstance(runs, list)

    def test_get_step_from_run(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            ("step-a", pv_id, "step-a"),
        )
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        run_id = repo.create(pv_id)
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, "step-a", pv_id, now, now),
        )
        step = repo.get_step(rs_id)
        assert step is not None
        assert step["step_id"] == "step-a"

        missing = repo.get_step("nonexistent")
        assert missing is None

    def test_diagnostics_round_trip(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        run_id = repo.create(pv_id)
        repo.append_diagnostic(run_id, {
            "code": "TEST_DIAG", "message": "test", "severity": "error",
            "extra_field": "val",
        })
        diags = repo.get_diagnostics(run_id)
        assert len(diags) == 1
        assert diags[0]["code"] == "TEST_DIAG"
        assert diags[0]["extra_field"] == "val"

    def test_run_repo_empty_queries(self, store):
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        assert repo.get("nonexistent") is None
        assert repo.get_active_step("nonexistent") is None
        assert repo.get_latest_successful_id_for_plan("nonexistent") is None
        assert repo.get_step("nonexistent") is None
        assert repo.get_latest_successful_step_across_plan("nonexistent", "step") is None
        assert repo.get_latest_successful_id("nonexistent") is None

    def test_run_repo_set_active_step(self, store):
        from cardre.store.run_repo import RunRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        repo = RunRepository(store)
        run_id = repo.create(pv_id)
        assert repo.get_active_step(run_id) is None
        repo.set_active_step(run_id, "step-a")
        assert repo.get_active_step(run_id) == "step-a"
        repo.set_active_step(run_id, None)
        assert repo.get_active_step(run_id) is None

    def test_run_step_repo_latest_successful(self, store):
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
            ("step-x", pv_id, "step-x"),
        )
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)
        run_repo.finish(run_id, "succeeded")
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, "step-x", pv_id, now, now),
        )
        rs_repo = RunStepRepository(store)
        rs = rs_repo.get_latest_successful_step(pv_id, "step-x")
        assert rs is not None
        assert rs.step_id == "step-x"

        rs_none = rs_repo.get_latest_successful_step("nonexistent-pv", "step-x")
        assert rs_none is None

    def test_run_step_repo_get_and_get_for_run(self, store):
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = RunRepository(store).create(pv_id)
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, 's1', ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, pv_id, now, now),
        )
        rs_repo = RunStepRepository(store)
        rs = rs_repo.get(rs_id)
        assert rs is not None
        assert rs.step_id == "s1"
        assert rs_repo.get("nonexistent") is None

        all_steps = rs_repo.get_for_run(run_id)
        assert len(all_steps) == 1
        assert rs_repo.get_for_run("nonexistent") == []


class TestStepRepo:
    def _seed_project_and_plan(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        return project_id, plan_id, pv_id

    def test_get_steps_empty(self, store):
        from cardre.store.step_repo import StepRepository
        repo = StepRepository(store)
        steps = repo.get_steps("nonexistent")
        assert steps == []

    def test_insert_and_get_edges(self, store):
        _, _, pv_id = self._seed_project_and_plan(store)
        for sid in ("parent-a", "child-b", "child-c"):
            store.execute(
                "INSERT OR IGNORE INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', 'h', '', 0, ?)",
                (sid, pv_id, sid),
            )
        from cardre.store.step_repo import StepRepository
        repo = StepRepository(store)
        repo.insert_edge(pv_id, "parent-a", "child-b", edge_order=0)
        repo.insert_edge(pv_id, "parent-a", "child-c", edge_order=1)
        parent_edges = repo.get_parent_edges(pv_id, "child-b")
        assert len(parent_edges) == 1
        assert parent_edges[0]["parent_step_id"] == "parent-a"
        child_edges = repo.get_child_edges(pv_id, "parent-a")
        assert len(child_edges) == 2
        assert child_edges[0]["edge_order"] == 0

    def test_get_distinct_node_types(self, store):
        project_id, _, pv_id = self._seed_project_and_plan(store)
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
            ("s1", pv_id, "s1"),
        )
        from cardre.store.step_repo import StepRepository
        repo = StepRepository(store)
        types = repo.get_distinct_node_types(project_id)
        assert any(t["node_type"] == "cardre.noop" for t in types)

    def test_get_all_edges(self, store):
        _, _, pv_id = self._seed_project_and_plan(store)
        for sid in ("a", "b"):
            store.execute(
                "INSERT OR IGNORE INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', 'h', '', 0, ?)",
                (sid, pv_id, sid),
            )
        from cardre.store.step_repo import StepRepository
        repo = StepRepository(store)
        repo.insert_edge(pv_id, "a", "b", 0)
        all_edges = repo.get_all_edges(pv_id)
        assert len(all_edges) == 1
        assert all_edges[0]["parent_step_id"] == "a"
        assert all_edges[0]["child_step_id"] == "b"


class TestBranchRepo:
    def test_get_nonexistent_branch(self, store):
        from cardre.store.branch_repo import BranchRepository
        branch = BranchRepository(store).get_branch("nonexistent")
        assert branch is None

    def test_get_plan_version_ids(self, store):
        from cardre.store.branch_repo import BranchRepository
        repo = BranchRepository(store)
        ids = repo.get_plan_version_ids("nonexistent-branch")
        assert ids == []

    def test_get_step_map_empty(self, store):
        from cardre.store.branch_repo import BranchRepository
        step_map = BranchRepository(store).get_step_map("nonexistent-branch", "nonexistent-pv")
        assert step_map == []

    def test_create_and_list_branches(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.branch_repo import BranchRepository
        repo = BranchRepository(store)
        branch_id = repo.create_branch(
            project_id, plan_id, "test-branch", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
            branch_point_step_id="step-a",
        )
        branch = repo.get_branch(branch_id)
        assert branch is not None
        assert branch["name"] == "test-branch"
        assert branch["branch_type"] == "challenger"

        branches = repo.list(project_id=project_id)
        assert len(branches) >= 1

        branches_by_plan = repo.list(project_id=project_id, plan_id=plan_id)
        assert len(branches_by_plan) >= 1

        branches_by_type = repo.list(project_id=project_id, branch_type="challenger")
        assert len(branches_by_type) >= 1
        branches_by_wrong_type = repo.list(project_id=project_id, branch_type="baseline")
        assert len(branches_by_wrong_type) == 0

    def test_create_step_map_and_get(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.branch_repo import BranchRepository
        repo = BranchRepository(store)
        branch_id = repo.create_branch(
            project_id, plan_id, "step-map-test", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        repo.create_step_map(branch_id, pv_id, "canon-a", "step-a",
                             is_shared_upstream=True, is_branch_owned=False)
        step_map = repo.get_step_map(branch_id, pv_id)
        assert len(step_map) == 1
        assert step_map[0]["canonical_step_id"] == "canon-a"
        assert step_map[0]["step_id"] == "step-a"
        assert step_map[0]["is_shared_upstream"] == 1
        assert step_map[0]["is_branch_owned"] == 0

    def test_evidence_repo_edge_cases(self, store):
        from cardre.store.evidence_repo import EvidenceRepository
        repo = EvidenceRepository(store)
        assert repo.get_edge_for_child_parent("pv", "child", "parent") is None
        assert repo.get_edges_for_plan_step("pv", "step") == []

    def test_project_registry_edge_cases(self, tmp_path):
        from cardre.store.project_registry import ProjectRegistry
        registry = ProjectRegistry(tmp_path / "registry.json")
        assert registry.list_all() == {}
        assert registry.resolve_root("nonexistent") is None

    def test_project_repo_edge_cases(self, store):
        from cardre.store.project_repo import ProjectRepository
        repo = ProjectRepository(store)
        pid = repo.create("Test")
        p = repo.get(pid)
        assert p is not None
        assert repo.get("nonexistent") is None
        projects = repo.list_all()
        assert any(x["project_id"] == pid for x in projects)

    def test_comparison_repo_edge_cases(self, store):
        from cardre.store.comparison_repo import ComparisonRepository
        repo = ComparisonRepository(store)
        assert repo.get_comparison("nonexistent") is None
        assert repo.get_challenger_branches("nonexistent") == []
        assert repo.get_snapshot_plan_versions("nonexistent") == []
        assert repo.list_for_project("nonexistent") == []

    def test_branch_repo_list_with_status(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.branch_repo import BranchRepository
        repo = BranchRepository(store)
        repo.create_branch(project_id, plan_id, "test", "challenger",
                           base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test")
        branches = repo.list(project_id=project_id, status="active")
        assert len(branches) >= 1

    def test_branch_repo_update_head(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.branch_repo import BranchRepository
        repo = BranchRepository(store)
        branch_id = repo.create_branch(
            project_id, plan_id, "head-test", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
        )
        new_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 2, 0, ?)",
            (new_pv_id, plan_id, now),
        )
        repo.update_head(branch_id, new_pv_id)
        branch = repo.get_branch(branch_id)
        assert branch["head_plan_version_id"] == new_pv_id

    def test_branch_repo_champion_and_comparison_methods(self, store):
        from cardre.store.champion_repo import ChampionRepository
        from cardre.store.comparison_repo import ComparisonRepository
        champion_repo = ChampionRepository(store)
        assert champion_repo.get_champion_assignment_for_project("nonexistent") is None
        assert champion_repo.get_champion_assignment("nonexistent-plan") is None
        assert champion_repo.get_champion_assignment("nonexistent-plan", champion_branch_id="b1") is None
        assert champion_repo.get_champion_assignment_by_branch("nonexistent-branch") is None
        comparison_repo = ComparisonRepository(store)
        assert comparison_repo.get_comparison("nonexistent") is None
        assert comparison_repo.get_comparison_snapshot("nonexistent") is None
        assert comparison_repo.get_comparison_snapshots("nonexistent") == []

    def test_comparison_repo_full_lifecycle(self, store):
        from cardre.store.comparison_repo import ComparisonRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.branch_repo import BranchRepository
        branch_repo = BranchRepository(store)
        baseline_id = branch_repo.create_branch(
            project_id, plan_id, "baseline", "baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
        )
        challenger_id = branch_repo.create_branch(
            project_id, plan_id, "challenger", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
        )

        repo = ComparisonRepository(store)
        comp_id = repo.create_comparison(
            project_id=project_id, plan_id=plan_id, baseline_branch_id=baseline_id,
        )
        repo.add_challenger_branch(comp_id, challenger_id, position=0)

        challengers = repo.get_challenger_branches(comp_id)
        assert len(challengers) == 1
        assert challengers[0]["branch_id"] == challenger_id

        # Create an artifact for the snapshot
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
            "media_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("comp-art-1", "comparison", "comparison", "/tmp/comp.json", "ph", "lh", "application/json", now),
        )
        snapshot_id = repo.create_snapshot(
            comparison_id=comp_id, project_id=project_id, plan_id=plan_id,
            comparison_artifact_id="comp-art-1",
        )
        assert snapshot_id is not None

        snapshots = repo.get_comparison_snapshots(comp_id)
        assert len(snapshots) == 1

        snapshot = repo.get_comparison_snapshot(snapshot_id)
        assert snapshot is not None

        repo.add_snapshot_plan_version(snapshot_id, pv_id, branch_id=challenger_id)
        versions = repo.get_snapshot_plan_versions(snapshot_id)
        assert len(versions) == 1


class TestSchemaMigration:
    def test_v100_store_migrated_to_v101_adds_active_step_id(self, tmp_path):
        """A store created at schema version 100 is migrated to 101 on open,
        adding the ``active_step_id`` column to the ``runs`` table."""
        from cardre.store.db import ProjectStore
        from cardre.store.schema import V2_STORE_SCHEMA_FAMILY

        store_root = tmp_path / "v100.cardre"
        store_root.mkdir(parents=True)
        (store_root / "cardre.sqlite").touch()

        conn = __import__("sqlite3").connect(str(store_root / "cardre.sqlite"))
        conn.row_factory = __import__("sqlite3").Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.isolation_level = None

        conn.execute(
            "CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('schema_family', ?)",
            (V2_STORE_SCHEMA_FAMILY,),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('schema_version', '100')"
        )

        conn.execute(
            "CREATE TABLE runs ("
            "run_id TEXT PRIMARY KEY, plan_version_id TEXT, status TEXT NOT NULL, "
            "run_scope TEXT NOT NULL DEFAULT 'full_plan', branch_id TEXT, "
            "target_step_id TEXT, force INTEGER NOT NULL DEFAULT 0, "
            "requested_by TEXT, request_id TEXT, created_at TEXT NOT NULL, "
            "queued_at TEXT, started_at TEXT NOT NULL, finished_at TEXT, "
            "heartbeat_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, "
            "created_at, started_at) VALUES ('r1', 'pv1', 'running', 'full_plan', 'now', 'now')"
        )
        conn.close()

        store = ProjectStore(store_root)
        store.open()

        from cardre.store.schema import V2_STORE_SCHEMA_VERSION
        assert V2_STORE_SCHEMA_VERSION == 101

        from cardre.store.run_repo import RunRepository
        repo = RunRepository(store)
        assert repo.get_active_step("r1") is None
        repo.set_active_step("r1", "step-x")
        assert repo.get_active_step("r1") == "step-x"

        store.close()
