"""Manual-binning review and preview endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cardre.api.dependencies import get_project_store
from cardre.api.schemas import (
    ManualBinningEditRequest,
    ManualBinningEditResponse,
    ManualBinningPreviewRequest,
    ManualBinningPreviewResponse,
    ManualBinningReviewResponse,
    ManualBinningReviewUpdate,
)
from cardre.services.manual_binning_service import (
    extract_event_rate_by_bin,
    extract_iv,
    extract_woe_by_bin,
)
from cardre.services.plan_mutation_service import (
    ManualBinningEditCommand,
    PlanMutationService,
)
from cardre.store.db import ProjectStore
from cardre.store.manual_binning_repo import ManualBinningRepository

router = APIRouter(prefix="/projects/{project_id}/manual-binning", tags=["manual_binning"])


def _review_to_response(review) -> ManualBinningReviewResponse:
    """Convert a ManualBinningReview domain object to a response model."""
    d = review if isinstance(review, dict) else review.to_dict()
    return ManualBinningReviewResponse(
        review_id=d["review_id"],
        plan_version_id=d["plan_version_id"],
        step_id=d["step_id"],
        status=d["status"],
        reviewer_notes=d.get("reviewer_notes", ""),
        affected_downstream_step_ids=d.get("affected_downstream_step_ids", []),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


@router.get("/reviews", response_model=list[ManualBinningReviewResponse])
async def list_reviews(
    project_id: str,
    plan_version_id: str | None = None,
    step_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> list[ManualBinningReviewResponse]:
    """List manual-binning reviews, optionally filtered."""
    repo = ManualBinningRepository(store)
    if step_id and plan_version_id:
        reviews = repo.get_reviews_for_step(plan_version_id, step_id)
    else:
        # Return all reviews for the project (through plans)
        rows = store.execute(
            "SELECT r.* FROM manual_binning_reviews r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? ORDER BY r.created_at",
            (project_id,),
        ).fetchall()
        reviews = [repo._row_to_review(r) for r in rows]
    return [_review_to_response(r) for r in reviews]


@router.get("/reviews/{review_id}", response_model=ManualBinningReviewResponse)
async def get_review(
    project_id: str,
    review_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ManualBinningReviewResponse:
    """Get a single manual-binning review."""
    repo = ManualBinningRepository(store)
    review = repo.get_review(review_id)
    if review is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "REVIEW_NOT_FOUND",
                "message": f"Review {review_id!r} not found.",
            },
        )
    return _review_to_response(review)


@router.patch("/reviews/{review_id}", response_model=ManualBinningReviewResponse)
async def update_review(
    project_id: str,
    review_id: str,
    body: ManualBinningReviewUpdate,
    store: ProjectStore = Depends(get_project_store),
) -> ManualBinningReviewResponse:
    """Update a manual-binning review (status, notes)."""
    repo = ManualBinningRepository(store)
    existing = repo.get_review(review_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "REVIEW_NOT_FOUND",
                "message": f"Review {review_id!r} not found.",
            },
        )
    repo.update_review(
        review_id=review_id,
        status=body.status,
        reviewer_notes=body.reviewer_notes,
    )
    updated = repo.get_review(review_id)
    assert updated is not None
    return _review_to_response(updated)


@router.post("/edit", response_model=ManualBinningEditResponse)
async def apply_manual_binning_edit(
    project_id: str,
    body: ManualBinningEditRequest,
    store: ProjectStore = Depends(get_project_store),
) -> ManualBinningEditResponse:
    """Apply a manual-binning edit (creates new draft version + review)."""
    service = PlanMutationService(store)
    command = ManualBinningEditCommand(
        plan_version_id=body.plan_version_id,
        step_id=body.step_id,
        overrides=body.overrides,
        reviewer_notes=body.reviewer_notes,
        status=body.status,
        affected_downstream_step_ids=body.affected_downstream_step_ids,
    )
    result = service.apply_manual_binning_edit(command)
    return ManualBinningEditResponse(
        new_plan_version_id=result.new_plan_version_id,
        review_id=result.review_id,
        affected_step_ids=result.affected_step_ids,
    )


@router.post("/preview", response_model=ManualBinningPreviewResponse)
async def preview_binning(
    project_id: str,
    body: ManualBinningPreviewRequest,
) -> ManualBinningPreviewResponse:
    """Preview WOE/IV/event-rate for a variable's bin data."""
    woe_by_bin = extract_woe_by_bin(body.variable_data)
    iv = extract_iv(body.variable_data)
    event_rate_by_bin = extract_event_rate_by_bin(body.variable_data)
    return ManualBinningPreviewResponse(
        woe_by_bin=woe_by_bin,
        iv=iv,
        event_rate_by_bin=event_rate_by_bin,
    )
