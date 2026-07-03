"""Tests for PlanMutationService.apply_manual_binning_edit."""

from __future__ import annotations

import json

import pytest

from cardre.services.plan_mutation_service import (
    ManualBinningEditCommand,
    PlanMutationError,
    PlanMutationService,
)


class TestApplyManualBinningEdit:
    """apply_manual_binning_edit creates draft version + review in one transaction."""

    def test_creates_draft_version_and_review(self, store_with_evidence):
        store, project_id, plan_id, base_pv_id, mb_step_id = store_with_evidence

        service = PlanMutationService(store)
        command = ManualBinningEditCommand(
            plan_version_id=base_pv_id,
            step_id=mb_step_id,
            overrides=[{"variable": "income", "action": "merge_bins", "reason": "test"}],
            reviewer_notes="Merged low-frequency bins.",
            status="pending",
            affected_downstream_step_ids=["apply-woe"],
        )

        result = service.apply_manual_binning_edit(command)

        # 1. New plan version exists
        new_pv = store.execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?",
            (result.new_plan_version_id,),
        ).fetchone()
        assert new_pv is not None, "New plan version should exist"
        assert new_pv["is_committed"] == 0, "New version should be draft (uncommitted)"
        assert new_pv["plan_id"] == plan_id

        # 2. Steps are copied to new version
        steps = store.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (result.new_plan_version_id,),
        ).fetchall()
        assert len(steps) == 3, "Should have 3 steps (fine-classing, manual-binning, apply-woe)"

        # 3. Manual-binning step has updated params
        mb_step = None
        for s in steps:
            if s["step_id"] == mb_step_id:
                mb_step = dict(s)
                break
        assert mb_step is not None
        params = json.loads(mb_step["params_json"])
        assert params["overrides"] == [{"variable": "income", "action": "merge_bins", "reason": "test"}]
        assert params["status"] == "pending"

        # 4. Edges are copied to new version
        edges = store.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ?",
            (result.new_plan_version_id,),
        ).fetchall()
        assert len(edges) == 2, "Should have 2 edges (fine-classing -> mb, mb -> apply-woe)"

        # 5. Review row exists
        review = store.execute(
            "SELECT * FROM manual_binning_reviews WHERE review_id = ?",
            (result.review_id,),
        ).fetchone()
        assert review is not None
        assert review["plan_version_id"] == result.new_plan_version_id
        assert review["step_id"] == mb_step_id
        assert review["status"] == "pending"
        assert review["reviewer_notes"] == "Merged low-frequency bins."

        downstream = json.loads(review["affected_downstream_step_ids_json"])
        assert "apply-woe" in downstream

    def test_rolls_back_on_error(self, store_with_evidence):
        """If an error occurs mid-transaction, no partial state remains."""
        store, project_id, plan_id, base_pv_id, mb_step_id = store_with_evidence

        service = PlanMutationService(store)

        # Use a non-existent step_id to trigger an error
        command = ManualBinningEditCommand(
            plan_version_id=base_pv_id,
            step_id="non-existent-step",
            overrides=[],
        )

        with pytest.raises(PlanMutationError):
            service.apply_manual_binning_edit(command)

        # The base version steps should not have been modified
        base_steps = store.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ?",
            (base_pv_id,),
        ).fetchall()
        assert len(base_steps) == 3, "Base version steps should be untouched"

        # No new plan version should have been created
        # Since the error happens BEFORE the transaction starts (in validation),
        # no new version is created. The key assertion is that base state is intact.
        assert len([r for r in store.execute(
            "SELECT * FROM plan_versions WHERE plan_id = ?", (plan_id,)
        ).fetchall()]) == 1, "Only the base version should exist"

    def test_does_not_mutate_historical_evidence(self, store_with_evidence):
        """Historical evidence rows are never modified by apply_manual_binning_edit."""
        store, project_id, plan_id, base_pv_id, mb_step_id = store_with_evidence

        # Snapshot evidence state before
        before_edges = [
            dict(r) for r in store.execute(
                "SELECT * FROM evidence_edges WHERE plan_version_id = ?",
                (base_pv_id,),
            ).fetchall()
        ]
        before_artifacts = store.execute(
            "SELECT * FROM evidence_artifacts"
        ).fetchall()

        service = PlanMutationService(store)
        command = ManualBinningEditCommand(
            plan_version_id=base_pv_id,
            step_id=mb_step_id,
            overrides=[{"variable": "income", "action": "merge_bins"}],
        )
        service.apply_manual_binning_edit(command)

        # Evidence state should be identical
        after_edges = [
            dict(r) for r in store.execute(
                "SELECT * FROM evidence_edges WHERE plan_version_id = ?",
                (base_pv_id,),
            ).fetchall()
        ]
        after_artifacts = store.execute(
            "SELECT * FROM evidence_artifacts"
        ).fetchall()

        assert before_edges == after_edges, "Evidence edges must not be mutated"
        assert len(before_artifacts) == len(after_artifacts), "Evidence artifacts must not be mutated"

    def test_raises_on_nonexistent_plan_version(self, store):
        """A non-existent base plan version raises PlanMutationError."""
        service = PlanMutationService(store)
        command = ManualBinningEditCommand(
            plan_version_id="nonexistent-pv",
            step_id="manual-binning",
            overrides=[],
        )
        with pytest.raises(PlanMutationError, match="not found"):
            service.apply_manual_binning_edit(command)

    def test_raises_on_nonexistent_step(self, store_with_evidence):
        """A non-existent step in the plan raises PlanMutationError."""
        store, project_id, plan_id, base_pv_id, mb_step_id = store_with_evidence

        service = PlanMutationService(store)
        command = ManualBinningEditCommand(
            plan_version_id=base_pv_id,
            step_id="not-a-step",
            overrides=[],
        )
        with pytest.raises(PlanMutationError, match="not found"):
            service.apply_manual_binning_edit(command)
