"""Evidence summary routes — wraps ArtifactEvidenceReader for the frontend.

These routes provide typed evidence access without exposing raw artifact
path or file format to the frontend. Phase 4 of guided workflow sprint.
See ``docs/architecture/artifact-evidence-access.md`` for the approved
read path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from cardre.evidence import ArtifactEvidenceReader
from cardre.services.project_registry import get_store_for_project
from sidecar.models import RunStepEvidenceItem, RunStepEvidenceResponse

router = APIRouter(prefix="/runs", tags=["evidence"])


def _to_item(reader: ArtifactEvidenceReader, artifact_id: str) -> RunStepEvidenceItem:
    art = reader._store.get_artifact(artifact_id)
    summary = reader.summarise_artifact(artifact_id)
    return RunStepEvidenceItem(
        artifact_id=artifact_id,
        artifact_type=art.artifact_type if art else "",
        role=art.role if art else None,
        media_type=art.media_type if art else "",
        evidence_kind=getattr(summary, "kind", None) if summary else None,
        summary=summary,
        logical_hash=art.logical_hash if art else None,
    )


@router.get("/{run_id}/steps/{step_id}/evidence", response_model=RunStepEvidenceResponse)
def get_step_evidence(
    run_id: str,
    step_id: str,
    project_id: str = Query(..., description="Project ID for store lookup"),
):
    store = get_store_for_project(project_id)
    reader = ArtifactEvidenceReader(store)

    for rs in store.get_run_steps(run_id):
        if rs.step_id == step_id:
            items = [_to_item(reader, aid) for aid in rs.output_artifact_ids]
            return RunStepEvidenceResponse(run_id=run_id, step_id=step_id, items=items)

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

    items: list[RunStepEvidenceItem] = []
    for rs in store.get_run_steps(run_id):
        for aid in rs.output_artifact_ids:
            items.append(_to_item(reader, aid))

    return RunStepEvidenceResponse(run_id=run_id, step_id=None, items=items)
