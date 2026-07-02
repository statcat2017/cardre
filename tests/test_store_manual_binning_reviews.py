from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.manual_binning_repo import ManualBinningRepository


def test_manual_binning_review_lifecycle(store) -> None:
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    plan_version_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (plan_version_id, plan_id, now, "Base"),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, params_json, params_hash, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, '{}', 'hash', 0, ?)",
        ("step-1", plan_version_id, "cardre.step", "1", "analysis", "step-1"),
    )

    repo = ManualBinningRepository(store)
    review_id = repo.create_review(
        plan_version_id,
        "step-1",
        status="pending",
        reviewer_notes="needs review",
        affected_downstream_step_ids=["downstream-1", "downstream-2"],
    )

    review = repo.get_review(review_id)
    assert review is not None
    assert review.status == "pending"
    assert review.affected_downstream_step_ids == ["downstream-1", "downstream-2"]

    repo.update_review(review_id, status="approved")
    updated = repo.get_review(review_id)
    assert updated is not None
    assert updated.status == "approved"
    assert len(repo.get_reviews_for_step(plan_version_id, "step-1")) == 1
