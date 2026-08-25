"""Characterization tests for GetPlan."""

from __future__ import annotations

from cardre.application.plans.get_plan import GetPlan, GetPlanCommand

from ._helpers import factory


class TestGetPlan:
    def test_returns_plan_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        use_case = GetPlan(factory(uow_factory, project_id))
        plan = use_case(GetPlanCommand(plan_id=plan_id))
        assert plan is not None
        assert plan.plan_id == plan_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlan(factory(uow_factory, project_id))
        assert use_case(GetPlanCommand(plan_id="nonexistent")) is None
