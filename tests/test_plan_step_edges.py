from __future__ import annotations

from cardre.domain.artifacts import params_hash
from cardre.domain.step import StepSpec


def _step_spec(step_id, node_type, params, parent_step_ids, position):
    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category="analysis",
        params=params,
        params_hash=params_hash(params),
        parent_step_ids=parent_step_ids,
        position=position,
        canonical_step_id=step_id,
    )


def test_plan_step_edges_round_trip(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        root = _step_spec("root", "cardre.root", {}, [], 0)
        child = _step_spec("child", "cardre.child", {"limit": 1}, ["root"], 1)

        plan_version_id = uow.plans.create_version(plan_id, steps=[root, child], is_committed=True)
        steps = uow.plans.get_version_steps(plan_version_id)

        assert [step.step_id for step in steps] == ["root", "child"]
        assert steps[1].parent_step_ids == ["root"]

        rows = uow._conn.execute(
            "SELECT parent_step_id, child_step_id, edge_order FROM plan_step_edges WHERE plan_version_id = ?",
            (plan_version_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["parent_step_id"] == "root"
        assert rows[0]["child_step_id"] == "child"
        assert rows[0]["edge_order"] == 0


def test_plan_step_edges_preserve_multi_parent_order(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        left = _step_spec("left", "cardre.left", {}, [], 0)
        right = _step_spec("right", "cardre.right", {}, [], 1)
        join = _step_spec("join", "cardre.join", {}, ["left", "right"], 2)

        plan_version_id = uow.plans.create_version(plan_id, steps=[left, right, join], is_committed=True)

        rows = uow._conn.execute(
            "SELECT parent_step_id, child_step_id, edge_order FROM plan_step_edges WHERE plan_version_id = ? ORDER BY edge_order",
            (plan_version_id,),
        ).fetchall()
        assert [(r["parent_step_id"], r["child_step_id"], r["edge_order"]) for r in rows] == [
            ("left", "join", 0),
            ("right", "join", 1),
        ]
