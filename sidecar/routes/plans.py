"""Plan endpoints — step status, staleness, param updates, and manual binning editor."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.services import PlanService
from cardre.services.manual_binning_service import ManualBinningService
from cardre.services.project_registry import load_registry
from cardre.staleness import staleness_detail
from cardre.store import ProjectStore
from sidecar.dependencies import project_store_from_registry, resolve_registry_entry
from cardre.services.workflow_guidance_service import (
    WorkflowGuidanceService,
    WorkflowGuidanceServiceError,
)
from sidecar.models import (
    ManualBinningEditorStateResponse,
    ManualBinningPreviewRequest,
    ManualBinningPreviewResponse,
    ManualBinningReviewRequest,
    ManualBinningReviewResponse,
    PlanResponse,
    ReadinessItem,
    StalenessItem,
    StalenessResponse,
    UpdateStepParamsRequest,
    UpdateStepParamsResponse,
    WorkflowBlocker,
    WorkflowGuidance,
    WorkflowNextAction,
    WorkflowReportReadiness,
    WorkflowStepGuidance,
)

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, project_id: str | None = None):
    registry = load_registry()
    if project_id is None:
        for pid, entry in registry.items():
            store = project_store_from_registry(pid)
            if store.get_plan(plan_id) is not None:
                project_id = pid
                break
    if project_id is None or project_id not in registry:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    store = project_store_from_registry(project_id)
    plan_dto = PlanService(store).get_plan_with_status(plan_id, project_id)
    return PlanResponse(**dataclasses.asdict(plan_dto))


@router.post("/{plan_id}/steps/{step_id}/params", response_model=UpdateStepParamsResponse)
def update_step_params(plan_id: str, step_id: str, req: UpdateStepParamsRequest):
    entry = resolve_registry_entry(req.project_id)
    store = ProjectStore(Path(entry["path"]))
    result = PlanService(store).update_params(plan_id, step_id, req.base_plan_version_id, dict(req.params))
    return UpdateStepParamsResponse(**dataclasses.asdict(result))


@router.get("/{plan_id}/steps/{step_id}/editor-state", response_model=ManualBinningEditorStateResponse)
def get_manual_binning_editor_state(plan_id: str, step_id: str, project_id: str):
    store = project_store_from_registry(project_id)
    result = ManualBinningService(store).get_editor_state(plan_id, step_id=step_id)
    return ManualBinningEditorStateResponse(**dataclasses.asdict(result))


@router.post("/{plan_id}/steps/{step_id}/manual-binning/preview", response_model=ManualBinningPreviewResponse)
def preview_manual_binning_overrides(plan_id: str, step_id: str, req: ManualBinningPreviewRequest):
    entry = resolve_registry_entry(req.project_id)
    store = ProjectStore(Path(entry["path"]))
    result = ManualBinningService(store).preview_overrides(plan_id, req.plan_version_id, req.overrides, step_id=step_id)
    return ManualBinningPreviewResponse(**dataclasses.asdict(result))


@router.post("/{plan_id}/steps/{step_id}/manual-binning/review", response_model=ManualBinningReviewResponse)
def review_manual_binning(plan_id: str, step_id: str, req: ManualBinningReviewRequest):
    from cardre.services.manual_binning_service import ManualBinningService
    from sidecar.dependencies import resolve_registry_entry
    from cardre.store import ProjectStore
    from pathlib import Path

    entry = resolve_registry_entry(req.project_id)
    store = ProjectStore(Path(entry["path"]))
    PlanService(store)._validate_manual_binning_review_params(req.reviewed, req.accept_automated, req.overrides)

    service = ManualBinningService(store)
    svc_result = service.save_with_review(
        plan_id=plan_id,
        plan_version_id=req.plan_version_id,
        step_id=step_id,
        project_id=req.project_id,
        reviewed=req.reviewed,
        accept_automated=req.accept_automated,
        overrides=req.overrides,
    )

    return ManualBinningReviewResponse(
        plan_id=plan_id,
        new_plan_version_id=svc_result.new_plan_version_id,
        reviewed=req.reviewed,
        accept_automated=req.accept_automated,
    )


@router.get("/{plan_id}/versions/{plan_version_id}/staleness", response_model=StalenessResponse)
def get_staleness_detail(plan_id: str, plan_version_id: str, project_id: str, branch_id: str | None = None):
    store = project_store_from_registry(project_id)
    pv = store.get_plan_version(plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_VERSION_NOT_FOUND", "message": f"No plan version with ID {plan_version_id}"})
    if pv["plan_id"] != plan_id:
        raise HTTPException(status_code=400, detail={"code": "VERSION_NOT_IN_PLAN", "message": "Plan version does not belong to the specified plan"})

    detail_items = staleness_detail(store, plan_version_id, branch_id=branch_id)
    nodes = [StalenessItem(step_id=d.step_id, is_stale=d.is_stale, reason=d.reason) for d in detail_items]
    return StalenessResponse(plan_version_id=plan_version_id, branch_id=branch_id, nodes=nodes)


@router.get("/{plan_id}/workflow-guidance", response_model=WorkflowGuidance)
def get_workflow_guidance(
    plan_id: str,
    project_id: str | None = None,
    branch_id: str | None = None,
    run_id: str | None = None,
):
    from cardre.services.project_registry import load_registry

    if project_id is None:
        registry = load_registry()
        for pid, entry in registry.items():
            store = project_store_from_registry(pid)
            if store.get_plan(plan_id) is not None:
                project_id = pid
                break

    if project_id is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    store = project_store_from_registry(project_id)
    service = WorkflowGuidanceService(store)

    try:
        result = service.build(
            plan_id=plan_id,
            project_id=project_id,
            branch_id=branch_id,
            run_id=run_id,
        )
    except WorkflowGuidanceServiceError as exc:
        raise HTTPException(status_code=400, detail={"code": "GUIDANCE_FAILED", "message": str(exc)})

    return WorkflowGuidance(
        phase=result.phase,
        next_action=WorkflowNextAction(
            kind=result.next_action_kind,
            label=result.next_action_label,
            description=result.next_action_description,
            run_scope=result.next_action_run_scope,
            step_id=result.next_action_step_id,
            action_target=result.next_action_target,
        ),
        blockers=[
            WorkflowBlocker(code=b["code"], message=b["message"], step_id=b.get("step_id"), severity=b.get("severity", "blocker"))
            for b in result.blockers
        ],
        step_guidance={
            cid: WorkflowStepGuidance(
                readiness=sg["readiness"],
                primary_action=sg["primary_action"],
                explanation=sg["explanation"],
                evidence_kinds=sg["evidence_kinds"],
                action_target=sg.get("action_target"),
            )
            for cid, sg in result.step_guidance.items()
        },
        report_readiness=(
            WorkflowReportReadiness(
                ready=result.report_readiness["ready"],
                status=result.report_readiness["status"],
                blockers=[ReadinessItem(**b) for b in result.report_readiness["blockers"]],
                warnings=[ReadinessItem(**w) for w in result.report_readiness["warnings"]],
            )
            if result.report_readiness
            else None
        ),
        branch_id=result.branch_id,
        run_id=result.run_id,
    )

