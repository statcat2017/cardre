"""Phase 1 — manual binning review lifecycle via the repository."""

import pytest

from cardre.store.db import ProjectStore


@pytest.fixture
def store_with_plan(tmp_path):
    """Create a store with a plan, plan version, and minimal plan steps."""
    root = tmp_path / "mb.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    from cardre.domain.step import StepSpec
    from cardre.store.plan_repo import PlanRepository
    from cardre.store.project_repo import ProjectRepository
    from cardre.store.step_repo import StepRepository

    plans = PlanRepository(store)
    projects = ProjectRepository(store)
    steps = StepRepository(store)

    project_id = projects.create("test")
    plan_id = plans.create_plan(project_id, "test_plan")
    pv_id = plans.create_version(plan_id, is_committed=False)

    # Insert plan steps so manual_binning_reviews FK is satisfied
    for sid in ("binning_step", "step_a", "step_b", "step_c"):
        steps.insert_steps(pv_id, [
            StepSpec(
                step_id=sid,
                node_type="t", node_version="1", category="t",
                params={}, params_hash="h", parent_step_ids=[],
            )
        ])

    return store, pv_id


class TestManualBinningReviewLifecycle:
    def test_create_review(self, store_with_plan):
        """Create a manual binning review."""
        store, pv_id = store_with_plan
        from cardre.store.manual_binning_repo import ManualBinningRepository

        reviews = ManualBinningRepository(store)
        review_id = reviews.create_review(
            plan_version_id=pv_id,
            step_id="binning_step",
            status="pending",
            reviewer_notes="Initial review",
            affected_downstream_step_ids=["step_b", "step_c"],
        )

        review = reviews.get_review(review_id)
        assert review is not None
        assert review.plan_version_id == pv_id
        assert review.step_id == "binning_step"
        assert review.status == "pending"
        assert review.reviewer_notes == "Initial review"
        assert review.affected_downstream_step_ids == ["step_b", "step_c"]

    def test_get_reviews_for_step(self, store_with_plan):
        """Multiple reviews for the same step can be retrieved."""
        store, pv_id = store_with_plan
        from cardre.store.manual_binning_repo import ManualBinningRepository

        reviews = ManualBinningRepository(store)
        r1 = reviews.create_review(pv_id, "step_a", status="pending")
        r2 = reviews.create_review(pv_id, "step_a", status="approved")

        step_reviews = reviews.get_reviews_for_step(pv_id, "step_a")
        assert len(step_reviews) == 2
        ids = {r.review_id for r in step_reviews}
        assert ids == {r1, r2}

    def test_update_review_status(self, store_with_plan):
        """Review status can be updated."""
        store, pv_id = store_with_plan
        from cardre.store.manual_binning_repo import ManualBinningRepository

        reviews = ManualBinningRepository(store)
        review_id = reviews.create_review(pv_id, "step_a", status="pending")

        reviews.update_review(review_id, status="approved", reviewer_notes="Looks good")

        review = reviews.get_review(review_id)
        assert review.status == "approved"
        assert review.reviewer_notes == "Looks good"

    def test_review_not_found(self, store_with_plan):
        """Getting a non-existent review returns None."""
        store, _ = store_with_plan
        from cardre.store.manual_binning_repo import ManualBinningRepository

        reviews = ManualBinningRepository(store)
        assert reviews.get_review("nonexistent") is None

    def test_empty_downstream_step_ids(self, store_with_plan):
        """A review with no affected downstream steps stores empty list."""
        store, pv_id = store_with_plan
        from cardre.store.manual_binning_repo import ManualBinningRepository

        reviews = ManualBinningRepository(store)
        review_id = reviews.create_review(pv_id, "step_a")

        review = reviews.get_review(review_id)
        assert review.affected_downstream_step_ids == []
