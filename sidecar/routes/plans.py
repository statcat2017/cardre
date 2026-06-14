"""Plan endpoints — step status, staleness, param updates, and manual binning editor."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.services import PlanService
from sidecar.models import (
    PlanResponse,
    UpdateStepParamsRequest,
    UpdateStepParamsResponse,
    ManualBinningEditorStateResponse,
    ManualBinningPreviewResponse,
    ManualBinningPreviewRequest,
)
from cardre.services.project_registry import load_registry

router = APIRouter(prefix="/plans", tags=["plans"])


def _get_store(project_path: str):
    from cardre.store import ProjectStore

    return ProjectStore(Path(project_path))


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, project_id: str | None = None):
    registry = load_registry()
    if project_id is None:
        for pid, entry in registry.items():
            store = _get_store(entry["path"])
            if store.get_plan(plan_id) is not None:
                project_id = pid
                break
    if project_id is None or project_id not in registry:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": f"No plan with ID {plan_id}"})

    store = _get_store(registry[project_id]["path"])
    return PlanService(store).get_plan_with_status(plan_id, project_id)


@router.post("/{plan_id}/steps/{step_id}/params", response_model=UpdateStepParamsResponse)
def update_step_params(plan_id: str, step_id: str, req: UpdateStepParamsRequest):
    registry = load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    return PlanService(store).update_params(plan_id, step_id, req.base_plan_version_id, dict(req.params))


@router.get("/{plan_id}/steps/{step_id}/editor-state", response_model=ManualBinningEditorStateResponse)
def get_manual_binning_editor_state(plan_id: str, step_id: str, project_id: str):
    registry = load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    store = _get_store(entry["path"])
    return PlanService(store).get_manual_binning_editor_state(plan_id, step_id=step_id)


@router.post("/{plan_id}/steps/{step_id}/manual-binning/preview", response_model=ManualBinningPreviewResponse)
def preview_manual_binning_overrides(plan_id: str, step_id: str, req: ManualBinningPreviewRequest):
    registry = load_registry()
    entry = registry.get(req.project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {req.project_id}"})

    store = _get_store(entry["path"])
    return PlanService(store).preview_manual_binning(plan_id, req.plan_version_id, req.overrides, step_id=step_id)

