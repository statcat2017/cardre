"""Plan endpoints — thin handlers calling use cases."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.mappers import plan_to_response, plan_version_to_response, step_spec_to_response
from cardre.api.schemas import (
    PlanCreateRequest,
    PlanListResponse,
    PlanResponse,
    PlanStepResponse,
    PlanVersionListResponse,
    PlanVersionResponse,
    PlanVersionUpdate,
)
from cardre.bootstrap.container import Container
from cardre.domain.errors import CardreError

router = APIRouter(prefix="/projects/{project_id}", tags=["plans"])


def _uc(container: Container, project_id: str):
    """Build plan use cases for project_id."""

    from cardre.application.plans.commit_plan_version import (
        CommitPlanVersion,
        CommitPlanVersionCommand,
    )
    from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand
    from cardre.application.plans.get_plan import GetPlan, GetPlanCommand
    from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
    from cardre.application.plans.list_plan_versions import (
        ListPlanVersions,
        ListPlanVersionsCommand,
    )
    from cardre.application.plans.list_plans import ListPlans, ListPlansCommand
    from cardre.application.plans.update_plan_version import (
        UpdatePlanVersion,
        UpdatePlanVersionCommand,
    )

    def _factory():
        return container.uow_factory.for_project(project_id)
    return {
        "create": CreatePlan(_factory),
        "list": ListPlans(_factory),
        "get": GetPlan(_factory),
        "get_version": GetPlanVersion(_factory),
        "list_versions": ListPlanVersions(_factory),
        "update_version": UpdatePlanVersion(_factory),
        "commit_version": CommitPlanVersion(_factory),
        "CreatePlanCommand": CreatePlanCommand,
        "GetPlanCommand": GetPlanCommand,
        "GetPlanVersionCommand": GetPlanVersionCommand,
        "ListPlanVersionsCommand": ListPlanVersionsCommand,
        "ListPlansCommand": ListPlansCommand,
        "UpdatePlanVersionCommand": UpdatePlanVersionCommand,
        "CommitPlanVersionCommand": CommitPlanVersionCommand,
    }


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(project_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    plans = uc["list"](uc["ListPlansCommand"](project_id=project_id))
    return PlanListResponse(plans=[plan_to_response(p) for p in plans])


@router.post("/plans", response_model=PlanResponse, status_code=201)
async def create_plan(project_id: str, body: PlanCreateRequest, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        plan = uc["create"](uc["CreatePlanCommand"](project_id=project_id, name=body.name))
        return plan_to_response(plan)
    except CardreError as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(project_id: str, plan_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    plan = uc["get"](uc["GetPlanCommand"](plan_id=plan_id))
    if plan is None:
        raise CardreApiError(code=ErrorCode.PLAN_NOT_FOUND, message=f"Plan {plan_id!r} not found.", status_code=404)
    return plan_to_response(plan)


@router.get("/plans/{plan_id}/versions", response_model=PlanVersionListResponse)
async def list_plan_versions(project_id: str, plan_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    versions = uc["list_versions"](uc["ListPlanVersionsCommand"](plan_id=plan_id))
    return PlanVersionListResponse(versions=[plan_version_to_response(v) for v in versions])


@router.get("/plan-versions/{version_id}", response_model=PlanVersionResponse)
async def get_plan_version(project_id: str, version_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    pv = uc["get_version"](uc["GetPlanVersionCommand"](plan_version_id=version_id))
    if pv is None:
        raise CardreApiError(code=ErrorCode.PLAN_VERSION_NOT_FOUND, message=f"Plan version {version_id!r} not found.", status_code=404)
    return plan_version_to_response(pv)


@router.patch("/plan-versions/{version_id}", response_model=PlanVersionResponse)
async def update_plan_version(project_id: str, version_id: str, body: PlanVersionUpdate, container=Depends(get_container)):
    uc = _uc(container, project_id)
    if body.description is not None:
        uc["update_version"](uc["UpdatePlanVersionCommand"](plan_version_id=version_id, description=body.description))
    pv = uc["get_version"](uc["GetPlanVersionCommand"](plan_version_id=version_id))
    if pv is None:
        raise CardreApiError(code=ErrorCode.PLAN_VERSION_NOT_FOUND, message=f"Plan version {version_id!r} not found.", status_code=404)
    return plan_version_to_response(pv)


@router.post("/plan-versions/{version_id}/commit", response_model=PlanVersionResponse)
async def commit_plan_version(project_id: str, version_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        committed = uc["commit_version"](uc["CommitPlanVersionCommand"](plan_version_id=version_id))
        return plan_version_to_response(committed)
    except CardreError as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


@router.get("/plan-versions/{version_id}/steps", response_model=list[PlanStepResponse])
async def get_plan_version_steps(project_id: str, version_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        steps = uow.plans.get_version_steps(version_id)
    return [step_spec_to_response(s) for s in steps]
