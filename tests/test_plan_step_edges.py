"""Phase 1 — plan step edges are rows, queryable by parent and child."""

import pytest

from cardre.domain.step import StepSpec
from cardre.store.db import ProjectStore


@pytest.fixture
def store_with_steps(tmp_path):
    """Create a store with a plan, plan version, and two steps."""
    root = tmp_path / "test.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    from cardre.store.plan_repo import PlanRepository
    from cardre.store.step_repo import StepRepository
    from cardre.store.project_repo import ProjectRepository

    plans = PlanRepository(store)
    steps_repo = StepRepository(store)
    projects = ProjectRepository(store)

    project_id = projects.create("test_project")
    plan_id = plans.create_plan(project_id, "test_plan")
    pv_id = plans.create_version(plan_id, is_committed=False)

    step_a = StepSpec(
        step_id="step_a",
        node_type="cardre.import",
        node_version="1",
        category="import",
        params={},
        params_hash="h1",
        parent_step_ids=[],
        position=0,
    )
    step_b = StepSpec(
        step_id="step_b",
        node_type="cardre.profile",
        node_version="1",
        category="profile",
        params={},
        params_hash="h2",
        parent_step_ids=["step_a"],
        position=1,
    )
    steps_repo.insert_steps(pv_id, [step_a, step_b])
    # Insert edge: step_a -> step_b
    steps_repo.insert_edge(pv_id, "step_a", "step_b", edge_order=0)

    return store, pv_id, steps_repo, step_a, step_b


def test_edge_insert_and_query_by_child(store_with_steps):
    """Can query edges by child step."""
    store, pv_id, steps_repo, step_a, step_b = store_with_steps
    parent_edges = steps_repo.get_parent_edges(pv_id, "step_b")
    assert len(parent_edges) == 1
    assert parent_edges[0]["parent_step_id"] == "step_a"
    assert parent_edges[0]["child_step_id"] == "step_b"


def test_edge_insert_and_query_by_parent(store_with_steps):
    """Can query edges by parent step."""
    store, pv_id, steps_repo, step_a, step_b = store_with_steps
    child_edges = steps_repo.get_child_edges(pv_id, "step_a")
    assert len(child_edges) == 1
    assert child_edges[0]["child_step_id"] == "step_b"


def test_edge_primary_key_enforces_uniqueness(store_with_steps):
    """Duplicate edge insertion is ignored (INSERT OR IGNORE)."""
    store, pv_id, steps_repo, step_a, step_b = store_with_steps
    # Insert same edge again
    steps_repo.insert_edge(pv_id, "step_a", "step_b", edge_order=0)
    edges = steps_repo.get_all_edges(pv_id)
    assert len(edges) == 1  # not duplicated


def test_multiple_parents(tmp_path):
    """A step can have multiple parents."""
    root = tmp_path / "test2.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    from cardre.store.plan_repo import PlanRepository
    from cardre.store.step_repo import StepRepository
    from cardre.store.project_repo import ProjectRepository

    plans = PlanRepository(store)
    steps_repo = StepRepository(store)
    projects = ProjectRepository(store)

    project_id = projects.create("test")
    plan_id = plans.create_plan(project_id, "p")
    pv_id = plans.create_version(plan_id)

    for sid in ["import", "profile", "split", "both"]:
        steps_repo.insert_steps(pv_id, [
            StepSpec(
                step_id=sid,
                node_type="t", node_version="1", category="t",
                params={}, params_hash="h", parent_step_ids=[],
            )
        ])

    steps_repo.insert_edge(pv_id, "import", "both", 0)
    steps_repo.insert_edge(pv_id, "profile", "both", 1)

    parent_edges = steps_repo.get_parent_edges(pv_id, "both")
    assert len(parent_edges) == 2
    assert {e["parent_step_id"] for e in parent_edges} == {"import", "profile"}


def test_cascade_delete_removes_edges(tmp_path):
    """Deleting a step cascades to its edges."""
    root = tmp_path / "cascade.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    from cardre.store.plan_repo import PlanRepository
    from cardre.store.step_repo import StepRepository
    from cardre.store.project_repo import ProjectRepository

    plans = PlanRepository(store)
    steps_repo = StepRepository(store)
    projects = ProjectRepository(store)

    project_id = projects.create("test")
    plan_id = plans.create_plan(project_id, "p")
    pv_id = plans.create_version(plan_id)

    steps_repo.insert_steps(pv_id, [
        StepSpec(step_id="a", node_type="t", node_version="1", category="t",
                 params={}, params_hash="h", parent_step_ids=[]),
        StepSpec(step_id="b", node_type="t", node_version="1", category="t",
                 params={}, params_hash="h2", parent_step_ids=["a"]),
    ])
    steps_repo.insert_edge(pv_id, "a", "b", 0)

    # Delete step a
    store.execute("DELETE FROM plan_steps WHERE plan_version_id = ? AND step_id = ?",
                  (pv_id, "a"))

    edges = steps_repo.get_all_edges(pv_id)
    assert len(edges) == 0
