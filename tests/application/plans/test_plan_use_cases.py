"""Characterization tests for plan use cases — create, get, list, commit, update.

Ported behavioral coverage for the thin plan use cases through the production
persistence stack.
"""

from __future__ import annotations

import pytest

from cardre.application.plans.commit_plan_version import CommitPlanVersion, CommitPlanVersionCommand
from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand
from cardre.application.plans.get_plan import GetPlan, GetPlanCommand
from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
from cardre.application.plans.list_plan_versions import ListPlanVersions, ListPlanVersionsCommand
from cardre.application.plans.list_plans import ListPlans, ListPlansCommand
from cardre.application.plans.update_plan_version import UpdatePlanVersion, UpdatePlanVersionCommand
from cardre.domain.errors import CardreError

from ..conftest import make_branchable_steps


def _factory(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return factory


class TestCreatePlan:
    def test_creates_and_returns_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CreatePlan(_factory(uow_factory, project_id))
        plan = use_case(CreatePlanCommand(project_id=project_id, name="My Plan"))
        assert plan is not None
        assert plan.name == "My Plan"
        assert plan.project_id == project_id


class TestGetPlan:
    def test_returns_plan_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        use_case = GetPlan(_factory(uow_factory, project_id))
        plan = use_case(GetPlanCommand(plan_id=plan_id))
        assert plan is not None
        assert plan.plan_id == plan_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlan(_factory(uow_factory, project_id))
        assert use_case(GetPlanCommand(plan_id="nonexistent")) is None


class TestListPlans:
    def test_lists_plans_for_project(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            uow.plans.create_plan(project_id, "A")
            uow.plans.create_plan(project_id, "B")
            uow.commit()
        use_case = ListPlans(_factory(uow_factory, project_id))
        plans = use_case(ListPlansCommand(project_id=project_id))
        assert len(plans) == 2


class TestGetPlanVersion:
    def test_returns_version_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = GetPlanVersion(_factory(uow_factory, project_id))
        pv = use_case(GetPlanVersionCommand(plan_version_id=pv_id))
        assert pv is not None
        assert pv.plan_version_id == pv_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlanVersion(_factory(uow_factory, project_id))
        assert use_case(GetPlanVersionCommand(plan_version_id="nonexistent")) is None


class TestListPlanVersions:
    def test_lists_versions_for_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.plans.create_version(plan_id, is_committed=True)
            uow.plans.create_version(plan_id, is_committed=False)
            uow.commit()
        use_case = ListPlanVersions(_factory(uow_factory, project_id))
        versions = use_case(ListPlanVersionsCommand(plan_id=plan_id))
        assert len(versions) == 2


class TestCommitPlanVersion:
    def test_commits_draft_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(
                plan_id, make_branchable_steps(), is_committed=False,
            )
            uow.commit()
        use_case = CommitPlanVersion(_factory(uow_factory, project_id))
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_raises_on_nonexistent_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CommitPlanVersion(_factory(uow_factory, project_id))
        with pytest.raises(CardreError, match="not found"):
            use_case(CommitPlanVersionCommand(plan_version_id="nonexistent"))

    def test_raises_on_already_committed(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(
                plan_id, make_branchable_steps(), is_committed=True,
            )
            uow.commit()
        use_case = CommitPlanVersion(_factory(uow_factory, project_id))
        with pytest.raises(CardreError, match="already committed"):
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))


class TestUpdatePlanVersion:
    def test_updates_description(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = UpdatePlanVersion(_factory(uow_factory, project_id))
        use_case(UpdatePlanVersionCommand(
            plan_version_id=pv_id, description="Updated",
        ))
        with uow_factory.for_project(project_id) as uow:
            pv = uow.plans.get_version(pv_id)
        assert pv.description == "Updated"
