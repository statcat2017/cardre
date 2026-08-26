"""Characterization tests for GetPlanVersion."""

from __future__ import annotations

from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand

from ._helpers import factory


class TestGetPlanVersion:
    def test_returns_version_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = GetPlanVersion(factory(uow_factory, project_id))
        pv = use_case(GetPlanVersionCommand(plan_version_id=pv_id))
        assert pv is not None
        assert pv.plan_version_id == pv_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlanVersion(factory(uow_factory, project_id))
        assert use_case(GetPlanVersionCommand(plan_version_id="nonexistent")) is None
