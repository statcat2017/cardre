from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from cardre.domain.plan import Plan, PlanVersion


def test_plan_and_plan_version_to_dict() -> None:
    plan = Plan(
        plan_id="plan-1",
        project_id="project-1",
        name="My Plan",
        created_at="2026-01-01T00:00:00+00:00",
    )
    version = PlanVersion(
        plan_version_id="pv-1",
        plan_id="plan-1",
        version_number=1,
        is_committed=False,
        created_at="2026-01-01T00:00:00+00:00",
        description="draft",
    )

    assert plan.to_dict()["name"] == "My Plan"
    assert version.to_dict()["is_committed"] is False


def test_plan_and_version_are_frozen() -> None:
    plan = Plan(
        plan_id="plan-1",
        project_id="project-1",
        name="My Plan",
        created_at="2026-01-01T00:00:00+00:00",
    )
    version = PlanVersion(
        plan_version_id="pv-1",
        plan_id="plan-1",
        version_number=1,
        is_committed=True,
        created_at="2026-01-01T00:00:00+00:00",
    )

    with pytest.raises(FrozenInstanceError):
        plan.name = "Changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        version.description = "Changed"  # type: ignore[misc]
