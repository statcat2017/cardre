"""Characterization tests for ApplyManualBinningEdit use case.

Validates draft version + review atomic creation, missing plan/step
validation through the production persistence stack. The use case now uses
the UoW's ``manual_binning`` repo directly, so the plan-version write and
the review write share one transaction.
"""

from __future__ import annotations

import json

import pytest

from cardre.application.plans.apply_manual_binning_edit import (
    ApplyManualBinningEdit,
    ApplyManualBinningEditCommand,
)
from cardre.domain.errors import CardreError


def _seed_plan_with_mb_step(uow, project_id):
    """Seed a committed plan version with automatic-binning -> manual-binning -> apply-woe."""
    plan_id = uow.plans.create_plan(project_id, "Test Plan")
    pv_id = uow.plans.create_version(
        plan_id,
        steps=[
            _step("automatic-binning", "cardre.automatic_binning", "fit", [], 0,
                  {"max_bins": 20}, "auto-hash"),
            _step("manual-binning", "cardre.manual_binning", "refinement",
                  ["automatic-binning"], 1, {"overrides": []}, "mb-hash"),
            _step("apply-woe", "cardre.apply_woe_mapping", "transform",
                  ["manual-binning"], 2, {}, "woe-hash"),
        ],
        description="Base", is_committed=True,
    )
    return plan_id, pv_id


def _step(step_id, node_type, category, parents, position, params, params_hash):
    from cardre.domain.step import StepSpec
    return StepSpec(
        step_id=step_id, node_type=node_type, node_version="1", category=category,
        params=params, params_hash=params_hash, parent_step_ids=parents,
        branch_label="", position=position, canonical_step_id=step_id,
    )


def _use_case(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return ApplyManualBinningEdit(factory)


class TestApplyManualBinningEdit:
    def test_creates_draft_version_and_review_atomically(self, provisioned_project):
        project_id, uow_factory, _, root = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, base_pv_id = _seed_plan_with_mb_step(uow, project_id)
            uow.commit()

        use_case = _use_case(uow_factory, project_id)
        result = use_case(ApplyManualBinningEditCommand(
            plan_version_id=base_pv_id, step_id="manual-binning",
            overrides=[{"variable": "income", "action": "merge_bins", "reason": "test"}],
            reviewer_notes="Merged low-frequency bins.",
            status="pending",
            affected_downstream_step_ids=["apply-woe"],
        ))

        with uow_factory.read_only(project_id) as uow:
            new_pv = uow.plans.get_version(result.new_plan_version_id)
            assert new_pv is not None
            assert new_pv.is_committed is False
            assert new_pv.plan_id == plan_id

            steps = uow.plans.get_version_steps(result.new_plan_version_id)
            assert len(steps) == 3
            mb_step = next(s for s in steps if s.step_id == "manual-binning")
            assert mb_step.params["overrides"] == [
                {"variable": "income", "action": "merge_bins", "reason": "test"}
            ]
            assert mb_step.params["status"] == "pending"

            review = uow.manual_binning.get_review(result.review_id)
            assert review is not None
            assert review.plan_version_id == result.new_plan_version_id
            assert review.step_id == "manual-binning"
            assert review.status == "pending"
            assert review.reviewer_notes == "Merged low-frequency bins."
            assert "apply-woe" in review.affected_downstream_step_ids

    def test_raises_on_nonexistent_plan_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = _use_case(uow_factory, project_id)
        with pytest.raises(CardreError, match="not found"):
            use_case(ApplyManualBinningEditCommand(
                plan_version_id="nonexistent-pv", step_id="manual-binning", overrides=[],
            ))

    def test_raises_on_nonexistent_step(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            _, base_pv_id = _seed_plan_with_mb_step(uow, project_id)
            uow.commit()
        use_case = _use_case(uow_factory, project_id)
        with pytest.raises(CardreError, match="not found"):
            use_case(ApplyManualBinningEditCommand(
                plan_version_id=base_pv_id, step_id="not-a-step", overrides=[],
            ))


def test_manual_binning_row_access_does_not_crash(provisioned_project):
    """Regression: sqlite3.Row has no .get(); hydrating a review must use
    bracket access. A normally-inserted review must round-trip through the
    repo without AttributeError."""
    project_id, uow_factory, _, _ = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        _, pv_id = _seed_plan_with_mb_step(uow, project_id)
        uow.commit()
    with uow_factory.for_project(project_id) as uow:
        review = uow.manual_binning.create_review(
            plan_version_id=pv_id, step_id="manual-binning",
            status="pending", reviewer_notes="n",
            affected_downstream_step_ids=["apply-woe"],
        )
        uow.commit()
        rid = review.review_id
    with uow_factory.read_only(project_id) as uow:
        loaded = uow.manual_binning.get_review(rid)
    assert loaded is not None
    assert loaded.affected_downstream_step_ids == ["apply-woe"]
    with uow_factory.read_only(project_id) as uow:
        listed = uow.manual_binning.list_for_project(project_id)
    assert any(r.review_id == rid for r in listed)


# silence unused-import linters for json (kept for parity with old assertions)
_ = json
