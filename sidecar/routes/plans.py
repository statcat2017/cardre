"""Plan endpoints — step status, staleness, param updates, and manual binning editor."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.services import PlanService
from cardre.services.manual_binning_service import ManualBinningService
from cardre.services.project_registry import load_registry
from cardre.store import ProjectStore
from sidecar.dependencies import project_store_from_registry, resolve_registry_entry
from sidecar.models import (
    ManualBinningEditorStateResponse,
    ManualBinningPreviewRequest,
    ManualBinningPreviewResponse,
    PlanResponse,
    UpdateStepParamsRequest,
    UpdateStepParamsResponse,
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

