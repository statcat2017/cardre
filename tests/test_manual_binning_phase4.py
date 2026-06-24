"""Phase 4 integration tests — readiness, evidence, and report integration.

Tests that the readiness warning fires when reviewed with bad overrides,
and the report collector populates manual_binning_review from annotations.
"""

from __future__ import annotations

import json

import pytest

from cardre.audit import StepSpec
from cardre.readiness import check_report_readiness, LimitationCode
from cardre.reporting.collector import generate_report_bundle
from cardre.store import ProjectStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_minimal_branch(store: ProjectStore, project_id: str, plan_id: str, mb_params: dict) -> tuple[str, str, str]:
    """Create a plan version + branch with manual-binning and required steps.

    Returns (pv_id, branch_id, mb_step_id).
    """
    mb_step = StepSpec(
        "manual-binning__br_test",
        "cardre.manual_binning", "1", "refinement",
        mb_params, "hash",
        ["final-woe-iv"], "branch", 12,
        canonical_step_id="manual-binning",
        branch_id="test_branch",
    )
    # Required steps that the collector resolves
    required = ["import", "target-definition", "binning", "variable-selection",
                 "final-woe-iv", "model-fit", "score-scaling", "validation-metrics", "cutoff-analysis"]
    steps = []
    for i, cid in enumerate(required):
        steps.append(StepSpec(
            cid, f"cardre.{cid}", "1", "build", {}, "hash", [], "baseline", i,
            canonical_step_id=cid,
        ))
    steps.append(mb_step)

    pv_id = store.create_plan_version(plan_id, steps)
    run_id = store.create_run(pv_id)
    store.finish_run(run_id, "succeeded")

    branch_id = store.create_branch(
        project_id=project_id, plan_id=plan_id, name="Test", branch_type="baseline",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="Test.",
    )
    # Create step map for all required steps
    for cid in required:
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id=cid, step_id=cid,
            is_shared_upstream=False, is_branch_owned=True,
        )
    store.create_branch_step_map(
        branch_id=branch_id, plan_version_id=pv_id,
        canonical_step_id="manual-binning", step_id="manual-binning__br_test",
        is_shared_upstream=False, is_branch_owned=True,
    )
    return pv_id, branch_id, "manual-binning__br_test", run_id


def _add_review_annotation(store: ProjectStore, step_id: str, pv_id: str, payload: dict) -> None:
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO step_annotations "
            "(annotation_id, step_id, plan_version_id, kind, actor, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ann-1", step_id, pv_id, "manual_binning_review", "alice",
             json.dumps(payload), "2026-06-24T10:00:00Z"),
        )


# ---------------------------------------------------------------------------
# Readiness warning test
# ---------------------------------------------------------------------------


class TestReadinessWarningIntegration:
    """check_report_readiness emits warning when reviewed with bad overrides."""

    def test_warning_when_reviewed_with_missing_reason_code(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": True, "overrides": [{"variable": "income", "action": "merge_bins", "reason": "test"}]},
        )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {w.code for w in result.warnings}
        assert LimitationCode.MANUAL_BINNING_REVIEWED_WITH_WARNINGS in codes

    def test_no_warning_when_reviewed_with_valid_overrides(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": True, "overrides": [{"variable": "income", "action": "merge_bins",
              "reason": "test", "reason_code": "monotonicity"}]},
        )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {w.code for w in result.warnings}
        assert LimitationCode.MANUAL_BINNING_REVIEWED_WITH_WARNINGS not in codes

    def test_warning_is_not_blocker(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": True, "overrides": [{"variable": "income", "action": "merge_bins", "reason": "test"}]},
        )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        block_codes = {b.code for b in result.blockers}
        assert LimitationCode.MANUAL_BINNING_REVIEWED_WITH_WARNINGS not in block_codes


# ---------------------------------------------------------------------------
# Collector / report bundle test
# ---------------------------------------------------------------------------


class TestReportBundleReviewStateIntegration:
    """generate_report_bundle populates manual_binning_review from annotations."""

    def _collect(self, store, project_id, pv_id, branch_id, run_id):
        """Run the collector and return the bundle."""
        return generate_report_bundle(
            store=store, project_id=project_id,
            run_id=run_id, target_branch_id=branch_id, report_mode="branch",
        )

    def test_review_status_from_params(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": True, "overrides": [{"variable": "income", "action": "merge_bins",
              "reason": "test", "reason_code": "monotonicity"}]},
        )
        _add_review_annotation(store, mb_step_id, pv_id, {
            "reviewed": True, "reviewed_by": "bob", "reason_code": "monotonicity",
            "review_reason": "Looks good.",
        })
        bundle = self._collect(store, project_id, pv_id, branch_id, run_id)
        assert bundle.manual_binning_review.review_status == "reviewed"
        assert bundle.manual_binning_review.accepted_automated is False
        assert bundle.manual_binning_review.edited_variable_count == 1
        assert "income" in bundle.manual_binning_review.variables_edited
        assert "monotonicity" in bundle.manual_binning_review.reasons

    def test_review_metadata_from_annotation(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": True, "overrides": [{"variable": "income", "action": "merge_bins",
              "reason": "test", "reason_code": "monotonicity"}]},
        )
        _add_review_annotation(store, mb_step_id, pv_id, {
            "reviewed": True, "reviewed_by": "bob", "reason_code": "monotonicity",
            "review_reason": "Looks good.",
        })
        bundle = self._collect(store, project_id, pv_id, branch_id, run_id)
        assert bundle.manual_binning_review.reviewed_by == "bob"
        assert bundle.manual_binning_review.review_reason == "Looks good."
        assert len(bundle.manual_binning_review.reviewed_at) > 0

    def test_accepted_automated_distinct(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"accept_automated": True, "overrides": []},
        )
        _add_review_annotation(store, mb_step_id, pv_id, {
            "accept_automated": True, "reviewed_by": "alice",
        })
        bundle = self._collect(store, project_id, pv_id, branch_id, run_id)
        assert bundle.manual_binning_review.review_status == "accepted_automated"
        assert bundle.manual_binning_review.accepted_automated is True
        assert bundle.manual_binning_review.edited_variable_count == 0

    def test_not_started_when_unreviewed(self, store):
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test")
        pv_id, branch_id, mb_step_id, run_id = _setup_minimal_branch(
            store, project_id, plan_id,
            {"reviewed": False, "accept_automated": False, "overrides": []},
        )
        bundle = self._collect(store, project_id, pv_id, branch_id, run_id)
        assert bundle.manual_binning_review.review_status == "not_started"
        assert bundle.manual_binning_review.accepted_automated is False
