"""Method summary and model ranking API endpoints.

Phase 6 adds:
- GET /branches/{branch_id}/method-summary — model family, metrics, limitations
- GET /branch-comparison-snapshots/{snapshot_id}/model-ranking — rank by metric

NOTE: This module is an MVP stub. Evidence-readiness wiring and full
metric resolution are not yet implemented.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cardre.services.project_registry import get_store_for_project
from sidecar.models import MethodSummaryResponse, ModelRankingItem, ModelRankingResponse

router = APIRouter(tags=["method-summary"])


@router.get("/branches/{branch_id}/method-summary", response_model=MethodSummaryResponse)
def get_branch_method_summary(
    branch_id: str,
    project_id: str = Query(..., description="Project ID"),
) -> MethodSummaryResponse:
    """Get method summary for a branch: model family, metrics, limitations.

    MVP stub: returns model artifact metadata when available. Evidence
    readiness resolution is not yet wired.
    """
    from cardre.reporting.evidence_resolver import resolve_branch

    store = get_store_for_project(project_id)
    endpoint_warnings: list[str] = []

    branch = resolve_branch(store, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": f"Branch not found: {branch_id!r}"})

    # Find model artifact from latest run
    model_family = None
    feature_strategy = None
    feature_count = 0
    interpretability_level = None
    champion_eligibility = None
    limitations: list[str] = []
    model_found = False

    # Query run-steps for this branch
    for artifact_ids in store.get_output_artifact_ids_for_branch(branch_id):
        for aid in artifact_ids:
            art = store.get_artifact(aid)
            if art is None:
                continue
            if art.artifact_type == "model" and art.role == "model":
                art_path = store.artifact_path(art)
                try:
                    model_data = json.loads(art_path.read_text())
                except (json.JSONDecodeError, OSError):
                    endpoint_warnings.append(f"Failed to read model artifact {aid}")
                    continue
                model_family = model_data.get("model_family")
                feature_strategy = model_data.get("feature_strategy")
                feature_count = len(model_data.get("features", []))
                interpretability_level = model_data.get("interpretability", {}).get("explanation_level")
                limitations = model_data.get("interpretability", {}).get("limitations", [])
                model_found = True
                break
        if model_found:
            break

    if not model_found:
        endpoint_warnings.append("No model artifact found for this branch")

    # Determine champion eligibility
    if interpretability_level:
        from cardre.nodes.explainability import CHAMPION_ELIGIBILITY
        champion_eligibility = CHAMPION_ELIGIBILITY.get(interpretability_level)

    return MethodSummaryResponse(
        branch_id=branch_id,
        model_family=model_family,
        feature_strategy=feature_strategy,
        feature_count=feature_count,
        interpretability_level=interpretability_level,
        champion_eligibility=champion_eligibility,
        limitations=limitations,
        warnings=endpoint_warnings,
        evidence_readiness={
            "status": "not_implemented",
            "note": "Evidence readiness resolution is not yet wired in this MVP stub.",
        },
    )


@router.get(
    "/branch-comparison-snapshots/{snapshot_id}/model-ranking",
    response_model=ModelRankingResponse,
)
def get_model_ranking(
    snapshot_id: str,
    project_id: str = Query(..., description="Project ID"),
    metric: str = "auc",
) -> ModelRankingResponse:
    """Rank branches by a selected metric from a comparison snapshot."""
    store = get_store_for_project(project_id)

    # Read snapshot
    try:
        row = store.get_comparison_snapshot(snapshot_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "SNAPSHOT_NOT_FOUND", "message": f"Snapshot not found: {snapshot_id!r}"})

        artifact_id = row["comparison_artifact_id"]
        art = store.get_artifact(artifact_id)
        if art is None:
            raise HTTPException(status_code=404, detail={"code": "SNAPSHOT_ARTIFACT_NOT_FOUND", "message": "Snapshot artifact not found"})

        snapshot_data = json.loads(store.artifact_path(art).read_text())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "SNAPSHOT_READ_ERROR", "message": str(e)})

    comparison_id = snapshot_data.get("comparison_id", snapshot_id)

    # Extract branch info from model.branch_level and validation.roles
    model_branches = snapshot_data.get("model", {}).get("branch_level", {})
    validation_by_role = snapshot_data.get("validation", {}).get("roles", {})

    rankings: list[ModelRankingItem] = []
    for branch_id, branch_model in model_branches.items():
        model_family = branch_model.get("model_family")
        feature_count = branch_model.get("feature_count", 0)
        branch_warnings = branch_model.get("warnings", [])

        # Get metric value from validation data across roles
        metric_value = None
        for role in ("test", "train", "oot"):
            role_validation = validation_by_role.get(role, {})
            branch_metrics = role_validation.get(branch_id, {})
            if isinstance(branch_metrics, dict) and metric in branch_metrics:
                val = branch_metrics[metric]
                if val is not None:
                    metric_value = val
                    break

        interpretability = None

        from cardre.nodes.explainability import CHAMPION_ELIGIBILITY
        champion_eligible = CHAMPION_ELIGIBILITY.get(interpretability or "", "not_champion_eligible") in (
            "fully_eligible", "eligible_with_rule_report", "eligible_with_limitation_evidence",
        )

        rankings.append(ModelRankingItem(
            branch_id=branch_id,
            branch_label=branch_id,
            model_family=model_family,
            metric_name=metric,
            metric_value=metric_value,
            interpretability_level=interpretability,
            champion_eligible=champion_eligible,
            limitations_summary=[],
        ))

    # Sort by metric value descending (higher is better for AUC/KS/F1/G-Mean)
    rankings.sort(key=lambda r: r.metric_value if r.metric_value is not None else -1.0, reverse=True)
    for i, r in enumerate(rankings):
        r.rank = i + 1

    return ModelRankingResponse(
        comparison_id=comparison_id,
        metric_name=metric,
        rankings=rankings,
        total_branches=len(rankings),
    )
