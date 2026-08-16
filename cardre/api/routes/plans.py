"""Plan endpoints — thin handlers calling use cases."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode, translate_domain_error
from cardre.api.mappers import plan_to_response, plan_version_to_response, step_spec_to_response
from cardre.api.schemas import (
    CanonicalScorecardVersionRequest,
    PlanCreateRequest,
    PlanListResponse,
    PlanResponse,
    PlanStepResponse,
    PlanVersionListResponse,
    PlanVersionResponse,
    PlanVersionUpdate,
    StepParamsUpdate,
)
from cardre.bootstrap.container import Container

router = APIRouter(prefix="/projects/{project_id}", tags=["plans"])


def _uow_factory(container: Container, project_id: str):
    return lambda: container.uow_factory.for_project(project_id)


def _read_uow_factory(container: Container, project_id: str):
    return lambda: container.uow_factory.read_only(project_id)


@router.get("/plans", response_model=PlanListResponse)
def list_plans(project_id: str, container=Depends(get_container)):
    from cardre.application.plans.list_plans import ListPlans, ListPlansCommand

    plans = ListPlans(_read_uow_factory(container, project_id))(
        ListPlansCommand(project_id=project_id)
    )
    return PlanListResponse(plans=[plan_to_response(p) for p in plans])


@router.post("/plans", response_model=PlanResponse, status_code=201)
def create_plan(project_id: str, body: PlanCreateRequest, container=Depends(get_container)):
    from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand

    plan = CreatePlan(_uow_factory(container, project_id))(
        CreatePlanCommand(project_id=project_id, name=body.name)
    )
    return plan_to_response(plan)


@router.post("/plans/{plan_id}/canonical-version", response_model=PlanVersionResponse, status_code=201)
def create_canonical_scorecard_version(
    project_id: str,
    plan_id: str,
    body: CanonicalScorecardVersionRequest,
    container=Depends(get_container),
):
    from cardre.application.plans.create_canonical_scorecard_version import (
        CreateCanonicalScorecardVersion,
        CreateCanonicalScorecardVersionCommand,
    )
    from cardre.domain.errors import CardreError

    try:
        pv = CreateCanonicalScorecardVersion(
            _uow_factory(container, project_id), container.node_catalogue,
        )(
            CreateCanonicalScorecardVersionCommand(
                plan_id=plan_id,
                source_path=body.source_path,
                target_column=body.target_column,
                good_values=body.good_values,
                bad_values=body.bad_values,
                product=body.product,
                segment=body.segment,
                observation_window=body.observation_window,
                performance_window=body.performance_window,
                reject_inference_position=body.reject_inference_position,
                accept_automated=body.accept_automated,
                smoothing=body.smoothing,
            )
        )
    except CardreError as exc:
        raise translate_domain_error(exc) from exc
    return plan_version_to_response(pv)


@router.get("/plans/{plan_id}", response_model=PlanResponse)
def get_plan(project_id: str, plan_id: str, container=Depends(get_container)):
    from cardre.application.plans.get_plan import GetPlan, GetPlanCommand

    plan = GetPlan(_read_uow_factory(container, project_id))(
        GetPlanCommand(plan_id=plan_id)
    )
    if plan is None:
        raise CardreApiError(code=ErrorCode.PLAN_NOT_FOUND, message=f"Plan {plan_id!r} not found.", status_code=404)
    return plan_to_response(plan)


@router.get("/plans/{plan_id}/versions", response_model=PlanVersionListResponse)
def list_plan_versions(project_id: str, plan_id: str, container=Depends(get_container)):
    from cardre.application.plans.list_plan_versions import (
        ListPlanVersions,
        ListPlanVersionsCommand,
    )

    versions = ListPlanVersions(_read_uow_factory(container, project_id))(
        ListPlanVersionsCommand(plan_id=plan_id)
    )
    return PlanVersionListResponse(versions=[plan_version_to_response(v) for v in versions])


@router.get("/plan-versions/{plan_version_id}", response_model=PlanVersionResponse)
def get_plan_version(project_id: str, plan_version_id: str, container=Depends(get_container)):
    from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand

    pv = GetPlanVersion(_read_uow_factory(container, project_id))(
        GetPlanVersionCommand(plan_version_id=plan_version_id)
    )
    if pv is None:
        raise CardreApiError(code=ErrorCode.PLAN_VERSION_NOT_FOUND, message=f"Plan version {plan_version_id!r} not found.", status_code=404)
    return plan_version_to_response(pv)


@router.patch("/plan-versions/{plan_version_id}", response_model=PlanVersionResponse)
def update_plan_version(project_id: str, plan_version_id: str, body: PlanVersionUpdate, container=Depends(get_container)):
    from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
    from cardre.application.plans.update_plan_version import (
        UpdatePlanVersion,
        UpdatePlanVersionCommand,
    )
    from cardre.domain.errors import CardreError

    if body.description is not None:
        try:
            UpdatePlanVersion(_uow_factory(container, project_id))(
                UpdatePlanVersionCommand(plan_version_id=plan_version_id, description=body.description)
            )
        except CardreError as exc:
            raise translate_domain_error(exc) from exc
    pv = GetPlanVersion(_read_uow_factory(container, project_id))(
        GetPlanVersionCommand(plan_version_id=plan_version_id)
    )
    if pv is None:
        raise CardreApiError(code=ErrorCode.PLAN_VERSION_NOT_FOUND, message=f"Plan version {plan_version_id!r} not found.", status_code=404)
    return plan_version_to_response(pv)


@router.post("/plan-versions/{plan_version_id}/commit", response_model=PlanVersionResponse)
def commit_plan_version(project_id: str, plan_version_id: str, container=Depends(get_container)):
    from cardre.application.plans.commit_plan_version import (
        CommitPlanVersion,
        CommitPlanVersionCommand,
    )
    from cardre.domain.errors import CardreError

    try:
        committed = CommitPlanVersion(
            _uow_factory(container, project_id), container.node_catalogue,
        )(
            CommitPlanVersionCommand(plan_version_id=plan_version_id)
        )
    except CardreError as exc:
        raise translate_domain_error(exc) from exc
    return plan_version_to_response(committed)


@router.patch("/plan-versions/{plan_version_id}/steps/{step_id}", response_model=PlanVersionResponse)
def update_step_params(
    project_id: str,
    plan_version_id: str,
    step_id: str,
    body: StepParamsUpdate,
    container=Depends(get_container),
):
    from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
    from cardre.application.plans.update_step_params import (
        UpdateStepParams,
        UpdateStepParamsCommand,
    )
    from cardre.domain.errors import CardreError

    try:
        UpdateStepParams(_uow_factory(container, project_id), container.node_catalogue)(
            UpdateStepParamsCommand(
                plan_version_id=plan_version_id,
                step_id=step_id,
                params=body.params,
            )
        )
    except CardreError as exc:
        raise translate_domain_error(exc) from exc
    pv = GetPlanVersion(_read_uow_factory(container, project_id))(
        GetPlanVersionCommand(plan_version_id=plan_version_id)
    )
    if pv is None:
        raise CardreApiError(code=ErrorCode.PLAN_VERSION_NOT_FOUND, message=f"Plan version {plan_version_id!r} not found.", status_code=404)
    return plan_version_to_response(pv)


@router.get("/plan-versions/{plan_version_id}/steps", response_model=list[PlanStepResponse])
def get_plan_version_steps(project_id: str, plan_version_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        steps = uow.plans.get_version_steps(plan_version_id)
    return [step_spec_to_response(s, plan_version_id=plan_version_id) for s in steps]
