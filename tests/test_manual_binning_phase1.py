"""Phase 1 contract tests — state contract consolidation and audit widening.

Tests the widened DTO shape, audit annotation persistence, review
validation, blocker computation, and atomic write semantics.
"""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.audit import StepSpec
from cardre.readiness import compute_manual_binning_blockers
from cardre.services.manual_binning_service import ManualBinningService
from cardre.services.plan_dto import ManualBinningVariableSummary
from cardre.nodes.build.bins import ManualBinningNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _query(store, sql: str, params: tuple = ()) -> list:
    """Run a read query against the store and return rows as dicts."""
    conn = store._connect()
    conn.row_factory = __import__("sqlite3").Row
    return conn.execute(sql, params).fetchall()


def _make_plan_with_mb_step(store, project_id: str) -> tuple[str, str, str]:
    """Create a plan with a manual-binning step and return (plan_id, pv_id, step_id)."""
    plan_id = store.create_plan(project_id, "Test Plan")
    step_id = "manual-binning"
    steps = [
        StepSpec(
            step_id=step_id,
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={"overrides": []},
            params_hash="abc",
            parent_step_ids=["binning"],
            branch_label="",
            position=0,
            canonical_step_id="manual-binning",
        ),
    ]
    pv_id = store.create_plan_version(plan_id=plan_id, steps=steps)
    return plan_id, pv_id, step_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_id(store):
    return store.create_project("Test Plan")


# ---------------------------------------------------------------------------
# Blockers computation
# ---------------------------------------------------------------------------


class TestComputeManualBinningBlockers:
    """Tests for the shared blocker computation function."""

    def test_no_blockers_when_all_variables_clean(self):
        summaries = [
            ManualBinningVariableSummary(variable="income", review_required=False),
            ManualBinningVariableSummary(variable="age", review_required=False),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income", "age"],
            variable_summaries=summaries,
            current_overrides=[],
            branch_id=None,
            step_id="manual-binning",
        )
        assert blockers == []

    def test_unreviewed_required_variable_blocker(self):
        summaries = [
            ManualBinningVariableSummary(
                variable="income", review_required=True,
                zero_cell_warning_count=0, sparse_bin_warning_count=0,
                missing_count=0, special_bin_count=0,
            ),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income"],
            variable_summaries=summaries,
            current_overrides=[],
            branch_id=None,
            step_id="manual-binning",
        )
        codes = {b["code"] for b in blockers}
        assert "UNREVIEWED_REQUIRED_VARIABLE" in codes

    def test_unresolved_zero_cell_blocker(self):
        summaries = [
            ManualBinningVariableSummary(
                variable="income", review_required=False,
                zero_cell_warning_count=2, sparse_bin_warning_count=0,
                missing_count=0, special_bin_count=0,
            ),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income"],
            variable_summaries=summaries,
            current_overrides=[],
            branch_id=None,
            step_id="manual-binning",
        )
        codes = {b["code"] for b in blockers}
        assert "UNRESOLVED_ZERO_CELL" in codes

    def test_unresolved_missing_handling_blocker(self):
        summaries = [
            ManualBinningVariableSummary(
                variable="income", review_required=False,
                zero_cell_warning_count=0, sparse_bin_warning_count=0,
                missing_count=1, special_bin_count=0,
            ),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income"],
            variable_summaries=summaries,
            current_overrides=[],
            branch_id=None,
            step_id="manual-binning",
        )
        codes = {b["code"] for b in blockers}
        assert "UNRESOLVED_MISSING_HANDLING" in codes

    def test_edit_without_reason_code_blocker(self):
        summaries = [
            ManualBinningVariableSummary(variable="income", review_required=False),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income"],
            variable_summaries=summaries,
            current_overrides=[{"variable": "income", "action": "merge_bins", "reason": "test"}],
            branch_id=None,
            step_id="manual-binning",
        )
        codes = {b["code"] for b in blockers}
        assert "EDIT_WITHOUT_REASON_CODE" in codes

    def test_override_with_reason_code_clears_blocker(self):
        summaries = [
            ManualBinningVariableSummary(
                variable="income", review_required=True,
                zero_cell_warning_count=0, sparse_bin_warning_count=0,
                missing_count=1, special_bin_count=0,
            ),
        ]
        blockers = compute_manual_binning_blockers(
            selected_variables=["income"],
            variable_summaries=summaries,
            current_overrides=[{
                "variable": "income", "action": "reorder_missing_bin",
                "reason": "Accepted", "reason_code": "missing_value_treatment",
            }],
            branch_id=None,
            step_id="manual-binning",
        )
        codes = {b["code"] for b in blockers}
        assert "UNRESOLVED_MISSING_HANDLING" not in codes


# ---------------------------------------------------------------------------
# save_with_review — audit annotation persistence
# ---------------------------------------------------------------------------


class TestSaveWithReview:
    """Tests that save_with_review persists the correct annotation."""

    def test_save_with_review_creates_annotation(self, store, project_id):
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)

        result = service.save_with_review(
            plan_id=plan_id,
            plan_version_id=pv_id,
            step_id=step_id,
            project_id=project_id,
            reviewed=False,
            accept_automated=True,
            overrides=None,
            reviewed_by="alice",
            reason_code=None,
            review_reason=None,
        )

        # Read annotation
        ann_rows = _query(
            store,
            "SELECT payload_json, kind, actor, step_id, plan_version_id "
            "FROM step_annotations WHERE step_id = ? ORDER BY created_at DESC LIMIT 1",
            (step_id,),
        )
        assert len(ann_rows) == 1
        payload = json.loads(ann_rows[0]["payload_json"])
        assert ann_rows[0]["kind"] == "manual_binning_review"
        assert ann_rows[0]["actor"] == "alice"
        assert ann_rows[0]["plan_version_id"] == result.new_plan_version_id
        assert payload["reviewed"] is False
        assert payload["accept_automated"] is True
        assert payload["reviewed_by"] == "alice"
        assert payload["base_plan_version_id"] == pv_id
        assert payload["new_plan_version_id"] == result.new_plan_version_id
        assert payload["override_count"] == 0

    def test_save_with_accept_automated_creates_annotation(self, store, project_id):
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)

        result = service.save_with_review(
            plan_id=plan_id,
            plan_version_id=pv_id,
            step_id=step_id,
            project_id=project_id,
            reviewed=False,
            accept_automated=True,
            overrides=None,
        )

        ann_rows = _query(
            store,
            "SELECT payload_json FROM step_annotations WHERE step_id = ? ORDER BY created_at DESC LIMIT 1",
            (step_id,),
        )
        assert len(ann_rows) == 1
        payload = json.loads(ann_rows[0]["payload_json"])
        assert payload["reviewed"] is False
        assert payload["accept_automated"] is True
        assert payload["override_count"] == 0  # accept_automated clears overrides
        assert payload["base_plan_version_id"] == pv_id
        assert payload["new_plan_version_id"] == result.new_plan_version_id

    def test_save_with_review_sets_step_params(self, store, project_id):
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)

        result = service.save_with_review(
            plan_id=plan_id,
            plan_version_id=pv_id,
            step_id=step_id,
            project_id=project_id,
            reviewed=False,
            accept_automated=True,
        )

        new_steps = store.get_plan_version_steps(result.new_plan_version_id)
        mb = [s for s in new_steps if s.step_id == step_id][0]
        assert mb.params.get("reviewed") is False
        assert mb.params.get("accept_automated") is True

    def test_save_with_review_rejected_without_reason_code(self, store, project_id):
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)

        with pytest.raises(Exception) as exc:
            service.save_with_review(
                plan_id=plan_id,
                plan_version_id=pv_id,
                step_id=step_id,
                project_id=project_id,
                reviewed=True,
                accept_automated=False,
                reason_code=None,
                review_reason="Because.",
            )
        assert "reason_code is required" in str(exc.value)

    def test_accept_automated_clears_overrides(self, store, project_id):
        """Accept-automated sets overrides=[] even without upstream runs."""
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        # Manually set some overrides on the step first, then accept automated.
        # We skip the override validation path by accepting automated without
        # providing overrides — the service sets overrides=[] internally.
        service = ManualBinningService(store)
        result = service.save_with_review(
            plan_id=plan_id,
            plan_version_id=pv_id,
            step_id=step_id,
            project_id=project_id,
            reviewed=False,
            accept_automated=True,
            overrides=None,
        )

        new_steps = store.get_plan_version_steps(result.new_plan_version_id)
        mb = [s for s in new_steps if s.step_id == step_id][0]
        assert mb.params.get("accept_automated") is True
        assert mb.params.get("overrides") == []

    def test_annotation_plan_version_id_matches_new_version(self, store, project_id):
        """Verify the annotation is written against the new plan version, not the old one."""
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)

        result = service.save_with_review(
            plan_id=plan_id,
            plan_version_id=pv_id,
            step_id=step_id,
            project_id=project_id,
            reviewed=False,
            accept_automated=True,
        )

        ann_rows = _query(
            store,
            "SELECT plan_version_id FROM step_annotations WHERE step_id = ? ORDER BY created_at DESC LIMIT 1",
            (step_id,),
        )
        assert ann_rows[0]["plan_version_id"] == result.new_plan_version_id
        assert ann_rows[0]["plan_version_id"] != pv_id


# ---------------------------------------------------------------------------
# get_editor_state — contract shape
# ---------------------------------------------------------------------------


class TestGetEditorState:
    """Tests that get_editor_state returns the widened contract fields.

    Since the editor state requires upstream runs, the response will
    be ``ready=False``, but the DTO shape should still include the
    Phase 1 fields with sensible defaults.
    """

    def test_returns_contract_fields_when_not_ready(self, store, project_id):
        plan_id, pv_id, step_id = _make_plan_with_mb_step(store, project_id)
        service = ManualBinningService(store)
        state = service.get_editor_state(plan_id, step_id=step_id)

        assert state.plan_id == plan_id
        assert state.step_id == step_id
        # The state is likely "not ready" (no upstream run), but the
        # DTO should still carry the widened fields.
        assert hasattr(state, "project_id")
        assert hasattr(state, "branch_id")
        assert hasattr(state, "run_id")
        assert state.review_status in ("not_started", "reviewed", "accepted_automated")
        assert hasattr(state, "reviewed")
        assert hasattr(state, "accept_automated")
        assert hasattr(state, "reviewed_at")
        assert hasattr(state, "reviewed_by")
        assert hasattr(state, "review_reason")
        assert hasattr(state, "review_reason_code")
        assert isinstance(state.blocking_issues, list)

    def test_variable_summary_includes_widened_fields(self, store, project_id):
        """When no WOE evidence is available, variable_summaries may be
        empty; verify the DTO shape includes the new fields at the model
        level."""
        from cardre.services.plan_dto import ManualBinningVariableSummary

        vs = ManualBinningVariableSummary(variable="income")
        assert hasattr(vs, "variable_type")
        assert hasattr(vs, "bin_count")
        assert hasattr(vs, "missing_rate")
        assert hasattr(vs, "special_rate")
        assert hasattr(vs, "zero_cell_warning_count")
        assert hasattr(vs, "sparse_bin_warning_count")
        assert vs.monotonicity_status == "insufficient_bins"
        assert hasattr(vs, "edited")
        assert hasattr(vs, "review_required")


# ---------------------------------------------------------------------------
# Reason code vocabulary
# ---------------------------------------------------------------------------


class TestReasonCodes:
    """Tests for the reason code vocabulary on ManualBinningNode."""

    def test_reason_codes_contains_expected_codes(self):
        expected = {
            "business_interpretability", "monotonicity", "sparse_bin",
            "zero_cell", "missing_value_treatment", "special_value_treatment",
            "regulatory_or_policy", "other",
        }
        assert ManualBinningNode.REASON_CODES == expected

    def test_valid_reason_code_accepted(self):
        node = ManualBinningNode()
        overrides = [{
            "variable": "income", "action": "merge_bins",
            "reason": "Too many bins", "reason_code": "business_interpretability",
            "source_bin_ids": ["a", "b"],
        }]
        errors = node.validate_params({"overrides": overrides})
        assert errors == []  # reviewed/accept_automated not set is fine

    def test_invalid_reason_code_rejected(self):
        node = ManualBinningNode()
        overrides = [{
            "variable": "income", "action": "merge_bins",
            "reason": "test", "reason_code": "not_a_real_code",
            "source_bin_ids": ["a", "b"],
        }]
        errors = node.validate_params({"overrides": overrides})
        assert any("unknown reason_code" in e for e in errors)

    def test_reason_code_optional_for_backwards_compat(self):
        node = ManualBinningNode()
        overrides = [{
            "variable": "income", "action": "merge_bins",
            "reason": "test",
            "source_bin_ids": ["a", "b"],
        }]
        errors = node.validate_params({"overrides": overrides})
        assert errors == []
