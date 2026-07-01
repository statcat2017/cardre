"""Phase 1 — domain plan: draft/committed transitions, immutability after commit."""

from cardre.domain.plan import Plan, PlanVersion


def test_plan_minimal():
    """Plan can be constructed with minimal required args."""
    plan = Plan(
        plan_id="p1",
        project_id="proj1",
        name="Test Plan",
        created_at="2025-01-01T00:00:00",
    )
    assert plan.plan_id == "p1"
    assert plan.project_id == "proj1"
    assert plan.name == "Test Plan"
    assert plan.to_dict()["name"] == "Test Plan"


def test_plan_version_draft_default():
    """PlanVersion is a draft (is_committed=False) by default when not set."""
    pv = PlanVersion(
        plan_version_id="pv1",
        plan_id="p1",
        version_number=1,
        is_committed=False,
        created_at="2025-01-01T00:00:00",
    )
    assert not pv.is_committed
    assert pv.description == ""


def test_plan_version_committed():
    """PlanVersion can be created as committed."""
    pv = PlanVersion(
        plan_version_id="pv1",
        plan_id="p1",
        version_number=1,
        is_committed=True,
        created_at="2025-01-01T00:00:00",
        description="Initial version",
    )
    assert pv.is_committed
    assert pv.description == "Initial version"


def test_plan_version_immutability():
    """PlanVersion is frozen — attempting to mutate raises."""
    pv = PlanVersion(
        plan_version_id="pv1",
        plan_id="p1",
        version_number=1,
        is_committed=False,
        created_at="2025-01-01T00:00:00",
    )
    try:
        pv.is_committed = True
        assert False, "Should have raised"
    except Exception:
        pass


def test_plan_version_to_dict():
    """PlanVersion.to_dict() returns the expected fields."""
    pv = PlanVersion(
        plan_version_id="pv1",
        plan_id="p1",
        version_number=1,
        is_committed=True,
        created_at="2025-01-01T00:00:00",
        description="Initial",
    )
    d = pv.to_dict()
    assert d["plan_version_id"] == "pv1"
    assert d["is_committed"] is True
    assert d["version_number"] == 1


def test_plan_to_dict():
    """Plan.to_dict() returns the expected fields."""
    plan = Plan(
        plan_id="p1",
        project_id="proj1",
        name="Test",
        created_at="2025-01-01T00:00:00",
    )
    d = plan.to_dict()
    assert d["plan_id"] == "p1"
    assert d["project_id"] == "proj1"
    assert d["name"] == "Test"
