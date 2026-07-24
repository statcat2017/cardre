"""Governance endpoints — branches, comparisons, champion, manual binning.

All routes are gated by CARDRE_GOVERNANCE=1 via the require_governance dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode, GovernanceNotEnabled
from cardre.api.mappers import (
    branch_to_response,
    champion_assignment_to_response,
    comparison_to_response,
    manual_binning_review_to_response,
)
from cardre.api.schemas import (
    BranchCreateRequest,
    BranchListResponse,
    BranchResponse,
    ChampionResponse,
    ComparisonListResponse,
    ComparisonResponse,
    ManualBinningEditRequest,
    ManualBinningEditResponse,
    ManualBinningPreviewRequest,
    ManualBinningPreviewResponse,
    ManualBinningReviewResponse,
    ManualBinningReviewUpdate,
)
from cardre.bootstrap.container import Container
from cardre.domain.errors import CardreError
from cardre.domain.errors import GovernanceNotEnabled as DomainGovernanceNotEnabled

router = APIRouter(prefix="/projects/{project_id}/governance", tags=["governance"])


def _require_governance(container: Container = Depends(get_container)):
    if not getattr(container.settings, "governance_enabled", False):
        raise GovernanceNotEnabled()
    return True


def _uc(container: Container, project_id: str):
    from cardre.application.governance.assign_champion import AssignChampion, AssignChampionCommand
    from cardre.application.governance.create_branch import CreateBranch, CreateBranchCommand
    from cardre.application.governance.create_comparison import (
        CreateComparison,
        CreateComparisonCommand,
    )
    from cardre.application.governance.refresh_comparison import (
        RefreshComparison,
        RefreshComparisonCommand,
    )

    def _factory():
        return container.uow_factory.for_project(project_id)
    return {
        "create_branch": CreateBranch(_factory),
        "create_comparison": CreateComparison(_factory),
        "refresh_comparison": RefreshComparison(_factory, None, None),
        "assign_champion": AssignChampion(_factory),
        "CreateBranchCommand": CreateBranchCommand,
        "CreateComparisonCommand": CreateComparisonCommand,
        "RefreshComparisonCommand": RefreshComparisonCommand,
        "AssignChampionCommand": AssignChampionCommand,
    }


# ---- Branches ----


@router.get("/branches", response_model=BranchListResponse, dependencies=[Depends(_require_governance)])
async def list_branches(project_id: str, plan_id: str | None = None, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        branches = uow.branches.list_branches(project_id, plan_id)
    return BranchListResponse(branches=[branch_to_response(b) for b in branches])


@router.get("/branches/{branch_id}", response_model=BranchResponse, dependencies=[Depends(_require_governance)])
async def get_branch(project_id: str, branch_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        branch = uow.branches.get_branch(branch_id)
    if branch is None:
        raise CardreApiError(code=ErrorCode.BRANCH_NOT_FOUND, message=f"Branch {branch_id!r} not found.", status_code=404)
    return branch_to_response(branch)


@router.post("/branches", response_model=BranchResponse, status_code=201, dependencies=[Depends(_require_governance)])
async def create_branch(project_id: str, body: BranchCreateRequest, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        result = uc["create_branch"](uc["CreateBranchCommand"](
            project_id=project_id, plan_id=body.plan_id, name=body.name,
            branch_type=body.branch_type, branch_point_step_id=body.branch_point_step_id or "",
            base_branch_id=body.base_branch_id, base_plan_version_id=body.base_plan_version_id,
            created_reason=body.created_reason,
        ))
        with container.uow_factory.read_only(project_id) as uow:
            branch = uow.branches.get_branch(result.branch_id)
        if branch is None:
            raise CardreApiError(code=ErrorCode.BRANCH_NOT_FOUND, message="Branch not found after creation.", status_code=500)
        return branch_to_response(branch)
    except (CardreError, DomainGovernanceNotEnabled) as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


# ---- Comparisons ----


@router.get("/comparisons", response_model=ComparisonListResponse, dependencies=[Depends(_require_governance)])
async def list_comparisons(project_id: str, plan_id: str | None = None, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        comparisons = uow.comparisons.list_for_project(project_id, plan_id)
    return ComparisonListResponse(comparisons=[comparison_to_response(c) for c in comparisons])


@router.get("/comparisons/{comparison_id}", response_model=ComparisonResponse, dependencies=[Depends(_require_governance)])
async def get_comparison(project_id: str, comparison_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        comparison = uow.comparisons.get_comparison(comparison_id)
    if comparison is None:
        raise CardreApiError(code=ErrorCode.COMPARISON_NOT_FOUND, message=f"Comparison {comparison_id!r} not found.", status_code=404)
    return comparison_to_response(comparison)


@router.post("/comparisons", response_model=ComparisonResponse, status_code=201, dependencies=[Depends(_require_governance)])
async def create_comparison(project_id: str, body: dict, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        result = uc["create_comparison"](uc["CreateComparisonCommand"](
            project_id=project_id, plan_id=body["plan_id"],
            baseline_branch_id=body["baseline_branch_id"],
            challenger_branch_ids=body.get("challenger_branch_ids", []),
        ))
        with container.uow_factory.read_only(project_id) as uow:
            comparison = uow.comparisons.get_comparison(result.comparison_id)
        if comparison is None:
            raise CardreApiError(code=ErrorCode.COMPARISON_NOT_FOUND, message="Comparison not found.", status_code=500)
        return comparison_to_response(comparison)
    except (CardreError, DomainGovernanceNotEnabled) as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


@router.post("/comparisons/{comparison_id}/refresh", response_model=ComparisonResponse, dependencies=[Depends(_require_governance)])
async def refresh_comparison(project_id: str, comparison_id: str, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        uc["refresh_comparison"](uc["RefreshComparisonCommand"](project_id=project_id, comparison_id=comparison_id))
        with container.uow_factory.read_only(project_id) as uow:
            comparison = uow.comparisons.get_comparison(comparison_id)
        if comparison is None:
            raise CardreApiError(code=ErrorCode.COMPARISON_NOT_FOUND, message=f"Comparison {comparison_id!r} not found.", status_code=404)
        return comparison_to_response(comparison)
    except (CardreError, DomainGovernanceNotEnabled) as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


# ---- Champion ----


@router.get("/champion", response_model=ChampionResponse, dependencies=[Depends(_require_governance)])
async def get_champion(project_id: str, plan_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        assignment = uow.champion.get_champion_assignment(plan_id)
    return ChampionResponse(assignment=champion_assignment_to_response(assignment) if assignment is not None else None)


@router.post("/champion/assign", response_model=ChampionResponse, status_code=201, dependencies=[Depends(_require_governance)])
async def assign_champion(project_id: str, body: dict, container=Depends(get_container)):
    uc = _uc(container, project_id)
    try:
        uc["assign_champion"](uc["AssignChampionCommand"](
            project_id=project_id, plan_id=body["plan_id"], branch_id=body["branch_id"],
            comparison_id=body["comparison_id"], comparison_snapshot_id=body["comparison_snapshot_id"],
            assigned_reason=body.get("assigned_reason", ""),
        ))
        with container.uow_factory.read_only(project_id) as uow:
            assignment = uow.champion.get_champion_assignment(body["plan_id"])
        return ChampionResponse(assignment=champion_assignment_to_response(assignment) if assignment is not None else None)
    except (CardreError, DomainGovernanceNotEnabled) as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc


# ---- Manual binning reviews ----


@router.get("/manual-binning-reviews", response_model=list[ManualBinningReviewResponse], dependencies=[Depends(_require_governance)])
async def list_manual_binning_reviews(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        reviews = uow.manual_binning.list_for_project(project_id)
    return [manual_binning_review_to_response(r) for r in reviews]


@router.get("/manual-binning-reviews/{review_id}", response_model=ManualBinningReviewResponse, dependencies=[Depends(_require_governance)])
async def get_manual_binning_review(project_id: str, review_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        review = uow.manual_binning.get_review(review_id)
    if review is None:
        raise CardreApiError(code=ErrorCode.REVIEW_NOT_FOUND, message=f"Review {review_id!r} not found.", status_code=404)
    return manual_binning_review_to_response(review)


@router.patch("/manual-binning-reviews/{review_id}", response_model=ManualBinningReviewResponse, dependencies=[Depends(_require_governance)])
async def update_manual_binning_review(project_id: str, review_id: str, body: ManualBinningReviewUpdate, container=Depends(get_container)):
    with container.uow_factory.for_project(project_id) as uow:
        if body.status is not None or body.reviewer_notes is not None:
            uow.manual_binning.update_review(review_id, body.status or "", body.reviewer_notes or "")
            uow.commit()
        review = uow.manual_binning.get_review(review_id)
    if review is None:
        raise CardreApiError(code=ErrorCode.REVIEW_NOT_FOUND, message=f"Review {review_id!r} not found.", status_code=404)
    return manual_binning_review_to_response(review)


@router.post("/manual-binning-preview", response_model=ManualBinningPreviewResponse, dependencies=[Depends(_require_governance)])
async def preview_manual_binning(project_id: str, body: ManualBinningPreviewRequest, container=Depends(get_container)):
    from cardre.application.plans.manual_binning_preview import (
        extract_event_rate_by_bin,
        extract_iv,
        extract_woe_by_bin,
    )
    return ManualBinningPreviewResponse(
        woe_by_bin=extract_woe_by_bin(body.variable_data),
        iv=extract_iv(body.variable_data),
        event_rate_by_bin=extract_event_rate_by_bin(body.variable_data),
    )


@router.post("/apply-manual-binning-edit", response_model=ManualBinningEditResponse, dependencies=[Depends(_require_governance)])
async def apply_manual_binning_edit(project_id: str, body: ManualBinningEditRequest, container=Depends(get_container)):
    from cardre.application.plans.apply_manual_binning_edit import (
        ApplyManualBinningEdit,
        ApplyManualBinningEditCommand,
    )

    def factory():
        return container.uow_factory.for_project(project_id)

    class _InlineAdapter:
        def create(self, review_id, plan_version_id, step_id, status, reviewer_notes, affected_downstream_step_ids_json, created_at, updated_at):
            uow = container.uow_factory.for_project(project_id)
            try:
                uow._conn.execute(
                    "INSERT INTO manual_binning_reviews (review_id, plan_version_id, step_id, status, "
                    "reviewer_notes, affected_downstream_step_ids_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (review_id, plan_version_id, step_id, status, reviewer_notes,
                     affected_downstream_step_ids_json, created_at, updated_at),
                )
                uow.commit()
            except Exception:
                uow.rollback()
                raise
            finally:
                uow.close()

    uc = ApplyManualBinningEdit(factory, _InlineAdapter())
    try:
        result = uc(ApplyManualBinningEditCommand(
            plan_version_id=body.plan_version_id, step_id=body.step_id,
            overrides=body.overrides, reviewer_notes=body.reviewer_notes,
            status=body.status, affected_downstream_step_ids=body.affected_downstream_step_ids,
        ))
        return ManualBinningEditResponse(
            new_plan_version_id=result.new_plan_version_id,
            review_id=result.review_id,
            affected_step_ids=result.affected_step_ids,
        )
    except CardreError as exc:
        raise CardreApiError(code=ErrorCode.BAD_REQUEST, message=str(exc), status_code=400) from exc
