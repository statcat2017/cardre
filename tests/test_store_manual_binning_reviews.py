from __future__ import annotations

from cardre.domain.step import StepSpec


def test_manual_binning_review_lifecycle(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            steps=[
                StepSpec(
                    step_id="step-1", node_type="cardre.step", node_version="1",
                    category="analysis", params={}, params_hash="hash",
                    parent_step_ids=[], position=0, canonical_step_id="step-1",
                )
            ],
            is_committed=True,
        )

        review = uow.manual_binning.create_review(
            pv_id,
            "step-1",
            status="pending",
            reviewer_notes="needs review",
            affected_downstream_step_ids=["downstream-1", "downstream-2"],
        )

        assert review.status == "pending"
        assert review.affected_downstream_step_ids == ["downstream-1", "downstream-2"]

        got = uow.manual_binning.get_review(review.review_id)
        assert got is not None
        assert got.status == "pending"
        assert got.affected_downstream_step_ids == ["downstream-1", "downstream-2"]

        assert uow.manual_binning.update_review(review.review_id, status="approved") is True
        updated = uow.manual_binning.get_review(review.review_id)
        assert updated is not None
        assert updated.status == "approved"
        assert len(uow.manual_binning.get_reviews_for_step(pv_id, "step-1")) == 1
