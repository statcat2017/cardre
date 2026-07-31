from __future__ import annotations

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


class TestPlanRepository:
    def test_create_and_get_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project

        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            assert plan_id is not None
            plan = uow.plans.get_plan(plan_id)
            assert plan is not None
            assert plan.name == "test-plan"

            steps = [
                StepSpec(
                    step_id="s1", node_type="cardre.noop", node_version="1",
                    category="transform", params={}, params_hash=json_logical_hash({}),
                    parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
                )
            ]
            pv_id = uow.plans.create_version(plan_id, steps, description="v1", is_committed=True)
            assert pv_id is not None
            pv = uow.plans.get_version(pv_id)
            assert pv is not None
            assert pv.is_committed is True
            assert pv.description == "v1"

            version_steps = uow.plans.get_version_steps(pv_id)
            assert len(version_steps) >= 1

            plans = uow.plans.list_for_project(project_id)
            assert any(p.plan_id == plan_id for p in plans)

            versions = uow.plans.list_versions(plan_id)
            assert any(v.plan_version_id == pv_id for v in versions)

            latest = uow.plans.get_latest_version_id(plan_id)
            assert latest == pv_id
            assert uow.plans.get_latest_version_id("nonexistent") is None

            commit_resp = uow.plans.commit_version(pv_id)
            assert commit_resp is None

    def test_get_plan_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            assert uow.plans.get_plan("nonexistent") is None
            assert uow.plans.get_version("nonexistent") is None
            assert uow.plans.list_for_project("nonexistent") == []
            assert uow.plans.list_versions("nonexistent") == []
            assert uow.plans.get_version_steps("nonexistent") == []

    def test_get_plan_id_for_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=True)
            assert uow.plans.get_plan_id_for_version(pv_id) == plan_id
            assert uow.plans.get_plan_id_for_version("nonexistent") is None

    def test_commit_version_and_update_description(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "test-plan")
            pv_id = uow.plans.create_version(plan_id, [], description="v1", is_committed=False)
            uow.plans.commit_version(pv_id)
            pv = uow.plans.get_version(pv_id)
            assert pv.is_committed is True

            uow.plans.update_version_description(pv_id, "Updated description")
            pv = uow.plans.get_version(pv_id)
            assert pv.description == "Updated description"
