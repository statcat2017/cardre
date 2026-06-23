"""Evidence summary routes — wraps ArtifactEvidenceReader for the frontend.

These routes provide typed evidence access without exposing raw artifact
path or file format to the frontend. Phase 4 of guided workflow sprint.
See ``docs/architecture/artifact-evidence-access.md`` for the approved
read path.
"""

from __future__ import annotations

import dataclasses
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
    run_step_id: str | None = None,
    canonical_step_id: str | None = None,
    staleness_map: dict[str, bool] | None = None,
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

    parsed_payload = None
    if evidence_kind:
        try:
            from cardre.evidence import EvidenceKind
            ek = EvidenceKind(evidence_kind)
            parsed_payload = reader.read_optional(artifact_id, ek)
        except (ValueError, Exception):
            pass

    summary_dict, warnings_list = summarise(dataclasses.asdict(art), parsed_payload)

    is_stale = False
    staleness_reason: str | None = None
    if run_step_id and staleness_map is not None and staleness_details is not None:
        if staleness_map.get(run_step_id):
            is_stale = True
            for d in staleness_details:
                if getattr(d, "is_stale", False) and getattr(d, "step_id", None) == run_step_id:
                    staleness_reason = getattr(d, "reason", None) or None
                    break

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
        source_step_id=run_step_id,
        source_branch_id=None,
        status=status,
        summary=summary_dict,
        warnings=warnings_list,
    )


def _derive_step_status(items: list[RunStepEvidenceItem]) -> EvidenceStatus:
    if not items:
        return EvidenceStatus.MISSING
    if any(i.status == EvidenceStatus.STALE for i in items):
        return EvidenceStatus.STALE
    if any(i.status in (EvidenceStatus.MISSING, EvidenceStatus.UNSUPPORTED) for i in items):
        return EvidenceStatus.PARTIAL
    return EvidenceStatus.AVAILABLE


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
    step_by_id = {s.step_id: s for s in pv_steps}
    staleness_details = staleness_detail(store, plan_version_id) if plan_version_id else []
    staleness_map: dict[str, bool] = {d.step_id: d.is_stale for d in staleness_details}

    for rs in store.get_run_steps(run_id):
        if rs.step_id == step_id:
            pv_step = step_by_id.get(rs.step_id)
            canonical_step_id = getattr(pv_step, "canonical_step_id", None) if pv_step else None

            items = [
                _to_item(store, reader, aid,
                         run_step_id=rs.step_id,
                         canonical_step_id=canonical_step_id,
                         staleness_map=staleness_map,
                         staleness_details=staleness_details)
                for aid in rs.output_artifact_ids
            ]

            return RunStepEvidenceResponse(
                run_id=run_id,
                step_id=step_id,
                items=items,
                status=_derive_step_status(items),
                checked_at=datetime.now(timezone.utc).isoformat(),
                target_branch_id="",
                canonical_step_id=canonical_step_id,
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
    step_by_id = {s.step_id: s for s in pv_steps}
    staleness_details = staleness_detail(store, plan_version_id) if plan_version_id else []
    staleness_map: dict[str, bool] = {d.step_id: d.is_stale for d in staleness_details}

    items: list[RunStepEvidenceItem] = []
    for rs in store.get_run_steps(run_id):
        pv_step = step_by_id.get(rs.step_id)
        canonical_step_id = getattr(pv_step, "canonical_step_id", None) if pv_step else None
        for aid in rs.output_artifact_ids:
            items.append(_to_item(store, reader, aid,
                                  run_step_id=rs.step_id,
                                  canonical_step_id=canonical_step_id,
                                  staleness_map=staleness_map,
                                  staleness_details=staleness_details))

    return RunStepEvidenceResponse(
        run_id=run_id,
        step_id=None,
        items=items,
        status=_derive_step_status(items),
        checked_at=datetime.now(timezone.utc).isoformat(),
        target_branch_id="",
        canonical_step_id=None,
    )
