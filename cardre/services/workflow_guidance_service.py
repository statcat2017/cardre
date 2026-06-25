"""Workflow guidance aggregation service.

Reserved by ADR 0008. Orchestrates — never duplicates — existing
readiness, staleness, manual-binning, and plan-status sources.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from cardre.errors import CardreError, Diagnostic, Ok, Degraded, Fail, is_ok, is_degraded, is_fail
from cardre.readiness import check_report_readiness
from cardre.services.manual_binning_service import ManualBinningService
from cardre.staleness import compute_staleness
from cardre.step_id import resolve_required_steps
from cardre.store import ProjectStore


# Build stream canonical IDs (matches CONTEXT.md + STEP_DISPLAY_METADATA)
BUILD_STREAM_CANONICAL_IDS: list[str] = [
    "define-metadata",
    "apply-exclusions",
    "profile",
    "validate-target",
    "sample-definition",
    "split",
    "explicit-missing-outlier-treatment",
    "fine-classing",
    "initial-woe-iv",
    "variable-clustering",
    "variable-selection",
    "manual-binning",
    "final-woe-iv",
    "woe-transform-train",
    "logistic-regression",
    "model-fit",
    "score-scaling",
    "build-summary-report",
]

# Validate stream canonical IDs
VALIDATE_STREAM_CANONICAL_IDS: list[str] = [
    "apply-woe",
    "apply-model",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest-stub",
]

# All canonical IDs in pathway order
ALL_CANONICAL_IDS = BUILD_STREAM_CANONICAL_IDS + VALIDATE_STREAM_CANONICAL_IDS


# --- Step metadata constants ---

STEP_PRIMARY_ACTIONS: dict[str, str] = {
    "define-metadata": "Set target and metadata",
    "apply-exclusions": "Review and apply exclusions",
    "profile": "Profile dataset",
    "validate-target": "Validate binary target",
    "sample-definition": "Define sample parameters",
    "split": "Split data",
    "explicit-missing-outlier-treatment": "Configure imputation",
    "fine-classing": "Run auto binning",
    "initial-woe-iv": "Review IV rankings",
    "variable-clustering": "Review clusters",
    "variable-selection": "Select variables",
    "manual-binning": "Edit bins",
    "final-woe-iv": "Review final WOE/IV",
    "woe-transform-train": "Run WOE transform",
    "logistic-regression": "Fit model",
    "model-fit": "Fit model",
    "score-scaling": "Scale scorecard",
    "build-summary-report": "Review summary",
    "apply-woe": "Apply WOE to test/OOT",
    "apply-model": "Score test/OOT",
    "validation-metrics": "Review validation",
    "cutoff-analysis": "Set cutoff",
    "technical-manifest-stub": "Export manifest",
}

STEP_EXPLANATIONS: dict[str, str] = {
    "define-metadata": "Define the target column, good/bad categories, and population metadata. This anchors all downstream modelling.",
    "apply-exclusions": "Apply exclusion rules to filter the population before modelling.",
    "profile": "Generate column-level statistics and data quality summary for the imported dataset.",
    "validate-target": "Verify the target column has valid binary values for scorecard modelling.",
    "sample-definition": "Define sampling method, weights, and population parameters for the development sample.",
    "split": "Split the data into train, test, and out-of-time samples. Roles are immutable once set.",
    "explicit-missing-outlier-treatment": "Configure imputation and outlier treatment strategies before binning.",
    "fine-classing": "Generate fine bins for all candidate variables automatically.",
    "initial-woe-iv": "Calculate WOE and IV for initial variable ranking before selection.",
    "variable-clustering": "Group redundant variables and suggest cluster representatives to reduce multicollinearity.",
    "variable-selection": "Filter to the strongest candidate variables for coarse classing and modelling.",
    "manual-binning": "Review automated bins, merge sparse bins, record overrides, and confirm modelling judgement.",
    "final-woe-iv": "Recalculate WOE and IV after manual bin edits to confirm variable strength.",
    "woe-transform-train": "Apply bin definitions to produce WOE-transformed training data for logistic regression.",
    "logistic-regression": "Fit a logistic regression model on the WOE-transformed training data.",
    "model-fit": "Fit a logistic regression model on the WOE-transformed training data.",
    "score-scaling": "Convert log-odds to scorecard points with target odds and points-to-double-odds.",
    "build-summary-report": "Generate model summary, characteristic reports, and cut-off analysis.",
    "apply-woe": "Apply WOE mappings to test and OOT data using the fitted bin definitions.",
    "apply-model": "Score test and OOT data with the fitted model to produce score distributions.",
    "validation-metrics": "Compute AUC, Gini, KS, and calibration metrics by sample role (train/test/OOT).",
    "cutoff-analysis": "Analyse approval rate, bad rate, and capture rate at various score cutoffs.",
    "technical-manifest-stub": "Export the technical manifest and audit evidence for governance review.",
}

STEP_EVIDENCE_KINDS: dict[str, list[str]] = {
    "define-metadata": ["modelling_metadata"],
    "apply-exclusions": ["exclusion_summary"],
    "profile": ["profile_summary"],
    "validate-target": ["modelling_metadata"],
    "sample-definition": ["sample_definition"],
    "split": ["split_summary"],
    "explicit-missing-outlier-treatment": ["bin_definition"],
    "fine-classing": ["bin_definition"],
    "initial-woe-iv": ["woe_iv_evidence"],
    "variable-clustering": ["variable_clustering"],
    "variable-selection": ["selection_definition"],
    "manual-binning": ["bin_definition", "woe_iv_evidence", "manual_binning_overrides"],
    "final-woe-iv": ["woe_iv_evidence"],
    "woe-transform-train": ["woe_transform_evidence"],
    "logistic-regression": ["model_artifact"],
    "model-fit": ["model_artifact"],
    "score-scaling": ["score_scaling"],
    "build-summary-report": ["report_bundle"],
    "apply-woe": ["apply_woe_evidence"],
    "apply-model": ["apply_model_evidence"],
    "validation-metrics": ["validation_metrics"],
    "cutoff-analysis": ["cutoff_analysis"],
    "technical-manifest-stub": ["technical_manifest_index"],
}


@dataclasses.dataclass
class WorkflowGuidanceResult:
    """Internal result DTO — Phase 1's sidecar route maps this to Pydantic."""
    phase: str
    next_action_kind: str
    next_action_label: str
    next_action_description: str
    next_action_run_scope: str | None
    next_action_step_id: str | None
    next_action_target: str | None
    blockers: list[dict[str, Any]]
    step_guidance: dict[str, dict[str, Any]]
    report_readiness: dict[str, Any] | None
    branch_id: str | None
    run_id: str | None
    degraded: bool = False
    diagnostics: list[Diagnostic] = dataclasses.field(default_factory=list)


class WorkflowGuidanceServiceError(Exception):
    """Raised when guidance cannot be produced for the given keys."""


class WorkflowGuidanceService:
    """Aggregates workflow guidance by delegating to existing services."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._manual_binning_service = ManualBinningService(store)

    def build(
        self,
        plan_id: str,
        project_id: str,
        branch_id: str | None = None,
        run_id: str | None = None,
    ) -> WorkflowGuidanceResult:
        """Build workflow guidance for the given plan/branch/run.

        At least one of branch_id or run_id is required.
        If both are supplied they must be consistent:
        run.plan_version_id must equal branch.head_plan_version_id.
        Raises ``WorkflowGuidanceServiceError`` on invalid keys.
        """
        if branch_id is None and run_id is None:
            raise WorkflowGuidanceServiceError(
                "At least one of branch_id or run_id is required."
            )

        # --- Fix 1: consistency check when both supplied ---
        if branch_id is not None and run_id is not None:
            run = self._store.get_run(run_id)
            branch = self._store.get_branch(branch_id)
            if run is None:
                raise WorkflowGuidanceServiceError(f"Run {run_id!r} not found")
            if branch is None:
                raise WorkflowGuidanceServiceError(f"Branch {branch_id!r} not found")
            if run["plan_version_id"] != branch["head_plan_version_id"]:
                raise WorkflowGuidanceServiceError(
                    "run_id and branch_id are inconsistent: "
                    f"run's plan_version_id {run['plan_version_id']!r} "
                    f"does not match branch head {branch['head_plan_version_id']!r}"
                )

        # Resolve branch_id from run_id if needed
        if branch_id is None and run_id is not None:
            run = self._store.get_run(run_id)
            if run is not None:
                pv_id = run["plan_version_id"]
                for b in self._store.list_branches(project_id):
                    if b.get("head_plan_version_id") == pv_id:
                        branch_id = b["branch_id"]
                        break

        # --- Fix 2: only successful runs, no fallback to failed ---
        if run_id is None and branch_id is not None:
            branch = self._store.get_branch(branch_id)
            if branch is not None:
                head_pv = branch.get("head_plan_version_id")
                if head_pv:
                    runs = self._store.list_runs(head_pv)
                    for r in runs:
                        if r.get("status") == "succeeded":
                            run_id = r["run_id"]
                            break
                    # No fallback — run_id stays None if no successful run

        # Get branch step map
        resolved_branch_id = branch_id or ""
        head_pv_id = _resolve_head_pv_id(self._store, plan_id, resolved_branch_id)
        step_map = self._store.get_branch_step_map(resolved_branch_id, head_pv_id) if resolved_branch_id else []

        # --- Fix 3: derive step status from branch+run context ---
        # Get plan version steps directly from store
        plan_steps = self._store.get_plan_version_steps(head_pv_id) if head_pv_id else []

        # Compute staleness with branch context
        staleness_map: dict[str, bool] = {}
        diagnostics: list[Diagnostic] = []
        if head_pv_id:
            try:
                staleness_map = compute_staleness(
                    self._store, head_pv_id, branch_id=resolved_branch_id or None,
                )
            except CardreError as e:
                diagnostics.append(Diagnostic(
                    code="STALENESS_UNAVAILABLE",
                    message="Could not compute staleness; pathway freshness is unknown.",
                    source="workflow_guidance.compute_staleness",
                    exception_type=e.__class__.__name__,
                    context={"plan_version_id": head_pv_id, "branch_id": resolved_branch_id},
                ))
                staleness_map = {}

        # Build run step status lookup (keyed by step_id)
        run_step_status: dict[str, str] = {}
        if run_id:
            try:
                for rs in self._store.get_run_steps(run_id):
                    run_step_status[rs.step_id] = rs.status
            except Exception as e:
                raise WorkflowGuidanceServiceError(
                    f"Could not load run steps for run {run_id}: {e}"
                )

        # Resolve canonical step -> actual step_id through branch step map
        resolved_canonical = resolve_required_steps(
            branch_id=resolved_branch_id or "unknown",
            canonical_step_ids=ALL_CANONICAL_IDS,
            branch_step_map=step_map,
        ) if resolved_branch_id else {}

        # Build a status map keyed by canonical ID — from branch+run context
        status_by_canonical: dict[str, Any] = _build_canonical_status_map(
            plan_steps=plan_steps,
            resolved_canonical=resolved_canonical,
            step_map=step_map,
            staleness_map=staleness_map,
            run_step_status=run_step_status,
            canonical_ids=ALL_CANONICAL_IDS,
        )

        # Build step guidance for all canonical steps
        step_guidance: dict[str, dict[str, Any]] = {}
        for cid in ALL_CANONICAL_IDS:
            sg = self._step_guidance_for(
                canonical_id=cid,
                head_pv_id=head_pv_id,
                plan_id=plan_id,
                branch_id=resolved_branch_id,
                step_map=step_map,
                status=status_by_canonical.get(cid),
                diagnostics=diagnostics,
            )
            step_guidance[cid] = sg

        # Report readiness (only when run_id resolved) — computed once, used
        # by both _derive_phase and the result.
        report_readiness = None
        readiness_r: Ok | Degraded | Fail | None = None
        if run_id is not None and branch_id:
            try:
                result = check_report_readiness(
                    store=self._store,
                    project_id=project_id,
                    run_id=run_id,
                    target_branch_id=branch_id,
                    report_mode="branch",
                )
                report_readiness = result.to_dict()
                readiness_r = Ok(report_readiness)
            except Exception as e:
                diagnostics.append(Diagnostic(
                    code="REPORT_READINESS_UNAVAILABLE",
                    message="Could not check report readiness.",
                    source="workflow_guidance.check_report_readiness",
                    context={"run_id": run_id, "branch_id": branch_id},
                ))
                report_readiness = {"ready": False, "status": "unavailable", "blockers": [], "warnings": []}
                readiness_r = Degraded(report_readiness, [Diagnostic(
                    code="REPORT_READINESS_UNAVAILABLE",
                    message="Could not check report readiness.",
                    context={"run_id": run_id, "branch_id": branch_id},
                )])

        # Derive phase (uses readiness_r instead of calling check_report_readiness again)
        phase = self._derive_phase(
            project_id=project_id,
            step_guidance=step_guidance,
            plan_id=plan_id,
            run_id=run_id,
            branch_id=resolved_branch_id,
            readiness_r=readiness_r,
        )

        # Collect blockers
        blockers = self._collect_blockers(step_guidance)

        # Derive next action
        next_action = self._derive_next_action(phase, step_guidance, blockers, diagnostics)

        degraded = len(diagnostics) > 0

        return WorkflowGuidanceResult(
            phase=phase,
            next_action_kind=next_action["kind"],
            next_action_label=next_action["label"],
            next_action_description=next_action["description"],
            next_action_run_scope=next_action.get("run_scope"),
            next_action_step_id=next_action.get("step_id"),
            next_action_target=next_action.get("action_target"),
            blockers=blockers,
            step_guidance=step_guidance,
            report_readiness=report_readiness,
            branch_id=resolved_branch_id or None,
            run_id=run_id,
            degraded=degraded,
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _step_guidance_for(
        self,
        canonical_id: str,
        head_pv_id: str,
        plan_id: str,
        branch_id: str,
        step_map: list[dict[str, Any]],
        status: dict[str, Any] | None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        readiness = "ready"
        explanation = STEP_EXPLANATIONS.get(canonical_id, "")
        primary_action = STEP_PRIMARY_ACTIONS.get(canonical_id, "Configure")
        action_target = None
        diags = diagnostics or []

        if status is None:
            readiness = "needs_config"
        elif status.get("is_stale", False):
            readiness = "stale"
        elif status.get("status", "") == "succeeded":
            readiness = "complete"
        elif status.get("status", "") == "failed":
            readiness = "blocked"
        elif status.get("status", "") in ("not_run", ""):
            readiness = "needs_config"

        # Check manual-binning readiness specifically
        if canonical_id == "manual-binning" and branch_id:
            try:
                resolved = resolve_required_steps(
                    branch_id=branch_id,
                    canonical_step_ids=["manual-binning"],
                    branch_step_map=step_map,
                )
                ref = resolved.get("manual-binning")
                actual_step_id = ref.step_id if ref else "manual-binning"

                state = self._manual_binning_service.get_editor_state(
                    plan_id, step_id=actual_step_id,
                )
                if not state.ready:
                    readiness = "blocked"
                    explanation = state.blocked_reason or explanation
                    primary_action = "Resolve manual-binning blockers"
            except Exception as e:
                readiness = "blocked"
                explanation = "Manual-binning state could not be loaded."
                primary_action = "Resolve manual-binning blockers"
                diags.append(Diagnostic(
                    code="MANUAL_BINNING_STATE_UNAVAILABLE",
                    message=f"Could not load manual-binning editor state: {e}",
                    context={"step_id": actual_step_id, "plan_id": plan_id, "branch_id": branch_id},
                ))

        if canonical_id == "manual-binning" and status:
            params = status.get("params", {})
            reviewed = params.get("reviewed", False)
            accept_automated = params.get("accept_automated", False)

            if reviewed or accept_automated:
                readiness = "complete"
                primary_action = "Reviewed"
            elif readiness != "blocked":
                readiness = "ready"
                primary_action = "Mark bin review complete"

        if canonical_id == "manual-binning":
            try:
                resolved = resolve_required_steps(
                    branch_id=branch_id,
                    canonical_step_ids=["manual-binning"],
                    branch_step_map=step_map,
                ) if branch_id else {}
                ref = resolved.get("manual-binning") if isinstance(resolved, dict) else None
                actual_step_id = ref.step_id if ref else "manual-binning"
                state = self._manual_binning_service.get_editor_state(
                    plan_id, step_id=actual_step_id,
                )
                if state.selected_variables:
                    action_target = f"manual_binning:N_selected={len(state.selected_variables)}"
                else:
                    action_target = None
            except Exception as e:
                action_target = None
                diags.append(Diagnostic(
                    code="ACTION_TARGET_UNAVAILABLE",
                    message=f"Could not compute selected-variable count: {e}",
                    severity="warning",
                    context={"step_id": canonical_id},
                ))

        return {
            "readiness": readiness,
            "primary_action": primary_action,
            "explanation": explanation,
            "evidence_kinds": STEP_EVIDENCE_KINDS.get(canonical_id, []),
            "action_target": action_target,
        }

    def _derive_phase(
        self,
        project_id: str,
        step_guidance: dict[str, dict[str, Any]],
        plan_id: str | None,
        run_id: str | None,
        branch_id: str | None,
        readiness_r: Ok | Degraded | Fail | None = None,
    ) -> str:
        # Check if any dataset has been imported (has train role)
        has_train = False
        for art in self._store.list_artifacts_for_project(project_id):
            if art.role == "train":
                has_train = True
                break
        if not has_train:
            return "setup"

        # Check build stream
        for cid in BUILD_STREAM_CANONICAL_IDS:
            sg = step_guidance.get(cid, {})
            r = sg.get("readiness", "needs_config")
            if r in ("blocked", "needs_config", "stale"):
                return "build"

        # Check validate stream
        for cid in VALIDATE_STREAM_CANONICAL_IDS:
            sg = step_guidance.get(cid, {})
            r = sg.get("readiness", "needs_config")
            if r in ("blocked", "needs_config", "stale"):
                return "validate"

        # All build + validate steps complete. Check report readiness.
        if run_id is None or branch_id is None:
            return "build"

        # Use the already-computed readiness result (no second call)
        if readiness_r is None or is_fail(readiness_r):
            return "report"
        if is_degraded(readiness_r):
            return "report"
        if not readiness_r.value.get("ready", False):
            return "report"
        return "ready"

    def _collect_blockers(
        self, step_guidance: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        for cid, sg in step_guidance.items():
            r = sg.get("readiness", "")
            if r == "blocked":
                blockers.append({
                    "code": "STEP_BLOCKED",
                    "message": f"Step {cid} is blocked: {sg.get('explanation', '')}",
                    "step_id": cid,
                    "severity": "blocker",
                })
        return blockers

    def _derive_next_action(
        self,
        phase: str,
        step_guidance: dict[str, dict[str, Any]],
        blockers: list[dict[str, Any]],
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        if phase == "setup":
            return {
                "kind": "import_dataset",
                "label": "Import dataset",
                "description": "Import a CSV or Parquet dataset to begin the scorecard pathway.",
                "run_scope": None,
                "step_id": None,
                "action_target": "dataset",
            }

        if blockers:
            b = blockers[0]
            return {
                "kind": "resolve_blocker",
                "label": "View blockers",
                "description": b.get("message", "A step is blocked. Resolve the issue to continue."),
                "run_scope": None,
                "step_id": b.get("step_id"),
                "action_target": None,
            }

        # Find first non-complete step
        for cid in ALL_CANONICAL_IDS:
            sg = step_guidance.get(cid, {})
            r = sg.get("readiness", "")
            if r == "needs_config":
                return {
                    "kind": "configure_step",
                    "label": f"Configure {STEP_PRIMARY_ACTIONS.get(cid, cid)}",
                    "description": sg.get("explanation", ""),
                    "run_scope": None,
                    "step_id": cid,
                    "action_target": None,
                }
            if r == "edit_bins" or (cid == "manual-binning" and r == "ready"):
                return {
                    "kind": "edit_bins",
                    "label": "Edit bins",
                    "description": "Review and refine automated bin boundaries.",
                    "run_scope": None,
                    "step_id": cid,
                    "action_target": "manual_binning",
                }
            if r == "stale":
                return {
                    "kind": "run_pathway",
                    "label": "Run pathway",
                    "description": f"Re-run the pathway to refresh stale step {cid}.",
                    "run_scope": "full_plan",
                    "step_id": None,
                    "action_target": None,
                }

        if phase in ("report", "validate"):
            return {
                "kind": "run_pathway",
                "label": "Run pathway",
                "description": "Some steps need running to complete the pathway.",
                "run_scope": "full_plan",
                "step_id": None,
                "action_target": None,
            }

        if phase == "ready":
            return {
                "kind": "export_report",
                "label": "Open exports",
                "description": "The scorecard is ready. Generate the audit pack.",
                "run_scope": None,
                "step_id": None,
                "action_target": "exports",
            }

        # If degraded diagnostics exist, suggest resolving them
        if diagnostics:
            return {
                "kind": "resolve_diagnostics",
                "label": "Resolve diagnostics",
                "description": "Some checks could not be completed. Review diagnostics before continuing.",
                "run_scope": None,
                "step_id": None,
                "action_target": "diagnostics",
            }

        # Fallback
        return {
            "kind": "run_pathway",
            "label": "Run pathway",
            "description": "Complete the remaining steps.",
            "run_scope": "full_plan",
            "step_id": None,
            "action_target": None,
        }


def _resolve_head_pv_id(store: ProjectStore, plan_id: str, branch_id: str) -> str:
    """Resolve the plan version ID to use for step-map lookups."""
    if branch_id:
        branch = store.get_branch(branch_id)
        if branch is not None:
            head = branch.get("head_plan_version_id")
            if head:
                return head
    latest = store.get_latest_plan_version_id(plan_id)
    return latest or ""


def _build_canonical_status_map(
    plan_steps: list[Any],
    resolved_canonical: dict[str, Any],
    step_map: list[dict[str, Any]],
    staleness_map: dict[str, bool],
    run_step_status: dict[str, str],
    canonical_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Build a canonical-step-keyed status dict from branch+run context.

    Returns dict keyed by canonical_step_id with fields:
    step_id, canonical_step_id, status, is_stale, params, node_type.
    """
    # Build lookup from plan steps by step_id
    plan_by_step: dict[str, Any] = {}
    for ps in plan_steps:
        plan_by_step[ps.step_id] = ps

    # For each canonical step, determine the actual step_id from
    # the branch step map, then derive status from run + staleness.
    result: dict[str, dict[str, Any]] = {}

    # Also build a direct canonical->plan-step map for non-branched projects
    canonical_to_plan: dict[str, Any] = {}
    for ps in plan_steps:
        cid = getattr(ps, "canonical_step_id", None) or ps.step_id
        if cid not in canonical_to_plan:
            canonical_to_plan[cid] = ps

    for cid in canonical_ids:
        actual_step_id = cid
        resolved = resolved_canonical.get(cid)
        if resolved is not None:
            actual_step_id = getattr(resolved, "step_id", None) or cid
        else:
            # Fallback: try to find the canonical ID from direct plan steps
            ps = canonical_to_plan.get(cid)
            if ps is not None:
                actual_step_id = ps.step_id

        plan_step = plan_by_step.get(actual_step_id) or canonical_to_plan.get(cid)

        is_stale = staleness_map.get(actual_step_id, False)
        run_status = run_step_status.get(actual_step_id, "")

        status = run_status
        if not status:
            status = getattr(plan_step, "status", "") if plan_step else "not_run"

        result[cid] = {
            "step_id": actual_step_id,
            "canonical_step_id": cid,
            "status": status,
            "is_stale": is_stale,
            "node_type": getattr(plan_step, "node_type", "") if plan_step else "",
            "params": getattr(plan_step, "params", {}) if plan_step else {},
        }

    return result
