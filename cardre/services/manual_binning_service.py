"""ManualBinningService — manual binning editor state and preview logic.

Extracted from PlanService so binning-specific orchestration does not
bloat the plan query/update service.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.audit import RunStepRecord, StepSpec, utc_now_iso
from cardre.evidence import ArtifactEvidenceReader, EvidenceError, EvidenceKind
from cardre._evidence.models import WoeIvEvidence
from cardre.engine.binning.diagnostics import (
    MonotonicStatus,
    check_sparse_bins_ratio,
    check_sparse_bins_ratio_count,
    check_zero_cell_bins,
    monotonicity_status,
)
from cardre.readiness import compute_manual_binning_blockers
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
    UpdateStepParamsResponse,
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

        # Compute review status from persisted params
        reviewed = mb_spec.params.get("reviewed", False)
        accept_automated = mb_spec.params.get("accept_automated", False)
        if reviewed:
            review_status = "reviewed"
        elif accept_automated:
            review_status = "accepted_automated"
        else:
            review_status = "not_started"

        # Read latest review annotation for audit fields
        review_annotation = _get_latest_review_annotation(self._store, step_id, latest_pv_id)

        # Build the response with Phase 1 fields
        result = ManualBinningEditorStateResponse(
            plan_id=plan_id, plan_version_id=latest_pv_id, step_id=step_id, ready=True,
            source=ManualBinningSourceInfo(
                binning_step_id=bin_actual_id, binning_artifact_id=bin_artifact_id,
                binning_method=binning_method,
                variable_selection_step_id=vs_actual_id, variable_selection_artifact_id=vs_artifact_id,
            ),
            selected_variables=selected_vars, source_bins_by_variable=source_bins,
            current_overrides=current_overrides, warnings=warnings,
            project_id=plan.get("project_id", ""),
            branch_id=branch_id,
            reviewed=reviewed,
            accept_automated=accept_automated,
            review_status=review_status,
            reviewed_at=review_annotation.get("created_at") if review_annotation else None,
            reviewed_by=review_annotation.get("reviewed_by") if review_annotation else None,
            review_reason=review_annotation.get("review_reason") if review_annotation else None,
            review_reason_code=review_annotation.get("reason_code") if review_annotation else None,
        )

        # Determine effective overrides per variable for the 'edited' flag
        edited_vars: set[str] = set()
        for ov in current_overrides:
            v = ov.get("variable")
            if v:
                edited_vars.add(v)

        try:
            reader = ArtifactEvidenceReader(self._store)
            run_id_found = None
            for run in self._store.list_runs(latest_pv_id):
                if run.get("status") == "succeeded":
                    run_id_found = run["run_id"]
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
                                        bins_list = bin_data.get("bins", [])
                                        total_count = sum(b.get("count", 0) for b in bins_list)
                                        m_count = _count_missing_bins(bin_data)
                                        s_count = _count_special_bins(bin_data)
                                        m_status = monotonicity_status(woe)
                                        summaries.append(ManualBinningVariableSummary(
                                            variable=var,
                                            iv=iv,
                                            woe_by_bin=woe,
                                            event_rate_by_bin=event_rate,
                                            missing_count=m_count,
                                            special_bin_count=s_count,
                                            sparse_bin_warning=check_sparse_bins_ratio(bins_list),
                                            non_monotonic_warning=m_status == MonotonicStatus.non_monotonic,
                                            # Phase 1 widened fields
                                            variable_type=bin_data.get("variable_type", bin_data.get("dtype")),
                                            bin_count=len(bins_list),
                                            missing_rate=(m_count / total_count) if total_count > 0 else None,
                                            special_rate=(s_count / total_count) if total_count > 0 else None,
                                            zero_cell_warning_count=check_zero_cell_bins(bins_list),
                                            sparse_bin_warning_count=check_sparse_bins_ratio_count(bins_list),
                                            monotonicity_status=m_status.value,
                                            edited=var in edited_vars,
                                            review_required=_variable_needs_review(var, bin_data, woe, current_overrides),
                                        ))
                                    result.variable_summaries = summaries
                                    result.run_id = run_id_found
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

        # Compute blocking issues for the review gate
        result.blocking_issues = compute_manual_binning_blockers(
            result.selected_variables,
            result.variable_summaries,
            result.current_overrides,
            branch_id,
            step_id,
        )

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

    def save_with_review(
        self,
        plan_id: str,
        plan_version_id: str,
        step_id: str,
        project_id: str,
        reviewed: bool = False,
        accept_automated: bool = False,
        overrides: list[dict] | None = None,
        reviewed_by: str | None = None,
        reason_code: str | None = None,
        review_reason: str | None = None,
        reopen: bool = False,
    ) -> UpdateStepParamsResponse:
        """Save a review/accept-automated/reopen decision for manual binning.

        When ``reviewed=True``, validates the review-completion gate via
        ``compute_manual_binning_blockers`` before committing.
        When ``reopen=True``, flips ``reviewed=False`` and
        ``accept_automated=False`` with a reason.

        Writes the params through PlanService.update_params atomically
        with the audit annotation.
        """
        from cardre.services.plan_service import PlanService, PlanValidationError

        if reopen:
            if not reason_code or not review_reason:
                raise PlanValidationError(
                    "PARAMS_VALIDATION_FAILED",
                    "reason_code and review_reason are required when reopening review.",
                )
            params: dict[str, Any] = {"reviewed": False, "accept_automated": False}
            action = "reopen"
        else:
            PlanService(self._store)._validate_manual_binning_review_params(
                reviewed, accept_automated, overrides,
                reason_code=reason_code, review_reason=review_reason,
            )
            params = {"reviewed": reviewed, "accept_automated": accept_automated}
            action = "review"

            if reviewed:
                # Gate check: cannot complete while blockers exist
                state = self.get_editor_state(plan_id, step_id=step_id)
                if not state.ready:
                    raise PlanValidationError(
                        "REVIEW_COMPLETION_BLOCKED",
                        "Cannot complete review while the editor is not ready. "
                        f"Blocked: {state.blocked_reason}",
                        status_code=409,
                    )
                blockers = compute_manual_binning_blockers(
                    state.selected_variables,
                    state.variable_summaries,
                    state.current_overrides,
                    branch_id=state.branch_id,
                    step_id=step_id,
                )
                if blockers:
                    messages = "; ".join(b["message"] for b in blockers)
                    raise PlanValidationError(
                        "REVIEW_COMPLETION_BLOCKED",
                        f"Cannot complete review: {messages}",
                        status_code=409,
                        extra={"blocking_issues": blockers},
                    )

        if overrides is not None:
            params["overrides"] = overrides
        elif accept_automated and not reopen:
            params["overrides"] = []

        # Build the annotation payload to write atomically with params
        annotation = {
            "kind": "manual_binning_review",
            "actor": reviewed_by or "user",
            "payload": {
                "reviewed": reviewed if not reopen else False,
                "accept_automated": accept_automated if not reopen else False,
                "override_count": len(overrides) if overrides else 0,
                "base_plan_version_id": plan_version_id,
                "reviewed_by": reviewed_by,
                "reason_code": reason_code,
                "review_reason": review_reason,
                "action": action,
            },
        }

        result = PlanService(self._store).update_params(
            plan_id=plan_id,
            step_id=step_id,
            base_plan_version_id=plan_version_id,
            params=params,
            annotation=annotation,
        )

        return result

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


def _get_latest_review_annotation(store, step_id: str, plan_version_id: str) -> dict | None:
    """Read the most recent manual_binning_review annotation for a step + plan version."""
    try:
        from cardre.store import ProjectStore
        with store.transaction() as conn:
            rows = conn.execute(
                "SELECT payload_json, created_at FROM step_annotations "
                "WHERE step_id = ? AND plan_version_id = ? AND kind = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (step_id, plan_version_id, "manual_binning_review"),
            ).fetchall()
        if not rows:
            return None
        payload = json.loads(rows[0]["payload_json"])
        payload["created_at"] = rows[0]["created_at"]
        return payload
    except Exception:
        return None


def _variable_needs_review(
    variable: str,
    bin_data: dict,
    woe_by_bin: dict[str, float] | None,
    current_overrides: list[dict],
) -> bool:
    """Determine whether a variable still needs manual review.

    A variable needs review when it has warnings (sparse, zero-cell,
    non-monotonic) or unresolved missing/special handling, and those
    warnings are not covered by a valid override with a matching reason
    code.
    """
    bins_list = bin_data.get("bins", [])
    has_sparse = check_sparse_bins_ratio(bins_list)
    has_zero_cell = check_zero_cell_bins(bins_list) > 0
    m_status = monotonicity_status(woe_by_bin)
    has_non_monotonic = m_status == MonotonicStatus.non_monotonic
    has_missing = _count_missing_bins(bin_data) > 0
    has_special = _count_special_bins(bin_data) > 0

    if not (has_sparse or has_zero_cell or has_non_monotonic or has_missing or has_special):
        return False

    # Check if overrides already cover this variable's warnings
    var_overrides = [ov for ov in current_overrides if ov.get("variable") == variable]
    if not var_overrides:
        return True

    override_reason_codes = {ov.get("reason_code") for ov in var_overrides if ov.get("reason_code")}

    if has_sparse and "sparse_bin" not in override_reason_codes:
        return True
    if has_zero_cell and "zero_cell" not in override_reason_codes:
        return True
    if has_non_monotonic and "monotonicity" not in override_reason_codes:
        return True
    if has_missing and "missing_value_treatment" not in override_reason_codes:
        return True
    if has_special and "special_value_treatment" not in override_reason_codes:
        return True

    return False



