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
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError

from ..conftest import make_branchable_steps


def _factory(uow_factory, project_id):
    return lambda: uow_factory.for_project(project_id)


def _catalogue():
    return build_default_catalogue()


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

    def test_target_column_propagates_across_target_steps(self, provisioned_project, tmp_path):
        """Editing the target on any target-dependent step must reach all
        three (define-metadata, validate-target, split) atomically — the
        desktop editor only exposes some of them."""
        import polars as pl

        from cardre.application.plans.create_canonical_scorecard_version import (
            CreateCanonicalScorecardVersion,
            CreateCanonicalScorecardVersionCommand,
        )

        project_id, uow_factory, _, _ = provisioned_project
        parquet_path = tmp_path / "in.parquet"
        pl.DataFrame({
            "x": list(range(6)),
            "outcome": ["good" if i % 2 else "bad" for i in range(6)],
        }).write_parquet(parquet_path)
        cat = _catalogue()
        create = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), cat)
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        pv = create(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(parquet_path), target_column="outcome",
        ))
        pv_id = pv.plan_version_id

        uc = UpdateStepParams(_factory(uow_factory, project_id), cat)
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
        meta_step = next(s for s in steps if s.canonical_step_id == "define-metadata")
        # A real user supplies business metadata before commit; the neutral
        # template leaves reject_inference_position empty, which node
        # validation rejects.
        uc(UpdateStepParamsCommand(
            plan_version_id=pv_id, step_id=meta_step.step_id,
            params={**meta_step.params, "reject_inference_position": "not_applied"},
        ))
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
        split_step = next(s for s in steps if s.canonical_step_id == "split")
        uc(UpdateStepParamsCommand(
            plan_version_id=pv_id, step_id=split_step.step_id,
            params={**split_step.params, "target_column": "default_flag"},
        ))
        with uow_factory.for_project(project_id) as uow:
            persisted = uow.plans.get_version_steps(pv_id)
        for step in persisted:
            if step.canonical_step_id in ("define-metadata", "validate-target", "split"):
                assert step.params["target_column"] == "default_flag", (
                    f"{step.canonical_step_id} was not propagated"
                )
