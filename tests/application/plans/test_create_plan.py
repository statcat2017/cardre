"""Characterization tests for CreatePlan."""

from __future__ import annotations

from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand

from ._helpers import factory


class TestCreatePlan:
    def test_creates_and_returns_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CreatePlan(factory(uow_factory, project_id))
        plan = use_case(CreatePlanCommand(project_id=project_id, name="My Plan"))
        assert plan is not None
        assert plan.name == "My Plan"
        assert plan.project_id == project_id
