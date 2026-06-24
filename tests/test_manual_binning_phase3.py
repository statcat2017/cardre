"""Phase 3 tests — bin detail, safe edits, and review-completion gate.

Tests the review-completion gate, reopen review, and blocker enforcement.
Uses monkeypatching to provide editor state without full upstream runs.
"""

from __future__ import annotations

import pytest

from cardre.audit import StepSpec
from cardre.services.manual_binning_service import ManualBinningService
from cardre.services.plan_dto import (
    ManualBinningEditorStateResponse,
    ManualBinningVariableSummary,
    ManualBinningSourceInfo,
    UpdateStepParamsResponse,
)
from cardre.services.plan_service import PlanValidationError


def _make_default_editor_state(overrides: list | None = None) -> ManualBinningEditorStateResponse:
    return ManualBinningEditorStateResponse(
        plan_id="plan-1",
        plan_version_id="pv-1",
        step_id="manual-binning",
        ready=True,
        project_id="prj-1",
        branch_id=None,
        run_id="run-1",
        review_status="not_started",
        reviewed=False,
        accept_automated=False,
        selected_variables=["income", "age"],
        variable_summaries=[
            ManualBinningVariableSummary(
                variable="income", iv=0.35, variable_type="numeric", bin_count=3,
                monotonicity_status="monotonic",
                edited=False, review_required=False,
            ),
            ManualBinningVariableSummary(
                variable="age", iv=0.12, variable_type="numeric", bin_count=4,
                monotonicity_status="non_monotonic",
                edited=False, review_required=True,
                missing_count=0, special_bin_count=1,
                zero_cell_warning_count=1, sparse_bin_warning_count=0,
            ),
        ],
        current_overrides=overrides or [],
        warnings=[],
        source=ManualBinningSourceInfo(
            binning_step_id="binning", binning_artifact_id="art-bin",
            binning_method="fine_classing",
            variable_selection_step_id="variable-selection",
            variable_selection_artifact_id="art-sel",
        ),
    )


class FakeStore:
    """Minimal store stub that tracks plan versions for update_params."""
    def __init__(self):
        self.plan_versions = {}
        self.annotations = []

    def get_latest_plan_version_id(self, plan_id):
        return "pv-base"

    def get_plan_version(self, plan_version_id):
        return {"plan_version_id": plan_version_id, "plan_id": "plan-1"}

    def get_plan_version_steps(self, plan_version_id):
        return [
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="abc",
                parent_step_ids=[], branch_label="", position=0,
                canonical_step_id="manual-binning",
            ),
        ]

    def create_plan_version(self, plan_id, steps, description=""):
        pv_id = f"pv-{len(self.plan_versions) + 1}"
        self.plan_versions[pv_id] = {"plan_id": plan_id, "steps": steps, "description": description}
        return pv_id

    def create_plan_version_in_transaction(self, conn, plan_id, steps, description=""):
        return self.create_plan_version(plan_id, steps, description)

    def transaction(self):
        from contextlib import nullcontext
        class FakeConn:
            def execute(self, *a, **kw):
                return self
            def fetchall(self):
                return []
            def fetchone(self):
                return None
        return nullcontext(FakeConn())

    def get_branch_step_map(self, branch_id, plan_version_id):
        return []

    def get_branch(self, branch_id):
        return None

    def get_latest_successful_run_id(self, plan_version_id, **kwargs):
        return None

    def get_latest_successful_run_id_for_plan(self, plan_id):
        return None

    def list_runs(self, plan_version_id):
        return []

    def get_plan(self, plan_id):
        return {"plan_id": plan_id, "name": "Test", "project_id": "prj-1", "metadata_json": "{}"}

    def get_artifact(self, artifact_id):
        return None

    def get_run_steps(self, run_id):
        return []


def test_gate_rejects_unreviewed_required_variable(monkeypatch):
    store = FakeStore()
    service = ManualBinningService(store)
    editor_state = _make_default_editor_state()

    monkeypatch.setattr(service, "get_editor_state", lambda plan_id, step_id="manual-binning": editor_state)

    with pytest.raises(PlanValidationError) as exc:
        service.save_with_review(
            plan_id="plan-1", plan_version_id="pv-base",
            step_id="manual-binning", project_id="prj-1",
            reviewed=True, reason_code="business_interpretability",
            review_reason="All good.",
        )

    assert exc.value.code == "REVIEW_COMPLETION_BLOCKED"
    assert "requires review" in str(exc.value.message)


def test_gate_rejects_edit_without_reason_code(monkeypatch):
    store = FakeStore()
    service = ManualBinningService(store)
    editor_state = _make_default_editor_state(
        overrides=[{"variable": "income", "action": "merge_bins", "reason": "test", "source_bin_ids": ["a", "b"]}]
    )

    monkeypatch.setattr(service, "get_editor_state", lambda plan_id, step_id="manual-binning": editor_state)

    with pytest.raises(PlanValidationError) as exc:
        service.save_with_review(
            plan_id="plan-1", plan_version_id="pv-base",
            step_id="manual-binning", project_id="prj-1",
            reviewed=True, reason_code="monotonicity",
            review_reason="Done.",
        )

    assert "missing a reason_code" in str(exc.value.message)


def test_gate_allows_completion_when_blockers_clear(monkeypatch):
    store = FakeStore()
    service = ManualBinningService(store)
    # All variables clean
    editor_state = _make_default_editor_state(
        overrides=[{
            "variable": "age", "action": "merge_bins",
            "reason": "Fixed", "reason_code": "monotonicity",
            "source_bin_ids": ["a", "b"],
        }]
    )
    # Override the variable_summaries to not require review
    editor_state.variable_summaries = [
        ManualBinningVariableSummary(
            variable="income", iv=0.35, monotonicity_status="monotonic",
            edited=False, review_required=False,
        ),
        ManualBinningVariableSummary(
            variable="age", iv=0.12, monotonicity_status="monotonic",
            edited=True, review_required=False,
            missing_count=0, special_bin_count=0,
            zero_cell_warning_count=0, sparse_bin_warning_count=0,
        ),
    ]

    monkeypatch.setattr(service, "get_editor_state", lambda plan_id, step_id="manual-binning": editor_state)

    result = service.save_with_review(
        plan_id="plan-1", plan_version_id="pv-base",
        step_id="manual-binning", project_id="prj-1",
        reviewed=True, reason_code="business_interpretability",
        review_reason="All good.",
    )
    assert result is not None


def test_accept_automated_bypasses_gate(monkeypatch):
    store = FakeStore()
    service = ManualBinningService(store)
    editor_state = _make_default_editor_state()

    monkeypatch.setattr(service, "get_editor_state", lambda plan_id, step_id="manual-binning": editor_state)

    # Should not raise despite blockers — accept_automated bypasses the gate
    result = service.save_with_review(
        plan_id="plan-1", plan_version_id="pv-base",
        step_id="manual-binning", project_id="prj-1",
        reviewed=False, accept_automated=True,
    )
    assert result is not None


def test_reopen_review_succeeds(monkeypatch):
    store = FakeStore()
    service = ManualBinningService(store)

    result = service.save_with_review(
        plan_id="plan-1", plan_version_id="pv-base",
        step_id="manual-binning", project_id="prj-1",
        reopen=True, reason_code="monotonicity",
        review_reason="Need to re-examine age variable.",
    )
    assert result is not None


def test_reopen_review_requires_reason():
    store = FakeStore()
    service = ManualBinningService(store)

    with pytest.raises(PlanValidationError) as exc:
        service.save_with_review(
            plan_id="plan-1", plan_version_id="pv-base",
            step_id="manual-binning", project_id="prj-1",
            reopen=True, reason_code=None, review_reason=None,
        )
    assert "reason_code and review_reason are required" in str(exc.value.message)
