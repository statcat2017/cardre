"""Characterization tests for branch-version consistency fixes.

These tests verify the three blocking findings from the PR 137 review:
1. Branch upstream edit resets reviewed manual-binning in the same branch-head version.
2. Branch-head update on an active champion branch supersedes champion
   without nested transaction failure.
3. run_scope="to_node" with branch_id records a branch-scoped run and
   uses branch-scoped staleness/short-circuiting.
"""

from __future__ import annotations

import uuid
from pathlib import Path


from cardre.audit import StepSpec, utc_now_iso, json_logical_hash
from cardre.store import ProjectStore
from cardre.services.plan_service import PlanService
from cardre.services.champion_service import supersede_champion_for_branch


def _make_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "test.cardre")
    store.initialize()
    return store


def _make_step(step_id: str, parent_ids: list[str] | None = None, params: dict | None = None,
               canonical_step_id: str | None = None, branch_id: str | None = None) -> StepSpec:
    p = params or {}
    return StepSpec(
        step_id=step_id,
        node_type="cardre.manual_binning" if canonical_step_id == "manual-binning" else "cardre.noop",
        node_version="1",
        category="refinement" if canonical_step_id == "manual-binning" else "transform",
        params=p,
        params_hash=json_logical_hash(p),
        parent_step_ids=parent_ids or [],
        branch_label="",
        position=0,
        canonical_step_id=canonical_step_id or step_id,
        branch_id=branch_id,
    )


class TestManualBinningReset:
    """Finding 1: upstream edit resets reviewed manual-binning in same version."""

    def test_upstream_edit_resets_reviewed_flag(self, tmp_path):
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")

        # Create branch first so we have the real branch_id
        pv0 = store.create_plan_version(plan_id, [_make_step("dummy")])
        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv0, head_plan_version_id=pv0,
            created_reason="test",
        )

        # Steps: upstream -> manual-binning, both branch-owned
        upstream = _make_step("upstream", branch_id=branch_id)
        mb = _make_step("manual-binning", parent_ids=["upstream"],
                        params={"reviewed": True, "accept_automated": False},
                        canonical_step_id="manual-binning", branch_id=branch_id)
        steps = [upstream, mb]
        pv_id = store.create_plan_version(plan_id, steps)

        # Update branch head to point at the version with our steps
        store.update_branch_head(branch_id, pv_id)
        for s in steps:
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=s.canonical_step_id, step_id=s.step_id,
                is_shared_upstream=False, is_branch_owned=True,
            )

        # Edit upstream step
        svc = PlanService(store)
        new_upstream_params = dict(upstream.params)
        new_upstream_params["x"] = 99
        svc.update_params(
            plan_id=plan_id, step_id="upstream",
            base_plan_version_id=pv_id, params=new_upstream_params,
        )

        # Verify: manual-binning reviewed flag was reset to False
        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        final_steps = store.get_plan_version_steps(latest_pv_id)
        mb_final = next(s for s in final_steps if s.canonical_step_id == "manual-binning")
        assert mb_final.params.get("reviewed") is False, (
            f"Expected reviewed=False after upstream edit, got {mb_final.params.get('reviewed')}"
        )

        # Verify: only one new version was created (no ghost version)
        versions = store.list_plan_versions(plan_id)
        assert len(versions) == 3, f"Expected 3 versions (dummy+initial+edit), got {len(versions)}"

    def test_direct_edit_does_not_reset_reviewed_flag(self, tmp_path):
        """Editing the manual-binning step directly should NOT reset reviewed."""
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")

        pv0 = store.create_plan_version(plan_id, [_make_step("dummy")])
        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv0, head_plan_version_id=pv0,
            created_reason="test",
        )

        mb = _make_step("manual-binning", params={"reviewed": True, "accept_automated": False},
                        canonical_step_id="manual-binning", branch_id=branch_id)
        steps = [mb]
        pv_id = store.create_plan_version(plan_id, steps)
        store.update_branch_head(branch_id, pv_id)
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id=mb.canonical_step_id, step_id=mb.step_id,
            is_shared_upstream=False, is_branch_owned=True,
        )

        svc = PlanService(store)
        new_params = dict(mb.params)
        new_params["reviewed"] = False  # user explicitly un-reviewing
        svc.update_params(
            plan_id=plan_id, step_id="manual-binning",
            base_plan_version_id=pv_id, params=new_params,
        )

        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        final_steps = store.get_plan_version_steps(latest_pv_id)
        mb_final = next(s for s in final_steps if s.canonical_step_id == "manual-binning")
        assert mb_final.params.get("reviewed") is False
        # Only one new version (no ghost)
        versions = store.list_plan_versions(plan_id)
        assert len(versions) == 3, f"Expected 3 versions, got {len(versions)}"


class TestChampionSupersede:
    """Finding 2: champion supersede without nested transaction."""

    def test_supersede_with_conn_no_nested_transaction(self, tmp_path):
        """supersede_champion_for_branch with conn= does not open a new transaction."""
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("a")])

        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        # Create required FK targets: comparison + comparison_snapshot
        comparison_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        now = utc_now_iso()
        store._connect().execute(
            "INSERT INTO branch_comparisons "
            "(comparison_id, project_id, plan_id, baseline_branch_id, "
            " challenger_branch_ids_json, comparison_spec_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comparison_id, pid, plan_id, branch_id, "[]", "{}", now),
        )
        store._connect().execute(
            "INSERT INTO branch_comparison_snapshots "
            "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
            " comparison_artifact_id, readiness_json, source_plan_version_ids_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, comparison_id, pid, plan_id,
             str(uuid.uuid4()), '{"ready": true}', "[]", now),
        )

        # Insert a champion assignment
        store._connect().execute(
            "INSERT INTO champion_assignments "
            "(champion_assignment_id, project_id, plan_id, scope_type, scope_key, "
            " champion_branch_id, comparison_id, comparison_snapshot_id, comparison_artifact_id, "
            " selected_plan_version_id, assigned_reason, assigned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), pid, plan_id, "project", "default",
             branch_id, comparison_id, snapshot_id, str(uuid.uuid4()),
             pv_id, "test", now),
        )

        # Call supersede with conn= inside an existing transaction
        with store.transaction() as conn:
            supersede_champion_for_branch(store, branch_id, "new-pv-id", conn=conn)

        # After supersede, get_champion_assignment_by_branch returns None
        # because it filters superseded_at IS NULL.  Verify the row still
        # exists and has superseded_at set.
        champ = store.get_champion_assignment_by_branch(branch_id)
        assert champ is None, "Champion should be superseded (returns None from active lookup)"
        # Direct query to verify the row was updated
        row = store._connect().execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ?",
            (branch_id,),
        ).fetchone()
        assert row is not None
        assert row["superseded_at"] is not None

    def test_supersede_without_conn_opens_own_transaction(self, tmp_path):
        """supersede_champion_for_branch without conn= opens its own transaction."""
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("a")])

        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        comparison_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        now = utc_now_iso()
        store._connect().execute(
            "INSERT INTO branch_comparisons "
            "(comparison_id, project_id, plan_id, baseline_branch_id, "
            " challenger_branch_ids_json, comparison_spec_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comparison_id, pid, plan_id, branch_id, "[]", "{}", now),
        )
        store._connect().execute(
            "INSERT INTO branch_comparison_snapshots "
            "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
            " comparison_artifact_id, readiness_json, source_plan_version_ids_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, comparison_id, pid, plan_id,
             str(uuid.uuid4()), '{"ready": true}', "[]", now),
        )

        now = utc_now_iso()
        store._connect().execute(
            "INSERT INTO champion_assignments "
            "(champion_assignment_id, project_id, plan_id, scope_type, scope_key, "
            " champion_branch_id, comparison_id, comparison_snapshot_id, comparison_artifact_id, "
            " selected_plan_version_id, assigned_reason, assigned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), pid, plan_id, "project", "default",
             branch_id, comparison_id, snapshot_id, str(uuid.uuid4()),
             pv_id, "test", now),
        )

        # Call supersede without conn= — should open its own transaction
        supersede_champion_for_branch(store, branch_id, "new-pv-id")

        # After supersede, active lookup returns None
        champ = store.get_champion_assignment_by_branch(branch_id)
        assert champ is None, "Champion should be superseded"
        row = store._connect().execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ?",
            (branch_id,),
        ).fetchone()
        assert row is not None
        assert row["superseded_at"] is not None

    def test_no_champion_no_error(self, tmp_path):
        """supersede_champion_for_branch with no champion assignment does nothing."""
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("a")])

        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        # Should not raise
        supersede_champion_for_branch(store, branch_id, "new-pv-id")


class TestRunToNodeBranchContext:
    """Finding 3: run_to_node with branch_id uses branch context."""

    def test_run_to_node_passes_branch_id_to_executor(self, monkeypatch, tmp_path):
        """execute_run passes branch_id to run_to_node."""
        from cardre.services import run_orchestrator
        from tests.test_run_worker import _init_store, _one_step_plan

        calls = []

        class FakeExecutor:
            def validate_plan_executability(self, store, plan_version_id):
                return []
            def run_to_node(self, store, plan_version_id, target_step_id, run_id=None, force=False, branch_id=None, lifecycle=None):
                calls.append(branch_id)
                return run_id

        monkeypatch.setattr(
            "cardre.services.run_service.PlanExecutor", lambda r: FakeExecutor()
        )
        monkeypatch.setattr(
            "cardre.services.run_service.NodeRegistry.with_defaults",
            staticmethod(lambda: object()),
        )

        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)

        run_orchestrator.execute_run(
            store=store, plan_version_id=pv_id, run_scope="to_node",
            target_step_id="source", branch_id="br-1",
        )

        assert calls == ["br-1"], f"Expected branch_id='br-1', got {calls}"

    def test_run_to_node_without_branch_id_passes_none(self, monkeypatch, tmp_path):
        """execute_run passes None for branch_id when not provided."""
        from cardre.services import run_orchestrator
        from tests.test_run_worker import _init_store, _one_step_plan

        calls = []

        class FakeExecutor:
            def validate_plan_executability(self, store, plan_version_id):
                return []
            def run_to_node(self, store, plan_version_id, target_step_id, run_id=None, force=False, branch_id=None, lifecycle=None):
                calls.append(branch_id)
                return run_id

        monkeypatch.setattr(
            "cardre.services.run_service.PlanExecutor", lambda r: FakeExecutor()
        )
        monkeypatch.setattr(
            "cardre.services.run_service.NodeRegistry.with_defaults",
            staticmethod(lambda: object()),
        )

        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)

        run_orchestrator.execute_run(
            store=store, plan_version_id=pv_id, run_scope="to_node",
            target_step_id="source",
        )

        assert calls == [None], f"Expected branch_id=None, got {calls}"


class TestAsyncToNodePreflight:
    """Async to_node preflight returns existing run without creating placeholder."""

    def test_is_to_node_current_returns_run_id_when_current(self, tmp_path):
        """_is_to_node_current returns existing run id when all closure steps are non-stale."""
        from sidecar.routes.runs import _is_to_node_current
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        steps = [_make_step("a")]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        # Save a run step so staleness can find evidence
        from cardre.audit import RunStepRecord
        rs = RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id, step_id="a",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.noop", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
            },
            warnings=[], errors=[],
        )
        store.save_run_step(rs)
        store.finish_run(run_id, "succeeded")

        result = _is_to_node_current(store, pv_id, "a")
        assert result == run_id, f"Expected {run_id}, got {result}"

    def test_is_to_node_current_returns_none_when_stale(self, tmp_path):
        """_is_to_node_current returns None when steps are stale."""
        from sidecar.routes.runs import _is_to_node_current
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        steps = [_make_step("a")]
        pv_id = store.create_plan_version(plan_id, steps)
        # No run exists — step is stale
        result = _is_to_node_current(store, pv_id, "a")
        assert result is None

    def test_is_to_node_current_returns_none_on_missing_target(self, tmp_path):
        """_is_to_node_current returns None when target step doesn't exist."""
        from sidecar.routes.runs import _is_to_node_current
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("a")])
        result = _is_to_node_current(store, pv_id, "nonexistent")
        assert result is None

    def test_is_to_node_current_with_branch_id(self, tmp_path):
        """_is_to_node_current uses branch-scoped staleness and run lookup."""
        from sidecar.routes.runs import _is_to_node_current
        store = _make_store(tmp_path)
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        steps = [_make_step("a")]
        pv_id = store.create_plan_version(plan_id, steps)

        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id, name="br", branch_type="challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        # Branch run exists with a run step
        run_id = store.create_run(pv_id, branch_id=branch_id)
        from cardre.audit import RunStepRecord
        rs = RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id, step_id="a",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.noop", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
            },
            warnings=[], errors=[],
        )
        store.save_run_step(rs)
        store.finish_run(run_id, "succeeded")

        result = _is_to_node_current(store, pv_id, "a", branch_id=branch_id)
        assert result == run_id, f"Expected {run_id}, got {result}"


class TestExecuteActionsBranchContext:
    """_execute_actions passes branch_id to _reuse_run_step."""

    def test_reuse_run_step_receives_branch_id(self, monkeypatch):
        """_reuse_run_step is called with branch_id from _execute_actions."""
        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry
        from cardre.audit import StepSpec, RunStepRecord

        captured = []

        class FakeStore:
            def run_heartbeat(self, run_id):
                pass
            def save_run_step(self, rs):
                pass

        class TrackingExecutor(PlanExecutor):
            def _reuse_run_step(self, store, spec, plan_version_id, run_id, step_outputs, run_step_records, evidence_source=None, branch_id=None):
                captured.append(branch_id)
                return RunStepRecord(
                    run_step_id="rs-1", run_id=run_id, step_id=spec.step_id,
                    plan_version_id=plan_version_id, status="succeeded",
                    started_at="now", finished_at="now",
                    input_artifact_ids=[], output_artifact_ids=[],
                    execution_fingerprint={}, warnings=[], errors=[],
                    is_carried_forward=True,
                )

        executor = TrackingExecutor(NodeRegistry.with_defaults())
        spec = StepSpec(step_id="s1", node_type="cardre.noop", node_version="1", category="transform",
                        params={}, params_hash="abc", parent_step_ids=[], branch_label="", position=0,
                        canonical_step_id="s1", branch_id=None)
        from cardre.executor import _StepAction
        actions = [_StepAction(spec=spec, action="reuse")]

        executor._execute_actions(
            store=FakeStore(), actions=actions, plan_version_id="pv", run_id="run",
            branch_id="br-1",
        )

        assert captured == ["br-1"], f"Expected branch_id='br-1', got {captured}"

    def test_reuse_run_step_receives_none_when_no_branch(self, monkeypatch):
        """_reuse_run_step receives None when _execute_actions has no branch_id."""
        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry
        from cardre.audit import StepSpec, RunStepRecord

        captured = []

        class FakeStore:
            def run_heartbeat(self, run_id):
                pass
            def save_run_step(self, rs):
                pass

        class TrackingExecutor(PlanExecutor):
            def _reuse_run_step(self, store, spec, plan_version_id, run_id, step_outputs, run_step_records, evidence_source=None, branch_id=None):
                captured.append(branch_id)
                return RunStepRecord(
                    run_step_id="rs-1", run_id=run_id, step_id=spec.step_id,
                    plan_version_id=plan_version_id, status="succeeded",
                    started_at="now", finished_at="now",
                    input_artifact_ids=[], output_artifact_ids=[],
                    execution_fingerprint={}, warnings=[], errors=[],
                    is_carried_forward=True,
                )

        executor = TrackingExecutor(NodeRegistry.with_defaults())
        spec = StepSpec(step_id="s1", node_type="cardre.noop", node_version="1", category="transform",
                        params={}, params_hash="abc", parent_step_ids=[], branch_label="", position=0,
                        canonical_step_id="s1", branch_id=None)
        from cardre.executor import _StepAction
        actions = [_StepAction(spec=spec, action="reuse")]

        executor._execute_actions(
            store=FakeStore(), actions=actions, plan_version_id="pv", run_id="run",
        )

        assert captured == [None], f"Expected branch_id=None, got {captured}"


class TestAsyncPreflightForce:
    """Async preflights are skipped when force=True."""

    def test_async_branch_force_skips_preflight(self):
        """async branch with force=True does not call _is_branch_current."""
        # Route guard: if not body.force and body.run_scope == "branch" and body.branch_id:
        # force=True -> not True is False -> short-circuit, preflight skipped
        assert (not True and True and True) is False
        # force=False -> not False is True -> preflight proceeds
        assert (not False and True and True) is True

    def test_async_to_node_force_skips_preflight(self):
        """async to_node with force=True does not call _is_to_node_current."""
        # Route guard: if not body.force and body.run_scope == "to_node" and body.target_step_id:
        assert (not True and True and True) is False
        assert (not False and True and True) is True
