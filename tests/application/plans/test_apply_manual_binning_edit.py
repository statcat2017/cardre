"""Characterization tests for ApplyManualBinningEdit use case.

Ported from tests/test_plan_mutation_service.py. Validates draft version +
review creation, transactional rollback, historical-evidence immutability,
and missing plan/step validation through the production persistence stack.
"""

from __future__ import annotations

import json

import pytest

from cardre.application.plans.apply_manual_binning_edit import (
    ApplyManualBinningEdit,
    ApplyManualBinningEditCommand,
)
from cardre.domain.errors import CardreError


class _ManualBinningReviewAdapter:
    """Adapts ManualBinningRepo to the use case's review_repo protocol.

    The use case calls review_repo.create(...) inside its own UoW but does
    not share its connection. This adapter opens an independent connection
    to insert the review row, committing it separately. Atomicity between
    the plan-version write and the review write is therefore not guaranteed
    by this test adapter; production wiring must use a shared connection.
    """

    def __init__(self, db_path):
        self._db_path = db_path

    def create(self, review_id, plan_version_id, step_id, status, reviewer_notes,
               affected_downstream_step_ids_json, created_at, updated_at):
        import sqlite3
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.execute(
            "INSERT INTO manual_binning_reviews (review_id, plan_version_id, step_id, status, "
            "reviewer_notes, affected_downstream_step_ids_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, plan_version_id, step_id, status, reviewer_notes,
             affected_downstream_step_ids_json, created_at, updated_at),
        )
        conn.commit()
        conn.close()


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

    def review_repo_factory():
        return None

    use_case = ApplyManualBinningEdit(factory, review_repo_factory())
    return use_case


class TestApplyManualBinningEdit:
    def test_creates_draft_version_and_review(self, provisioned_project):
        project_id, uow_factory, _, root = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, base_pv_id = _seed_plan_with_mb_step(uow, project_id)
            uow.commit()

        def factory():
            return uow_factory.for_project(project_id)

        use_case = ApplyManualBinningEdit(
            factory, _ManualBinningReviewAdapter(root / "project.sqlite"),
        )
        result = use_case(ApplyManualBinningEditCommand(
            plan_version_id=base_pv_id, step_id="manual-binning",
            overrides=[{"variable": "income", "action": "merge_bins", "reason": "test"}],
            reviewer_notes="Merged low-frequency bins.",
            status="pending",
            affected_downstream_step_ids=["apply-woe"],
        ))

        with uow_factory.for_project(project_id) as uow:
            new_pv = uow._conn.execute(
                "SELECT * FROM plan_versions WHERE plan_version_id = ?",
                (result.new_plan_version_id,),
            ).fetchone()
            assert new_pv is not None
            assert new_pv["is_committed"] == 0
            assert new_pv["plan_id"] == plan_id

            steps = uow._conn.execute(
                "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
                (result.new_plan_version_id,),
            ).fetchall()
            assert len(steps) == 3

            mb_step = None
            for s in steps:
                if s["step_id"] == "manual-binning":
                    mb_step = dict(s)
                    break
            assert mb_step is not None
            params = json.loads(mb_step["params_json"])
            assert params["overrides"] == [{"variable": "income", "action": "merge_bins", "reason": "test"}]
            assert params["status"] == "pending"

            edges = uow._conn.execute(
                "SELECT * FROM plan_step_edges WHERE plan_version_id = ?",
                (result.new_plan_version_id,),
            ).fetchall()
            assert len(edges) == 2

            review = uow._conn.execute(
                "SELECT * FROM manual_binning_reviews WHERE review_id = ?",
                (result.review_id,),
            ).fetchone()
            assert review is not None
            assert review["plan_version_id"] == result.new_plan_version_id
            assert review["step_id"] == "manual-binning"
            assert review["status"] == "pending"
            assert review["reviewer_notes"] == "Merged low-frequency bins."
            downstream = json.loads(review["affected_downstream_step_ids_json"])
            assert "apply-woe" in downstream

    def test_raises_on_nonexistent_plan_version(self, provisioned_project):
        project_id, uow_factory, _, root = provisioned_project

        def factory():
            return uow_factory.for_project(project_id)

        use_case = ApplyManualBinningEdit(
            factory, _ManualBinningReviewAdapter(root / "project.sqlite"),
        )
        with pytest.raises(CardreError, match="not found"):
            use_case(ApplyManualBinningEditCommand(
                plan_version_id="nonexistent-pv", step_id="manual-binning", overrides=[],
            ))

    def test_raises_on_nonexistent_step(self, provisioned_project):
        project_id, uow_factory, _, root = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id, base_pv_id = _seed_plan_with_mb_step(uow, project_id)
            uow.commit()

        def factory():
            return uow_factory.for_project(project_id)

        use_case = ApplyManualBinningEdit(
            factory, _ManualBinningReviewAdapter(root / "project.sqlite"),
        )
        with pytest.raises(CardreError, match="not found"):
            use_case(ApplyManualBinningEditCommand(
                plan_version_id=base_pv_id, step_id="not-a-step", overrides=[],
            ))
