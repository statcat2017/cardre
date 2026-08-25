"""Characterization tests for ListPlanVersions."""

from __future__ import annotations

from cardre.application.plans.list_plan_versions import (
    ListPlanVersions,
    ListPlanVersionsCommand,
)

from ._helpers import factory


class TestListPlanVersions:
    def test_lists_versions_for_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.plans.create_version(plan_id, is_committed=True)
            uow.plans.create_version(plan_id, is_committed=False)
            uow.commit()
        use_case = ListPlanVersions(factory(uow_factory, project_id))
        versions = use_case(ListPlanVersionsCommand(plan_id=plan_id))
        assert len(versions) == 2
