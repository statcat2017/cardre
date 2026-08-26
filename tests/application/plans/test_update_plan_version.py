"""Characterization tests for UpdatePlanVersion."""

from __future__ import annotations

import pytest

from cardre.application.plans.update_plan_version import (
    UpdatePlanVersion,
    UpdatePlanVersionCommand,
)
from cardre.domain.errors import CardreError

from ._helpers import factory


class TestUpdatePlanVersion:
    def test_updates_draft_description(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=False)
            uow.commit()
        use_case = UpdatePlanVersion(factory(uow_factory, project_id))
        use_case(UpdatePlanVersionCommand(
            plan_version_id=pv_id, description="Updated",
        ))
        with uow_factory.for_project(project_id) as uow:
            pv = uow.plans.get_version(pv_id)
        assert pv.description == "Updated"

    def test_rejects_committed_version(self, provisioned_project):
        """A committed plan version is immutable — updating its description
        must fail (F1)."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = UpdatePlanVersion(factory(uow_factory, project_id))
        with pytest.raises(CardreError) as exc:
            use_case(UpdatePlanVersionCommand(
                plan_version_id=pv_id, description="Tampered",
            ))
        assert exc.value.code in ("PLAN_VERSION_ALREADY_COMMITTED", "PLAN_VERSION_IMMUTABLE")

    def test_unknown_version_returns_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = UpdatePlanVersion(factory(uow_factory, project_id))
        with pytest.raises(CardreError) as exc:
            use_case(UpdatePlanVersionCommand(
                plan_version_id="nonexistent", description="X",
            ))
        assert exc.value.code == "PLAN_VERSION_NOT_FOUND"
