"""ManualBinningService — manual binning editor state and preview logic.

Extracted from PlanService so binning-specific orchestration does not
bloat the plan query/update service.
"""

from __future__ import annotations

from typing import Any

from cardre.audit import RunStepRecord, StepSpec
from cardre.evidence import ArtifactEvidenceReader, EvidenceError, EvidenceKind
from cardre._evidence.models import WoeIvEvidence
from cardre.reporting.evidence_contract import find_evidence_for_canonical_step
from cardre.nodes import validate_manual_binning_overrides, apply_manual_binning_overrides
from cardre.staleness import compute_staleness
from cardre.store import ProjectStore
from cardre.services.plan_dto import (
    ManualBinningEditorStateResponse,
    ManualBinningPreviewResponse,
    ManualBinningSourceInfo,
    ManualBinningVariableSummary,
    PreviewDiagnostics,
)
from cardre.services.plan_service import PlanValidationError
from cardre.services.step_topology import (
    find_nearest_ancestor_by_canonical_step_id,
    find_nearest_binning_source,
)


# ------------------------------------------------------------------
# Pure helper functions for WOE/IV evidence extraction
# ------------------------------------------------------------------


def _extract_woe_by_bin(evidence: WoeIvEvidence, var: str) -> dict[str, float] | None:
    for v in evidence.variables:
        if v.variable_name == var:
            result: dict[str, float] = {}
            for b in v.bins:
                if b.woe is not None:
                    result[b.bin_id] = b.woe
            return result or None
    return None


def _extract_iv(evidence: WoeIvEvidence, var: str) -> float | None:
    for v in evidence.variables:
        if v.variable_name == var:
            return v.iv
    return None


def _extract_event_rate_by_bin(evidence: WoeIvEvidence, var: str) -> dict[str, float] | None:
    for v in evidence.variables:
        if v.variable_name == var:
            result: dict[str, float] = {}
            for b in v.bins:
                result[b.bin_id] = b.bad_rate
            return result or None
    return None


def _check_sparse_bins(bin_data: dict) -> bool:
    bins = bin_data.get("bins", [])
    if not bins:
        return False
    total = sum(b.get("count", 0) for b in bins)
    if total == 0:
        return False
    return any(b.get("count", 0) / total < 0.05 for b in bins)


def _check_non_monotonic(woe_by_bin: dict[str, float] | None) -> bool:
    if not woe_by_bin or len(woe_by_bin) < 3:
        return False
    values = list(woe_by_bin.values())
    increasing = all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    decreasing = all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    return not (increasing or decreasing)


class ManualBinningService:
    """Manual-binning editor state, preview, and override validation."""

    def __init__(self, store: ProjectStore):
        self._store = store

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

        bin_spec = find_nearest_binning_source(steps, step_id, branch_step_map)
        vs_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        bin_actual_id = bin_spec.step_id if bin_spec else "binning"
        vs_actual_id = vs_spec.step_id if vs_spec else "variable-selection"

        if bin_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason="Binning step is not an ancestor of this manual-binning step.",
                required_steps=["binning"],
            )

        staleness = compute_staleness(self._store, latest_pv_id, branch_id=branch_id)
        bin_stale = staleness.get(bin_actual_id, True)
        vs_stale = staleness.get(vs_actual_id, True) if vs_spec else True

        if bin_stale or vs_stale:
            blocked = []
            if bin_stale:
                blocked.append(bin_actual_id)
            if vs_stale:
                blocked.append(vs_actual_id)
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason=f"Upstream steps stale: {', '.join(blocked)}. Run the pathway to refresh.",
                required_steps=blocked,
            )

        (bin_def, vs_def, bin_artifact_id, vs_artifact_id), err = self._resolve_upstream_defs(
            latest_pv_id, plan_id, bin_step_id=bin_actual_id, vs_step_id=vs_actual_id, branch_id=branch_id,
        )
        if err is not None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id,
                ready=False, blocked_reason=err, required_steps=["binning", "variable-selection"],
            )

        selected_vars = [s["variable"] for s in vs_def.get("selected", [])] if vs_def else []

        source_bins = {}
        if bin_def:
            for v in bin_def.get("variables", []):
                if v["variable"] in selected_vars:
                    source_bins[v["variable"]] = v

        current_overrides = mb_spec.params.get("overrides", [])
        binning_method = (bin_spec.params or {}).get("method", "fine_classing") if bin_spec else "fine_classing"

        warnings = []
        if not selected_vars:
            warnings.append({"message": "No variables selected by variable selection."})
        if not source_bins:
            warnings.append({"message": "No source bins found for selected variables."})

        result = ManualBinningEditorStateResponse(
            plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id, ready=True,
            source=ManualBinningSourceInfo(
                binning_step_id=bin_actual_id, binning_artifact_id=bin_artifact_id,
                binning_method=binning_method,
                variable_selection_step_id=vs_actual_id, variable_selection_artifact_id=vs_artifact_id,
            ),
            selected_variables=selected_vars, source_bins_by_variable=source_bins,
            current_overrides=current_overrides, warnings=warnings,
        )

        try:
            reader = ArtifactEvidenceReader(self._store)
            for run in self._store.list_runs(latest_pv_id):
                if run.get("status") == "succeeded":
                    woe_evidence = find_evidence_for_canonical_step(
                        self._store, latest_pv_id, "final-woe-iv", branch_id=branch_id,
                    )
                    if woe_evidence:
                        for aid in woe_evidence.output_artifact_ids:
                            art = self._store.get_artifact(aid)
                            if art and art.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1":
                                evidence = reader.read(aid, EvidenceKind.WOE_IV_EVIDENCE)
                                if evidence:
                                    summaries = []
                                    for var in result.selected_variables:
                                        woe = _extract_woe_by_bin(evidence, var)
                                        iv = _extract_iv(evidence, var)
                                        event_rate = _extract_event_rate_by_bin(evidence, var)
                                        bin_data = result.source_bins_by_variable.get(var, {})
                                        summaries.append(ManualBinningVariableSummary(
                                            variable=var,
                                            iv=iv,
                                            woe_by_bin=woe,
                                            event_rate_by_bin=event_rate,
                                            missing_count=_count_missing_bins(bin_data),
                                            special_bin_count=_count_special_bins(bin_data),
                                            sparse_bin_warning=_check_sparse_bins(bin_data),
                                            non_monotonic_warning=_check_non_monotonic(woe),
                                        ))
                                    result.variable_summaries = summaries
                                    break
                        break
                    break
        except Exception:
            warnings.append({
                "code": "VARIABLE_SUMMARY_UNAVAILABLE",
                "message": "Variable summary could not be loaded — WOE/IV evidence may be missing or stale.",
            })
            result.warnings = warnings

        # Add warning if selected variables exist but no summaries were built
        if result.selected_variables and not result.variable_summaries:
            no_summary_warning = {
                "code": "VARIABLE_SUMMARY_UNAVAILABLE",
                "message": "No final WOE/IV evidence found for selected variables. Variable summary table not available.",
            }
            if no_summary_warning not in warnings:
                warnings.append(no_summary_warning)
                result.warnings = warnings

        return result

    def preview_overrides(
        self,
        plan_id: str,
        plan_version_id: str,
        overrides: list[dict],
        step_id: str = "manual-binning",
    ) -> ManualBinningPreviewResponse:
        """Validate manual-binning overrides against binning source output."""
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

        bin_spec = find_nearest_binning_source(steps, step_id, branch_step_map)
        vs_spec = find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        bin_step_id = bin_spec.step_id if bin_spec else "binning"
        vs_step_id = vs_spec.step_id if vs_spec else "variable-selection"

        result, err = self._resolve_upstream_defs(
            plan_version_id, plan_id, bin_step_id=bin_step_id, vs_step_id=vs_step_id, branch_id=branch_id,
        )
        if err is not None:
            return ManualBinningPreviewResponse(
                valid=False, diagnostics=PreviewDiagnostics(override_count=0, warnings=[err]),
            )

        bin_def, vs_def, _, _ = result
        selected_vars = {s["variable"] for s in vs_def.get("selected", [])}

        validation_warnings = validate_manual_binning_overrides(bin_def, overrides, selected_vars)
        if validation_warnings:
            return ManualBinningPreviewResponse(
                valid=False, diagnostics=PreviewDiagnostics(override_count=len(overrides), warnings=validation_warnings),
            )

        refined = apply_manual_binning_overrides(bin_def, overrides, selected_vars)
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

        bin_step_id = self._find_mb_step_id_for_validation(plan_version_id, step_id, "binning", branch_id)
        vs_step_id = self._find_mb_step_id_for_validation(plan_version_id, step_id, "variable-selection", branch_id)

        (bin_def, vs_def, _, _), err = self._resolve_upstream_defs(
            plan_version_id, plan_id, bin_step_id=bin_step_id, vs_step_id=vs_step_id, branch_id=branch_id,
        )
        if err is not None:
            raise PlanValidationError("PARAMS_VALIDATION_FAILED", err)

        selected_vars = {s["variable"] for s in vs_def.get("selected", [])} if vs_def else set()
        errors = validate_manual_binning_overrides(bin_def, overrides, selected_vars)
        if errors:
            raise PlanValidationError(
                "PARAMS_VALIDATION_FAILED", "; ".join(errors),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_upstream_defs(
        self, plan_version_id: str, plan_id: str,
        bin_step_id: str = "binning",
        vs_step_id: str = "variable-selection",
        branch_id: str | None = None,
    ) -> tuple:
        """Return (bin_def, vs_def, bin_artifact_id, vs_artifact_id) on success
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

        bin_rs = _find_run_step(bin_step_id)
        vs_rs = _find_run_step(vs_step_id)
        if bin_rs is None or vs_rs is None:
            return (None, None, None, None), "Run binning and variable-selection before editing manual bins."

        bin_artifact_id = bin_rs.output_artifact_ids[0] if bin_rs.output_artifact_ids else None
        vs_artifact_id = vs_rs.output_artifact_ids[0] if vs_rs.output_artifact_ids else None
        if bin_artifact_id is None or vs_artifact_id is None:
            return (None, None, None, None), "Binning or variable-selection produced no output artifacts."

        try:
            reader = ArtifactEvidenceReader(self._store)
            bin_def = reader.read(bin_artifact_id, EvidenceKind.BIN_DEFINITION)
            vs_def = reader.read(vs_artifact_id, EvidenceKind.SELECTION_DEFINITION)
            return (bin_def.to_dict(), vs_def.to_dict(), bin_artifact_id, vs_artifact_id), None
        except EvidenceError:
            return (None, None, None, None), "Could not read binning or variable-selection artifact contents."

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


# ---------------------------------------------------------------------------
# Pure helper functions for manual-binning variable summaries
# ---------------------------------------------------------------------------


def _count_missing_bins(bin_data: dict) -> int:
    """Count bins flagged as missing in the source bin data."""
    return sum(1 for b in bin_data.get("bins", []) if b.get("is_missing") or b.get("bin_type") == "missing")


def _count_special_bins(bin_data: dict) -> int:
    """Count bins flagged as special in the source bin data."""
    return sum(1 for b in bin_data.get("bins", []) if b.get("is_special") or b.get("bin_type") == "special")
