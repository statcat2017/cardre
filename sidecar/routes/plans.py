"""Plan endpoints — step status, staleness, param updates, and manual binning editor."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from sidecar.models import (
    PlanResponse,
    StepStatusItem,
    UpdateStepParamsRequest,
    UpdateStepParamsResponse,
    ManualBinningEditorStateResponse,
    ManualBinningSourceInfo,
    ManualBinningPreviewResponse,
    ManualBinningPreviewRequest,
    PreviewDiagnostics,
)
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/plans", tags=["plans"])


def _get_store(project_path: str):
    from cardre.store import ProjectStore
    return ProjectStore(Path(project_path))


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, project_id: str | None = None):
    registry = _load_registry()
    if project_id is None:
        for pid, entry in registry.items():
            store = _get_store(entry["path"])
            plan = store.get_plan(plan_id)
            if plan is not None:
                project_id = pid
                break
    if project_id is None or project_id not in registry:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    entry = registry[project_id]
    store = _get_store(entry["path"])
    plan = store.get_plan(plan_id)
    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        raise HTTPException(status_code=404, detail={"code": "NO_VERSION", "message": "Plan has no versions"})

    steps = store.get_plan_version_steps(latest_pv_id)

    executor = PlanExecutor(NodeRegistry.with_defaults())
    staleness = executor.compute_staleness(store, latest_pv_id)

    run_steps_map: dict[str, Any] = {}

    all_runs = store.list_runs(latest_pv_id)
    if all_runs:
        latest_run_id = all_runs[0]["run_id"]
        for rs in store.get_run_steps(latest_run_id):
            run_steps_map[rs.step_id] = rs

    step_items = []
    for s in steps:
        rs = run_steps_map.get(s.step_id)
        step_items.append(StepStatusItem(
            step_id=s.step_id,
            node_type=s.node_type,
            category=s.category,
            status=rs.status if rs else "not_run",
            is_stale=staleness.get(s.step_id, True),
            position=s.position,
            params=s.params,
        ))

    return PlanResponse(
        plan_id=plan_id,
        project_id=project_id,
        name=plan["name"],
        latest_version_id=latest_pv_id,
        steps=step_items,
    )


@router.post("/{plan_id}/steps/{step_id}/params", response_model=UpdateStepParamsResponse)
def update_step_params(plan_id: str, step_id: str, req: UpdateStepParamsRequest):
    registry = _load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        raise HTTPException(status_code=404, detail={"code": "NO_VERSION", "message": "Plan has no versions"})

    # P1#1: Optimistic concurrency — reject stale base_plan_version_id
    if req.base_plan_version_id != latest_pv_id:
        raise HTTPException(status_code=409, detail={
            "code": "STALE_VERSION",
            "message": "Plan version has changed since your last read. Refresh and retry.",
            "latest_version_id": latest_pv_id,
        })

    steps = store.get_plan_version_steps(latest_pv_id)
    target_step = None
    for s in steps:
        if s.step_id == step_id:
            target_step = s
            break

    if target_step is None:
        raise HTTPException(status_code=404, detail={"code": "STEP_NOT_FOUND", "message": f"No step {step_id} in plan {plan_id}"})

    # P1#2: Validate params against the node's schema before persisting
    new_params = dict(req.params)
    try:
        node = NodeRegistry.with_defaults().instantiate(target_step.node_type)
        validation_errors = node.validate_params(new_params)
        if validation_errors:
            raise HTTPException(status_code=422, detail={
                "code": "PARAMS_VALIDATION_FAILED",
                "message": "; ".join(validation_errors),
            })
    except KeyError:
        pass

    from cardre.audit import json_logical_hash, StepSpec

    new_steps = []
    for s in steps:
        if s.step_id == step_id:
            new_steps.append(StepSpec(
                step_id=s.step_id,
                node_type=s.node_type,
                node_version=s.node_version,
                category=s.category,
                params=new_params,
                params_hash=json_logical_hash(new_params),
                parent_step_ids=s.parent_step_ids,
                branch_label=s.branch_label,
                position=s.position,
            ))
        else:
            new_steps.append(s)

    new_pv_id = store.create_plan_version(
        plan_id=plan_id,
        steps=new_steps,
        description=f"Updated params for {step_id}",
    )

    executor = PlanExecutor(NodeRegistry.with_defaults())
    staleness = executor.compute_staleness(store, new_pv_id)

    stale_ids = [sid for sid, is_stale in staleness.items() if is_stale]

    return UpdateStepParamsResponse(
        plan_id=plan_id,
        new_plan_version_id=new_pv_id,
        changed_step_id=step_id,
        stale_step_ids=stale_ids,
    )


@router.get("/{plan_id}/steps/manual-binning/editor-state", response_model=ManualBinningEditorStateResponse)
def get_manual_binning_editor_state(plan_id: str, project_id: str):
    registry = _load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    store = _get_store(entry["path"])
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        raise HTTPException(status_code=404, detail={"code": "NO_VERSION", "message": "Plan has no versions"})

    steps = store.get_plan_version_steps(latest_pv_id)

    mb_spec = None
    for s in steps:
        if s.step_id == "manual-binning":
            mb_spec = s
            break

    if mb_spec is None:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Manual binning step not found in this plan.",
        )

    executor = PlanExecutor(NodeRegistry.with_defaults())
    ancestors = executor.find_ancestors("manual-binning", steps)
    if "fine-classing" not in ancestors:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Fine-classing step is not an ancestor of manual-binning.",
            required_steps=["fine-classing"],
        )

    if "variable-selection" not in mb_spec.parent_step_ids:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Variable-selection is not a direct parent of manual-binning.",
            required_steps=["variable-selection"],
        )

    staleness = executor.compute_staleness(store, latest_pv_id)
    fc_stale = staleness.get("fine-classing", True)
    vs_stale = staleness.get("variable-selection", True)

    if fc_stale or vs_stale:
        blocked = []
        if fc_stale:
            blocked.append("fine-classing")
        if vs_stale:
            blocked.append("variable-selection")
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason=f"Upstream steps stale: {', '.join(blocked)}. Run the pathway to refresh.",
            required_steps=blocked,
        )

    run_id = store.get_latest_successful_run_id(latest_pv_id)
    if run_id is None:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Run the pathway before editing manual bins.",
            required_steps=["fine-classing", "variable-selection"],
        )

    run_steps = store.get_run_steps(run_id)
    rs_by_step = {rs.step_id: rs for rs in run_steps}

    fc_rs = rs_by_step.get("fine-classing")
    vs_rs = rs_by_step.get("variable-selection")
    if fc_rs is None or vs_rs is None:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Run fine-classing and variable-selection before editing manual bins.",
            required_steps=["fine-classing", "variable-selection"],
        )

    fc_artifact_id = fc_rs.output_artifact_ids[0] if fc_rs.output_artifact_ids else None
    vs_artifact_id = vs_rs.output_artifact_ids[0] if vs_rs.output_artifact_ids else None

    if fc_artifact_id is None or vs_artifact_id is None:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Fine-classing or variable-selection produced no output artifacts.",
        )

    fc_artifact = store.get_artifact(fc_artifact_id)
    vs_artifact = store.get_artifact(vs_artifact_id)
    if fc_artifact is None or vs_artifact is None:
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Fine-classing or variable-selection artifacts not found.",
        )

    try:
        fc_def = json.loads(store.artifact_path(fc_artifact).read_text())
        vs_def = json.loads(store.artifact_path(vs_artifact).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return ManualBinningEditorStateResponse(
            plan_id=plan_id,
            plan_version_id=latest_pv_id,
            ready=False,
            blocked_reason="Could not read fine-classing or variable-selection artifact contents.",
        )

    selected_vars = [s["variable"] for s in vs_def.get("selected", [])]

    source_bins = {}
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
        ready=True,
        source=ManualBinningSourceInfo(
            fine_classing_step_id="fine-classing",
            fine_classing_artifact_id=fc_artifact_id,
            variable_selection_step_id="variable-selection",
            variable_selection_artifact_id=vs_artifact_id,
        ),
        selected_variables=selected_vars,
        source_bins_by_variable=source_bins,
        current_overrides=current_overrides,
        warnings=warnings,
    )


@router.post("/{plan_id}/steps/manual-binning/preview", response_model=ManualBinningPreviewResponse)
def preview_manual_binning_overrides(plan_id: str, req: ManualBinningPreviewRequest):
    registry = _load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    # P2#6: Verify plan_version_id belongs to plan_id
    pv = store.get_plan_version(req.plan_version_id)
    if pv is None or pv["plan_id"] != plan_id:
        raise HTTPException(status_code=400, detail={
            "code": "VERSION_NOT_IN_PLAN",
            "message": "Provided plan_version_id does not belong to this plan.",
        })

    steps = store.get_plan_version_steps(req.plan_version_id)

    executor = PlanExecutor(NodeRegistry.with_defaults())
    run_id = store.get_latest_successful_run_id(req.plan_version_id)
    if run_id is None:
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=0,
                warnings=["No successful run exists for this plan version."],
            ),
        )

    run_steps = store.get_run_steps(run_id)
    rs_by_step = {rs.step_id: rs for rs in run_steps}

    fc_rs = rs_by_step.get("fine-classing")
    vs_rs = rs_by_step.get("variable-selection")
    if fc_rs is None or vs_rs is None:
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=0,
                warnings=["Run fine-classing and variable-selection before previewing."],
            ),
        )

    fc_artifact_id = fc_rs.output_artifact_ids[0] if fc_rs.output_artifact_ids else None
    vs_artifact_id = vs_rs.output_artifact_ids[0] if vs_rs.output_artifact_ids else None
    if fc_artifact_id is None or vs_artifact_id is None:
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=0,
                warnings=["Fine-classing or variable-selection artifacts not found."],
            ),
        )

    fc_artifact = store.get_artifact(fc_artifact_id)
    vs_artifact = store.get_artifact(vs_artifact_id)
    if fc_artifact is None or vs_artifact is None:
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=0,
                warnings=["Fine-classing or variable-selection artifacts not found."],
            ),
        )

    try:
        fc_def = json.loads(store.artifact_path(fc_artifact).read_text())
        vs_def = json.loads(store.artifact_path(vs_artifact).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=0,
                warnings=["Could not read artifact contents."],
            ),
        )

    selected_vars = {s["variable"] for s in vs_def.get("selected", [])}
    var_map = {v["variable"]: dict(v) for v in fc_def.get("variables", []) if v["variable"] in selected_vars}

    validation_warnings: list[str] = []

    for override in req.overrides:
        variable = override.get("variable", "")
        action = override.get("action", "")
        reason = override.get("reason", "")
        source_bin_ids = override.get("source_bin_ids", [])

        if not reason:
            validation_warnings.append(f"Override for '{variable}' requires a non-empty reason")
            continue
        if variable not in var_map:
            validation_warnings.append(f"Override references unknown variable '{variable}'")
            continue
        if action not in ("merge_bins", "group_categories", "isolate_missing", "isolate_special_value"):
            validation_warnings.append(f"Unsupported manual_binning action '{action}' for '{variable}'")
            continue

        var_info = var_map[variable]
        var_bins = list(var_info.get("bins", []))
        bin_id_map = {b["bin_id"]: b for b in var_bins}

        for bid in source_bin_ids:
            if bid not in bin_id_map:
                validation_warnings.append(f"bin_id '{bid}' not found in variable '{variable}'")

        if validation_warnings:
            continue

        if action == "merge_bins":
            if len(source_bin_ids) < 2:
                validation_warnings.append(f"merge_bins for '{variable}' requires at least 2 source bins")
                continue
            kind = var_info.get("kind", "")
            if kind == "numeric":
                bin_positions = [var_bins.index(bin_id_map[bid]) for bid in source_bin_ids]
                expected_positions = list(range(min(bin_positions), max(bin_positions) + 1))
                if bin_positions != expected_positions:
                    validation_warnings.append(
                        f"Numeric bin merge for '{variable}' requires adjacent bins. "
                        f"Source bins at positions {bin_positions} are not contiguous."
                    )
                    continue

    if validation_warnings:
        return ManualBinningPreviewResponse(
            valid=False,
            diagnostics=PreviewDiagnostics(
                override_count=len(req.overrides),
                warnings=validation_warnings,
            ),
        )

    refined: dict[str, Any] = {}
    for var_name, var_info in var_map.items():
        var_info = dict(var_info)
        var_bins = list(var_info.get("bins", []))
        bin_id_map = {b["bin_id"]: b for b in var_bins}

        if not var_bins:
            refined[var_name] = var_info
            continue

        for override in req.overrides:
            if override["variable"] != var_name:
                continue
            variable = override["variable"]
            action = override["action"]
            source_bin_ids = override.get("source_bin_ids", [])

            if action == "merge_bins":
                merged = {
                    "bin_id": f"{variable}_manual_{override.get('new_label', 'merged').lower().replace(' ', '_')}",
                    "label": override.get("new_label", "Merged"),
                    "lower": bin_id_map[source_bin_ids[0]].get("lower"),
                    "upper": bin_id_map[source_bin_ids[-1]].get("upper"),
                    "lower_inclusive": bin_id_map[source_bin_ids[0]].get("lower_inclusive", False),
                    "upper_inclusive": bin_id_map[source_bin_ids[-1]].get("upper_inclusive", True),
                    "categories": None,
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                new_bins.insert(insert_pos, merged)
                var_info["bins"] = new_bins

            elif action == "group_categories":
                grouped = {
                    "bin_id": f"{variable}_manual_grouped",
                    "label": override.get("new_label", "Grouped"),
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": sum([bin_id_map[bid].get("categories", []) for bid in source_bin_ids], []),
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                new_bins.insert(insert_pos, grouped)
                var_info["bins"] = new_bins

        refined[var_name] = var_info

    return ManualBinningPreviewResponse(
        valid=True,
        refined_bins_by_variable=refined,
        diagnostics=PreviewDiagnostics(
            override_count=len(req.overrides),
            warnings=[],
        ),
    )
