"""Characterization tests for ListPlans."""

from __future__ import annotations

from cardre.application.plans.list_plans import ListPlans, ListPlansCommand

from ._helpers import factory


class TestListPlans:
    def test_lists_plans_for_project(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            uow.plans.create_plan(project_id, "A")
            uow.plans.create_plan(project_id, "B")
            uow.commit()
        use_case = ListPlans(factory(uow_factory, project_id))
        plans = use_case(ListPlansCommand(project_id=project_id))
        assert len(plans) == 2
