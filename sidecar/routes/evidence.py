"""Evidence summary routes — wraps ArtifactEvidenceReader for the frontend.

These routes provide typed evidence access without exposing raw artifact
path or file format to the frontend. Phase 4 of guided workflow sprint.
See ``docs/architecture/artifact-evidence-access.md`` for the approved
read path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from cardre.evidence import ArtifactEvidenceReader
from cardre._evidence.summaries import summarise
from cardre.services.project_registry import get_store_for_project
from cardre.staleness import staleness_detail
from cardre.store import ProjectStore
from sidecar.models import EvidenceStatus, RunStepEvidenceItem, RunStepEvidenceResponse

router = APIRouter(prefix="/runs", tags=["evidence"])


def _to_item(
    store: ProjectStore,
    reader: ArtifactEvidenceReader,
    artifact_id: str,
    staleness_map: dict[str, bool] | None = None,
    pv_steps: list | None = None,
    staleness_details: list | None = None,
) -> RunStepEvidenceItem:
    art = store.get_artifact(artifact_id)
    if art is None:
        return RunStepEvidenceItem(
            artifact_id=artifact_id,
            artifact_type="",
            evidence_kind=None,
            status=EvidenceStatus.MISSING,
        )

    summary_obj = reader.summarise_artifact(artifact_id)
    evidence_kind = getattr(summary_obj, "kind", None) or ""
    parsed = reader.read_optional(artifact_id, None) if evidence_kind else None

    summary_dict, warnings_list = summarise(dict(art), parsed)

    is_stale = False
    staleness_reason: str | None = None
    if staleness_map and staleness_details and evidence_kind:
        for s in pv_steps or []:
            if s.step_id in staleness_map and staleness_map[s.step_id]:
                if s.canonical_step_id == evidence_kind:
                    is_stale = True
                    break
        if is_stale:
            for d in staleness_details:
                if getattr(d, "is_stale", False) and getattr(d, "step_id", None) == s.step_id:
                    staleness_reason = getattr(d, "reason", None) or None
                    break

    source_step_id: str | None = None
    canonical_step_id: str | None = evidence_kind or None
    if summary_obj:
        source_step_id = getattr(summary_obj, "source_artifact_id", None) or None

    status = EvidenceStatus.UNSUPPORTED if summary_dict.get("unsupported_kind") else (
        EvidenceStatus.STALE if is_stale else EvidenceStatus.AVAILABLE
    )

    return RunStepEvidenceItem(
        artifact_id=artifact_id,
        artifact_type=art.artifact_type if art else "",
        role=art.role if art else None,
        media_type=art.media_type if art else "",
        evidence_kind=evidence_kind or None,
        logical_hash=art.logical_hash if art else None,
        created_at=getattr(art, "created_at", "") or "",
        is_stale=is_stale,
        staleness_reason=staleness_reason,
        canonical_step_id=canonical_step_id,
        source_step_id=source_step_id,
        source_branch_id=None,
        status=status,
        summary=summary_dict,
        warnings=warnings_list,
    )


@router.get("/{run_id}/steps/{step_id}/evidence", response_model=RunStepEvidenceResponse)
def get_step_evidence(
    run_id: str,
    step_id: str,
    project_id: str = Query(..., description="Project ID for store lookup"),
):
    store = get_store_for_project(project_id)
    reader = ArtifactEvidenceReader(store)

    run = store.get_run(run_id)
    plan_version_id = run["plan_version_id"] if run else None
    pv_steps = store.get_plan_version_steps(plan_version_id) if plan_version_id else []
    staleness_details = staleness_detail(store, plan_version_id) if plan_version_id else []
    staleness_map: dict[str, bool] = {d.step_id: d.is_stale for d in staleness_details}

    for rs in store.get_run_steps(run_id):
        if rs.step_id == step_id:
            items = [
                _to_item(store, reader, aid,
                         staleness_map=staleness_map, pv_steps=pv_steps,
                         staleness_details=staleness_details)
                for aid in rs.output_artifact_ids
            ]
            step_status = EvidenceStatus.MISSING
            if items:
                if any(i.status == EvidenceStatus.STALE for i in items):
                    step_status = EvidenceStatus.STALE
                elif any(i.status == EvidenceStatus.MISSING for i in items):
                    step_status = EvidenceStatus.PARTIAL
                elif any(i.status == EvidenceStatus.UNSUPPORTED for i in items):
                    step_status = EvidenceStatus.PARTIAL
                else:
                    step_status = EvidenceStatus.AVAILABLE

            return RunStepEvidenceResponse(
                run_id=run_id,
                step_id=step_id,
                items=items,
                status=step_status,
                checked_at=datetime.now(timezone.utc).isoformat(),
                target_branch_id="",
                canonical_step_id=None,
            )

    raise HTTPException(
        status_code=404,
        detail={"code": "STEP_NOT_IN_RUN", "message": f"Step {step_id!r} not found in run {run_id!r}"},
    )


@router.get("/{run_id}/evidence", response_model=RunStepEvidenceResponse)
def get_run_evidence(
    run_id: str,
    project_id: str = Query(..., description="Project ID for store lookup"),
):
    store = get_store_for_project(project_id)
    reader = ArtifactEvidenceReader(store)

    run = store.get_run(run_id)
    plan_version_id = run["plan_version_id"] if run else None
    pv_steps = store.get_plan_version_steps(plan_version_id) if plan_version_id else []
    staleness_details = staleness_detail(store, plan_version_id) if plan_version_id else []
    staleness_map: dict[str, bool] = {d.step_id: d.is_stale for d in staleness_details}

    items: list[RunStepEvidenceItem] = []
    for rs in store.get_run_steps(run_id):
        for aid in rs.output_artifact_ids:
            items.append(_to_item(store, reader, aid,
                                  staleness_map=staleness_map, pv_steps=pv_steps,
                                  staleness_details=staleness_details))

    step_status = EvidenceStatus.MISSING
    if items:
        if any(i.status == EvidenceStatus.STALE for i in items):
            step_status = EvidenceStatus.STALE
        elif any(i.status == EvidenceStatus.MISSING for i in items):
            step_status = EvidenceStatus.PARTIAL
        elif any(i.status == EvidenceStatus.UNSUPPORTED for i in items):
            step_status = EvidenceStatus.PARTIAL
        else:
            step_status = EvidenceStatus.AVAILABLE

    return RunStepEvidenceResponse(
        run_id=run_id,
        step_id=None,
        items=items,
        status=step_status,
        checked_at=datetime.now(timezone.utc).isoformat(),
        target_branch_id="",
        canonical_step_id=None,
    )
