from __future__ import annotations

import uuid

from cardre.domain.artifacts import params_hash
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.store.plan_repo import PlanRepository


def test_plan_step_edges_round_trip(store) -> None:
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Project", now, "0.2.0"),
    )

    repo = PlanRepository(store)
    plan_id = repo.create_plan(project_id, "Plan")
    root = StepSpec(
        step_id="root",
        node_type="cardre.root",
        node_version="1",
        category="analysis",
        params={},
        params_hash=params_hash({}),
        parent_step_ids=[],
        position=0,
    )
    child = StepSpec(
        step_id="child",
        node_type="cardre.child",
        node_version="1",
        category="analysis",
        params={"limit": 1},
        params_hash=params_hash({"limit": 1}),
        parent_step_ids=["root"],
        position=1,
    )

    plan_version_id = repo.create_version(plan_id, steps=[root, child], is_committed=True)
    steps = repo.get_version_steps(plan_version_id)

    assert [step.step_id for step in steps] == ["root", "child"]
    assert steps[1].parent_step_ids == ["root"]

    rows = store.execute(
        "SELECT parent_step_id, child_step_id, edge_order FROM plan_step_edges WHERE plan_version_id = ?",
        (plan_version_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["parent_step_id"] == "root"
    assert rows[0]["child_step_id"] == "child"
    assert rows[0]["edge_order"] == 0


def test_plan_step_edges_preserve_multi_parent_order(store) -> None:
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Project", now, "0.2.0"),
    )

    repo = PlanRepository(store)
    plan_id = repo.create_plan(project_id, "Plan")
    left = StepSpec(
        step_id="left",
        node_type="cardre.left",
        node_version="1",
        category="analysis",
        params={},
        params_hash=params_hash({}),
        parent_step_ids=[],
        position=0,
    )
    right = StepSpec(
        step_id="right",
        node_type="cardre.right",
        node_version="1",
        category="analysis",
        params={},
        params_hash=params_hash({}),
        parent_step_ids=[],
        position=1,
    )
    join = StepSpec(
        step_id="join",
        node_type="cardre.join",
        node_version="1",
        category="analysis",
        params={},
        params_hash=params_hash({}),
        parent_step_ids=["left", "right"],
        position=2,
    )

    plan_version_id = repo.create_version(plan_id, steps=[left, right, join], is_committed=True)

    rows = store.execute(
        "SELECT parent_step_id, child_step_id, edge_order FROM plan_step_edges WHERE plan_version_id = ? ORDER BY edge_order",
        (plan_version_id,),
    ).fetchall()
    assert [(r["parent_step_id"], r["child_step_id"], r["edge_order"]) for r in rows] == [
        ("left", "join", 0),
        ("right", "join", 1),
    ]
