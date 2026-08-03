"""Characterization tests for UpdateStepParams.

A single-step parameter editor for draft plan versions. The full supplied
parameter set is validated against the resolved node before persisting:
committed versions are immutable, unknown steps are rejected, and invalid
parameter values are rejected with a structured PARAMETER_VALIDATION_ERROR.
"""

from __future__ import annotations

import pytest

from cardre.application.plans.update_step_params import (
    UpdateStepParams,
    UpdateStepParamsCommand,
)
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError

from ..conftest import make_branchable_steps


def _factory(uow_factory, project_id):
    return lambda: uow_factory.for_project(project_id)


def _catalogue():
    return build_default_catalogue(Settings())


class TestUpdateStepParams:
    def test_updates_draft_step_params(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        steps = make_branchable_steps()
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, steps, is_committed=False)
            uow.commit()
        step_id = steps[1].step_id  # variable-selection
        new_params = {"min_iv": 0.05}
        uc = UpdateStepParams(_factory(uow_factory, project_id), _catalogue())
        uc(UpdateStepParamsCommand(
            plan_version_id=pv_id, step_id=step_id, params=new_params,
        ))
        with uow_factory.for_project(project_id) as uow:
            persisted = uow.plans.get_version_steps(pv_id)
        edited = next(s for s in persisted if s.step_id == step_id)
        assert edited.params["min_iv"] == 0.05
        assert edited.params_hash == json_logical_hash(edited.params)

    def test_rejects_invalid_params(self, provisioned_project):
        """An out-of-range parameter value must leave the version a draft."""
        project_id, uow_factory, _, _ = provisioned_project
        steps = make_branchable_steps()
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, steps, is_committed=False)
            uow.commit()
        uc = UpdateStepParams(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            uc(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id=steps[1].step_id,
                params={"min_iv": -1.0},
            ))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        with uow_factory.for_project(project_id) as uow:
            persisted = uow.plans.get_version_steps(pv_id)
        edited = next(s for s in persisted if s.step_id == steps[1].step_id)
        assert edited.params.get("min_iv", 0.02) != -1.0  # unchanged

    def test_rejects_committed_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        steps = make_branchable_steps()
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
            uow.commit()
        uc = UpdateStepParams(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            uc(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id=steps[0].step_id, params={},
            ))
        assert exc.value.code == "PLAN_VERSION_ALREADY_COMMITTED"

    def test_unknown_version_returns_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        uc = UpdateStepParams(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            uc(UpdateStepParamsCommand(
                plan_version_id="nonexistent", step_id="s1", params={},
            ))
        assert exc.value.code == "PLAN_VERSION_NOT_FOUND"

    def test_unknown_step_raises(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        steps = make_branchable_steps()
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, steps, is_committed=False)
            uow.commit()
        uc = UpdateStepParams(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            uc(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id="no-such-step", params={},
            ))
        assert exc.value.code == "STEP_NOT_FOUND"
