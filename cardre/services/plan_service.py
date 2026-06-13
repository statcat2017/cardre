"""PlanService — plan query, mutation, and aggregation logic.

Owns all business logic for plan endpoints.  Routes are thin delegates
that resolve a store from the project registry, instantiate this service,
and catch ``PlanValidationError`` to map to HTTP responses.
"""

from __future__ import annotations

import json
from typing import Any

from cardre.audit import StepSpec, json_logical_hash, replace_step_params
from cardre.executor import PlanExecutor
from cardre.nodes import validate_manual_binning_overrides, apply_manual_binning_overrides
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore
from sidecar.models import (
    ManualBinningEditorStateResponse,
    ManualBinningPreviewResponse,
    ManualBinningSourceInfo,
    PlanResponse,
    PreviewDiagnostics,
    StepStatusItem,
    UpdateStepParamsResponse,
)


class PlanValidationError(Exception):
    """Raised when plan-level business rules are violated.

    Routes catch this and convert it to ``HTTPException`` using the
    ``status_code``, ``code``, and ``message`` fields.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 422,
        extra: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        detail: dict[str, Any] = {"code": code, "message": message}
        if extra:
            detail.update(extra)
        self.detail = detail
        super().__init__(message)


class PlanService:
    """Business logic for plan query, mutation, and validation."""

    def __init__(self, store: ProjectStore):
        self._store = store
        self._registry = NodeRegistry.with_defaults()
        self._executor = PlanExecutor(self._registry)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_plan_with_status(self, plan_id: str, project_id: str) -> PlanResponse:
        """Return plan details with computed staleness and step statuses."""
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            raise PlanValidationError(
                "NO_VERSION", "Plan has no versions", status_code=404,
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)
        staleness = self._executor.compute_staleness(self._store, latest_pv_id)

        # Run steps from the current version's most recent run
        run_steps_map: dict[str, Any] = {}
        all_runs = self._store.list_runs(latest_pv_id)
        if all_runs:
            latest_run_id = all_runs[0]["run_id"]
            for rs in self._store.get_run_steps(latest_run_id):
                run_steps_map[rs.step_id] = rs

        # Fallback: when the current version has no runs, use the most
        # recent successful run from any version of this plan for
        # non-stale steps.
        fallback_run_steps_map: dict[str, Any] = {}
        if not all_runs:
            run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
            if run_id is not None:
                for rs in self._store.get_run_steps(run_id):
                    fallback_run_steps_map[rs.step_id] = rs

        step_items = []
        for s in steps:
            is_stale = staleness.get(s.step_id, True)
            rs = run_steps_map.get(s.step_id)
            if rs is None and not is_stale:
                rs = fallback_run_steps_map.get(s.step_id)
            status = rs.status if rs else "not_run"
            step_items.append(
                StepStatusItem(
                    step_id=s.step_id,
                    node_type=s.node_type,
                    category=s.category,
                    status=status,
                    is_stale=is_stale,
                    position=s.position,
                    params=s.params,
                    canonical_step_id=s.canonical_step_id,
                    branch_id=s.branch_id,
                )
            )

        return PlanResponse(
            plan_id=plan_id,
            project_id=project_id,
            name=plan["name"],
            latest_version_id=latest_pv_id,
            steps=step_items,
        )

    def update_params(
        self,
        plan_id: str,
        step_id: str,
        base_plan_version_id: str,
        params: dict[str, Any],
    ) -> UpdateStepParamsResponse:
        """Validate params, create a new plan version, return stale steps."""
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            raise PlanValidationError(
                "NO_VERSION", "Plan has no versions", status_code=404,
            )

        if base_plan_version_id != latest_pv_id:
            raise PlanValidationError(
                "STALE_VERSION",
                "Plan version has changed since your last read. Refresh and retry.",
                status_code=409,
                extra={"latest_version_id": latest_pv_id},
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)
        target_step = None
        for s in steps:
            if s.step_id == step_id:
                target_step = s
                break

        if target_step is None:
            raise PlanValidationError(
                "STEP_NOT_FOUND",
                f"No step {step_id} in plan {plan_id}",
                status_code=404,
            )

        new_params = dict(params)

        # Validate params against node schema
        try:
            node = self._registry.instantiate(target_step.node_type)
            validation_errors = node.validate_params(new_params)
            if validation_errors:
                raise PlanValidationError(
                    "PARAMS_VALIDATION_FAILED",
                    "; ".join(validation_errors),
                )
        except KeyError:
            pass

        # Manual-binning: validate overrides against upstream artefacts
        if step_id == "manual-binning":
            overrides = list(new_params.get("overrides", []))
            if overrides:
                self._validate_manual_binning_overrides(plan_id, latest_pv_id, overrides)

        new_steps = replace_step_params(steps, step_id, new_params)

        new_pv_id = self._store.create_plan_version(
            plan_id=plan_id,
            steps=new_steps,
            description=f"Updated params for {step_id}",
        )

        staleness = self._executor.compute_staleness(self._store, new_pv_id)
        stale_ids = [sid for sid, is_stale in staleness.items() if is_stale]

        return UpdateStepParamsResponse(
            plan_id=plan_id,
            new_plan_version_id=new_pv_id,
            changed_step_id=step_id,
            stale_step_ids=stale_ids,
        )

    def _find_nearest_ancestor_by_canonical_step_id(
        self,
        steps: list[StepSpec],
        target_step_id: str,
        branch_step_map: list[dict],
        canonical_step_id: str,
    ) -> StepSpec | None:
        """Branch-aware BFS for nearest ancestor with a given canonical_step_id.

        Algorithm per Phase 4 tech spec Section 15.4.
        """
        steps_by_id = {s.step_id: s for s in steps}
        target = steps_by_id.get(target_step_id)
        if target is None:
            return None

        branch_scope_ids = {row["step_id"] for row in branch_step_map}

        visited = set()
        queue: list[tuple[str, int]] = [(pid, 1) for pid in target.parent_step_ids]
        candidates: list[tuple[int, int, StepSpec]] = []

        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            if current_id not in branch_scope_ids:
                continue
            current = steps_by_id.get(current_id)
            if current is None:
                continue
            if current.canonical_step_id == canonical_step_id:
                candidates.append((depth, current.position, current))
                continue
            for pid in current.parent_step_ids:
                queue.append((pid, depth + 1))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], -item[1]))
        best_depth = candidates[0][0]
        best = [item for item in candidates if item[0] == best_depth]
        if len(best) > 1 and best[0][1] == best[1][1]:
            raise PlanValidationError(
                "AMBIGUOUS_BRANCH_ANCESTOR",
                f"Multiple ancestors found for canonical step {canonical_step_id}",
            )
        return candidates[0][2]

    def get_manual_binning_editor_state(
        self, plan_id: str, step_id: str = "manual-binning"
    ) -> ManualBinningEditorStateResponse:
        """Assemble manual-binning editor state from upstream artefacts.

        Supports both baseline (manual-binning) and branch-owned steps
        (manual-binning__br_xxx).
        """
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            raise PlanValidationError(
                "NO_VERSION", "Plan has no versions", status_code=404,
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)

        mb_spec = None
        for s in steps:
            if s.step_id == step_id:
                mb_spec = s
                break

        if mb_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason="Manual binning step not found in this plan.",
            )

        if mb_spec.canonical_step_id != "manual-binning":
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason=f"Step {step_id} is not a manual-binning step.",
            )

        # Branch-aware ancestor resolution
        branch_id = mb_spec.branch_id
        if branch_id:
            branch_step_map = self._store.get_branch_step_map(branch_id, latest_pv_id)
        else:
            # Baseline: all steps are in scope
            branch_step_map = [{"step_id": s.step_id, "is_shared_upstream": 0, "is_branch_owned": 1} for s in steps]

        fc_spec = self._find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "fine-classing")
        vs_spec = self._find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        fc_actual_id = fc_spec.step_id if fc_spec else "fine-classing"
        vs_actual_id = vs_spec.step_id if vs_spec else "variable-selection"

        if fc_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason="Fine-classing step is not an ancestor of this manual-binning step.",
                required_steps=["fine-classing"],
            )

        ancestors = self._executor.find_ancestors(fc_actual_id, steps)
        if "fine-classing" not in ancestors and fc_spec is None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason="Fine-classing step is not an ancestor of this manual-binning step.",
                required_steps=["fine-classing"],
            )

        staleness = self._executor.compute_staleness(self._store, latest_pv_id)
        fc_stale = staleness.get(fc_actual_id, True)
        vs_stale = staleness.get(vs_actual_id, True) if vs_spec else True

        if fc_stale or vs_stale:
            blocked = []
            if fc_stale:
                blocked.append(fc_actual_id)
            if vs_stale:
                blocked.append(vs_actual_id)
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason=f"Upstream steps stale: {', '.join(blocked)}. Run the pathway to refresh.",
                required_steps=blocked,
            )

        (fc_def, vs_def, fc_artifact_id, vs_artifact_id), err = self._resolve_mb_upstream_defs(
            latest_pv_id, plan_id,
            fc_step_id=fc_actual_id,
            vs_step_id=vs_actual_id,
        )
        if err is not None:
            return ManualBinningEditorStateResponse(
                plan_id=plan_id,
                plan_version_id=latest_pv_id,
                step_id=step_id,
                ready=False,
                blocked_reason=err,
                required_steps=["fine-classing", "variable-selection"],
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
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            step_id=step_id,
            ready=True,
            source=ManualBinningSourceInfo(
                fine_classing_step_id=fc_actual_id,
                fine_classing_artifact_id=fc_artifact_id,
                variable_selection_step_id=vs_actual_id,
                variable_selection_artifact_id=vs_artifact_id,
            ),
            selected_variables=selected_vars,
            source_bins_by_variable=source_bins,
            current_overrides=current_overrides,
            warnings=warnings,
        )

    def preview_manual_binning(
        self,
        plan_id: str,
        plan_version_id: str,
        overrides: list[dict],
        step_id: str = "manual-binning",
    ) -> ManualBinningPreviewResponse:
        """Validate manual-binning overrides against fine-classing output.

        Supports both baseline and branch-owned manual binning steps.
        """
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

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
                valid=False,
                diagnostics=PreviewDiagnostics(override_count=0, warnings=[f"Step {step_id} not found or not manual-binning."]),
            )

        branch_id = mb_spec.branch_id
        if branch_id:
            branch_step_map = self._store.get_branch_step_map(branch_id, plan_version_id)
        else:
            branch_step_map = [{"step_id": s.step_id} for s in steps]

        fc_spec = self._find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "fine-classing")
        vs_spec = self._find_nearest_ancestor_by_canonical_step_id(steps, step_id, branch_step_map, "variable-selection")

        fc_step_id = fc_spec.step_id if fc_spec else "fine-classing"
        vs_step_id = vs_spec.step_id if vs_spec else "variable-selection"

        result, err = self._resolve_mb_upstream_defs(
            plan_version_id, plan_id,
            fc_step_id=fc_step_id,
            vs_step_id=vs_step_id,
        )
        if err is not None:
            return ManualBinningPreviewResponse(
                valid=False,
                diagnostics=PreviewDiagnostics(override_count=0, warnings=[err]),
            )

        fc_def, vs_def, _, _ = result

        selected_vars = {s["variable"] for s in vs_def.get("selected", [])}

        validation_warnings = validate_manual_binning_overrides(fc_def, overrides)
        if validation_warnings:
            return ManualBinningPreviewResponse(
                valid=False,
                diagnostics=PreviewDiagnostics(
                    override_count=len(overrides),
                    warnings=validation_warnings,
                ),
            )

        refined = apply_manual_binning_overrides(fc_def, overrides, selected_vars)

        refined_by_var: dict[str, Any] = {}
        for v in refined.get("variables", []):
            refined_by_var[v["variable"]] = v

        return ManualBinningPreviewResponse(
            valid=True,
            refined_bins_by_variable=refined_by_var,
            diagnostics=PreviewDiagnostics(
                override_count=len(overrides),
                warnings=[],
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_mb_upstream_defs(
        self, plan_version_id: str, plan_id: str,
        fc_step_id: str = "fine-classing",
        vs_step_id: str = "variable-selection",
    ) -> tuple:
        """Return (fc_def, vs_def, fc_artifact_id, vs_artifact_id) on success
        or ((None, None, None, None), error_msg) on failure.

        Resolves fine-classing and variable-selection artifact contents
        from the most recent successful run (falling back to any version).

        Supports both baseline (fine-classing) and branch-owned step IDs
        (fine-classing__br_xxx).
        """
        run_id = self._store.get_latest_successful_run_id(plan_version_id)
        if run_id is None:
            run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
        if run_id is None:
            return (None, None, None, None), "Run fine-classing and variable-selection before editing manual bins."

        run_steps = self._store.get_run_steps(run_id)
        rs_by_step = {rs.step_id: rs for rs in run_steps}

        fc_rs = rs_by_step.get(fc_step_id)
        vs_rs = rs_by_step.get(vs_step_id)
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

    def _validate_manual_binning_overrides(
        self, plan_id: str, plan_version_id: str, overrides: list[dict],
    ) -> None:
        """Validate manual-binning overrides against upstream artefacts.

        Raises ``PlanValidationError`` if any override references an unknown
        variable, missing bin ID, or non-adjacent numeric merge.
        """
        if not overrides:
            return

        (fc_def, _, _, _), err = self._resolve_mb_upstream_defs(plan_version_id, plan_id)
        if err is not None:
            raise PlanValidationError("PARAMS_VALIDATION_FAILED", err)

        errors = validate_manual_binning_overrides(fc_def, overrides)
        if errors:
            raise PlanValidationError(
                "PARAMS_VALIDATION_FAILED", "; ".join(errors),
            )
