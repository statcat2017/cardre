"""Tests for honest action planning (#214).

Every step action must carry a reason code. The to-node closure only
includes ancestor steps. There are no pretend reuse/skip branches.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_plan_with_steps(store, step_ids=("step-a",)):
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
    for i, sid in enumerate(step_ids):
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pv_id, "cardre.noop", "1", "transform",
             json.dumps({}), f"hash-{sid}", "", i, sid),
        )
    if len(step_ids) >= 2:
        for i in range(len(step_ids) - 1):
            store.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, ?)",
                (pv_id, step_ids[i], step_ids[i + 1], 0),
            )
    return pv_id


def test_step_action_has_reason_code():
    """_StepAction carries a reason_code field (#214)."""
    from cardre.domain.step import StepSpec
    from cardre.execution.action_planner import _StepAction

    spec = StepSpec(
        step_id="s1", node_type="cardre.noop", node_version="1",
        category="transform", params={}, params_hash="h", position=0,
        parent_step_ids=[], canonical_step_id="s1",
    )
    action = _StepAction(spec=spec, action="execute", reason_code="full_plan")
    assert action.reason_code == "full_plan"
    assert action.reason_context == {}


def test_run_plan_version_actions_have_reason(store):
    """run_plan_version marks all steps with reason_code 'full_plan'."""
    from cardre.execution.executor import PlanExecutor

    pv_id = _seed_plan_with_steps(store, ("step-a", "step-b"))
    executor = PlanExecutor(store)

    # Intercept _execute_actions to inspect the actions list
    captured = []
    original = PlanExecutor._execute_actions

    def capture(self, plan_version_id, run_id, actions, **kwargs):
        captured.extend(actions)
        return (False, {}, {})

    PlanExecutor._execute_actions = capture
    try:
        executor.run_plan_version(pv_id, "run-1", force=True)
    finally:
        PlanExecutor._execute_actions = original

    assert len(captured) == 2
    assert all(a.reason_code == "full_plan" for a in captured)
    assert all(a.action == "execute" for a in captured)


def test_to_node_closure_only_includes_ancestors(store):
    """to-node run only includes ancestor closure, not all steps."""
    from cardre.execution.executor import PlanExecutor

    pv_id = _seed_plan_with_steps(store, ("step-a", "step-b", "step-c"))
    executor = PlanExecutor(store)

    captured = []
    original = PlanExecutor._execute_actions

    def capture(self, plan_version_id, run_id, actions, **kwargs):
        captured.extend(actions)
        return (False, {}, {})

    PlanExecutor._execute_actions = capture
    try:
        executor.run_to_node(pv_id, "step-b", "run-1", force=True)
    finally:
        PlanExecutor._execute_actions = original

    step_ids = [a.spec.step_id for a in captured]
    assert step_ids == ["step-a", "step-b"]
    assert all(a.reason_code == "to_node_closure" for a in captured)
