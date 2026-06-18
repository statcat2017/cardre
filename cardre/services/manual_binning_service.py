"""ManualBinningService — manual binning editor state and preview logic.

Extracted from PlanService so binning-specific orchestration does not
bloat the plan query/update service.
"""

from __future__ import annotations

import json
from typing import Any

from cardre.audit import RunStepRecord, StepSpec
from cardre.executor import PlanExecutor
from cardre.nodes import validate_manual_binning_overrides, apply_manual_binning_overrides
from cardre.registry import NodeRegistry
from cardre.staleness import compute_staleness
from cardre.store import ProjectStore
from cardre.services.plan_dto import (
    ManualBinningEditorStateResponse,
    ManualBinningPreviewResponse,
    ManualBinningSourceInfo,
    PreviewDiagnostics,
)
from cardre.services.plan_service import PlanValidationError
from cardre.services.step_topology import find_nearest_ancestor_by_canonical_step_id


class ManualBinningService:
    """Manual-binning editor state, preview, and override validation."""

    def __init__(self, store: ProjectStore):
        self._store = store
        self._registry = NodeRegistry.with_defaults()
        self._executor = PlanExecutor(self._registry)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_editor_state(
        self, plan_id: str, step_id: str = "manual-binning"
    ) -> ManualBinningEditorStateResponse:
        """Assemble manual-binning editor state from upstream artifacts.

        Supports both baseline (manual-binning) and branch-owned steps
        (manual-binning__br_xxx).
        """
        plan = self._store.get_plan(plan_id)
        if plan is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id="", step_id=step_id,
                ready=False, blocked_reason=f"No plan with ID {plan_id}",
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id="", step_id=step_id,
                ready=False, blocked_reason="Plan has no versions.",
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)

        mb_spec = None
        for s in steps:
            if s.step_id == step_id:
                mb_spec = s
                break

        if mb_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason="Manual binning step not found in this plan.",
            )

        if mb_spec.canonical_step_id != "manual-binning":
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason=f"Step {step_id} is not a manual-binning step.",
            )

        branch_id = mb_spec.branch_id
        if branch_id:
            branch_step_map = self._store.get_branch_step_map(branch_id, latest_pv_id)
        else:
            branch_step_map = [{"step_id": s.step_id, "is_shared_upstream": 0, "is_branch_owned": 1} for s in steps]

        fc_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "fine-classing")
        vs_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        fc_actual_id = fc_spec.step_id if fc_spec else "fine-classing"
        vs_actual_id = vs_spec.step_id if vs_spec else "variable-selection"

        if fc_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason="Fine-classing step is not an ancestor of this manual-binning step.",
                required_steps=["fine-classing"],
            )

        ancestors = self._executor.find_ancestors(fc_actual_id, steps)
        if "fine-classing" not in ancestors and fc_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason="Fine-classing step is not an ancestor of this manual-binning step.",
                required_steps=["fine-classing"],
            )

        staleness = compute_staleness(self._store, latest_pv_id)
        fc_stale = staleness.get(fc_actual_id, True)
        vs_stale = staleness.get(vs_actual_id, True) if vs_spec else True

        if fc_stale or vs_stale:
            blocked = []
            if fc_stale:
                blocked.append(fc_actual_id)
            if vs_stale:
                blocked.append(vs_actual_id)
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason=f"Upstream steps stale: {', '.join(blocked)}. Run the pathway to refresh.",
                required_steps=blocked,
            )

        (fc_def, vs_def, fc_artifact_id, vs_artifact_id), err = self._resolve_upstream_defs(
            latest_pv_id, plan_id, fc_step_id=fc_actual_id, vs_step_id=vs_actual_id, branch_id=branch_id,
        )
        if err is not None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason=err, required_steps=["fine-classing", "variable-selection"],
            )

        selected_vars = [s["variable"] for s in vs_def.get("selected", [])] if vs_def else []

        source_bins = {}
        if fc_def:
            for v in fc_def.get("variables", []):
                if v["variable"] in selected_vars:
                    source_bins[v["variable"]] = v

        current_overrides = mb_spec.params.get("overrides", [])

        warnings = []
        if not selected_vars:
            warnings.append({"message": "No variables selected by variable selection."})
        if not source_bins:
            warnings.append({"message": "No source bins found for selected variables from fine-classing."})

        return ManualBinningEditorStateResponse(
            plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id, ready=True,
            source=ManualBinningSourceInfo(
                fine_classing_step_id=fc_actual_id, fine_classing_artifact_id=fc_artifact_id,
                variable_selection_step_id=vs_actual_id, variable_selection_artifact_id=vs_artifact_id,
            ),
            selected_variables=selected_vars, source_bins_by_variable=source_bins,
            current_overrides=current_overrides, warnings=warnings,
        )

    def preview_overrides(
        self,
        plan_id: str,
        plan_version_id: str,
        overrides: list[dict],
        step_id: str = "manual-binning",
    ) -> ManualBinningPreviewResponse:
        """Validate manual-binning overrides against fine-classing output."""
        pv = self._store.get_plan_version(plan_version_id)
        if pv is None or pv["plan_id"] != plan_id:
            raise PlanValidationError(
                "VERSION_NOT_IN_PLAN",
                "Provided plan_version_id does not belong to this plan.",
                status_code=400,
            )

        steps = self._store.get_plan_version_steps(plan_version_id)
        mb_spec = None
        for s in steps:
            if s.step_id == step_id:
                mb_spec = s
                break

        if mb_spec is None or mb_spec.canonical_step_id != "manual-binning":
            return ManualBinningPreviewResponse(
                valid=False, diagnostics=PreviewDiagnostics(override_count=0, warnings=[f"Step {step_id} not found or not manual-binning."]),
            )

        branch_id = mb_spec.branch_id
        if branch_id:
            branch_step_map = self._store.get_branch_step_map(branch_id, plan_version_id)
        else:
            branch_step_map = [{"step_id": s.step_id} for s in steps]

        fc_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "fine-classing")
        vs_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        fc_step_id = fc_spec.step_id if fc_spec else "fine-classing"
        vs_step_id = vs_spec.step_id if vs_spec else "variable-selection"

        result, err = self._resolve_upstream_defs(
            plan_version_id, plan_id, fc_step_id=fc_step_id, vs_step_id=vs_step_id, branch_id=branch_id,
        )
        if err is not None:
            return ManualBinningPreviewResponse(
                valid=False, diagnostics=PreviewDiagnostics(override_count=0, warnings=[err]),
            )

        fc_def, vs_def, _, _ = result
        selected_vars = {s["variable"] for s in vs_def.get("selected", [])}

        validation_warnings = validate_manual_binning_overrides(fc_def, overrides, selected_vars)
        if validation_warnings:
            return ManualBinningPreviewResponse(
                valid=False, diagnostics=PreviewDiagnostics(override_count=len(overrides), warnings=validation_warnings),
            )

        refined = apply_manual_binning_overrides(fc_def, overrides, selected_vars)
        refined_by_var: dict[str, Any] = {}
        for v in refined.get("variables", []):
            refined_by_var[v["variable"]] = v

        return ManualBinningPreviewResponse(
            valid=True, refined_bins_by_variable=refined_by_var,
            diagnostics=PreviewDiagnostics(override_count=len(overrides), warnings=[]),
        )

    def validate_overrides(
        self, plan_id: str, plan_version_id: str, overrides: list[dict],
        step_id: str, branch_id: str | None = None,
    ) -> None:
        """Validate manual-binning overrides against upstream artifacts.

        Raises PlanValidationError on invalid overrides.
        """
        if not overrides:
            return

        fc_step_id = self._find_mb_step_id_for_validation(plan_version_id, step_id, "fine-classing", branch_id)
        vs_step_id = self._find_mb_step_id_for_validation(plan_version_id, step_id, "variable-selection", branch_id)

        (fc_def, vs_def, _, _), err = self._resolve_upstream_defs(
            plan_version_id, plan_id, fc_step_id=fc_step_id, vs_step_id=vs_step_id, branch_id=branch_id,
        )
        if err is not None:
            raise PlanValidationError("PARAMS_VALIDATION_FAILED", err)

        selected_vars = {s["variable"] for s in vs_def.get("selected", [])} if vs_def else set()
        errors = validate_manual_binning_overrides(fc_def, overrides, selected_vars)
        if errors:
            raise PlanValidationError(
                "PARAMS_VALIDATION_FAILED", "; ".join(errors),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_upstream_defs(
        self, plan_version_id: str, plan_id: str,
        fc_step_id: str = "fine-classing",
        vs_step_id: str = "variable-selection",
        branch_id: str | None = None,
    ) -> tuple:
        """Return (fc_def, vs_def, fc_artifact_id, vs_artifact_id) on success
        or ((None, None, None, None), error_msg) on failure."""
        def _find_run_step(sid: str) -> RunStepRecord | None:
            if branch_id and "__" in sid:
                rs = self._store.get_latest_successful_run_step_for_step(
                    plan_version_id, sid, branch_id=branch_id,
                )
                if rs is not None:
                    return rs
            run_id = self._store.get_latest_successful_run_id(plan_version_id)
            if run_id is None:
                run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
            if run_id is None:
                return None
            for rs in self._store.get_run_steps(run_id):
                if rs.step_id == sid and rs.status == "succeeded":
                    return rs
            return None

        fc_rs = _find_run_step(fc_step_id)
        vs_rs = _find_run_step(vs_step_id)
        if fc_rs is None or vs_rs is None:
            return (None, None, None, None), "Run fine-classing and variable-selection before editing manual bins."

        fc_artifact_id = fc_rs.output_artifact_ids[0] if fc_rs.output_artifact_ids else None
        vs_artifact_id = vs_rs.output_artifact_ids[0] if vs_rs.output_artifact_ids else None
        if fc_artifact_id is None or vs_artifact_id is None:
            return (None, None, None, None), "Fine-classing or variable-selection produced no output artifacts."

        fc_artifact = self._store.get_artifact(fc_artifact_id)
        vs_artifact = self._store.get_artifact(vs_artifact_id)
        if fc_artifact is None or vs_artifact is None:
            return (None, None, None, None), "Fine-classing or variable-selection artifacts not found."

        try:
            fc_def = json.loads(self._store.artifact_path(fc_artifact).read_text())
            vs_def = json.loads(self._store.artifact_path(vs_artifact).read_text())
            return (fc_def, vs_def, fc_artifact_id, vs_artifact_id), None
        except (FileNotFoundError, json.JSONDecodeError):
            return (None, None, None, None), "Could not read fine-classing or variable-selection artifact contents."

    def _find_mb_step_id_for_validation(
        self, plan_version_id: str, step_id: str, canonical: str, branch_id: str | None,
    ) -> str:
        """Find the step_id matching a canonical step ID, preferring a
        branch-owned instance when branch_id is given."""
        steps = self._store.get_plan_version_steps(plan_version_id)
        candidate = None
        for s in steps:
            if s.canonical_step_id == canonical:
                if branch_id and s.branch_id == branch_id:
                    return s.step_id
                if candidate is None:
                    candidate = s.step_id
        return candidate or canonical
