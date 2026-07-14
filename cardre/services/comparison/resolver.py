"""Shared evidence resolver for comparison section collectors."""

from __future__ import annotations

from typing import Any, cast

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.evidence_locator import EvidenceLocator
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.branch_repo import BranchRepository
from cardre.store.db import ProjectStore


def find_typed_artifact(
    store: ProjectStore,
    step_map: list[dict[str, Any]],
    cs: str,
    pv_id: str,
    evidence_branch_id: str | None,
    kinds: tuple[EvidenceKind, ...],
) -> dict[str, Any] | None:
    """Find the typed evidence for a canonical step."""
    reader = ArtifactEvidenceReader(store)
    locator = EvidenceLocator(store)
    for row in step_map:
        if row["canonical_step_id"] == cs:
            resolved = locator.resolve(pv_id, row["step_id"], branch_id=evidence_branch_id)
            rs = resolved.run_step if resolved is not None else None
            if rs:
                artifact_ids = ArtifactRepository(store).output_artifact_ids_for_run_step(rs.run_step_id)
                if artifact_ids:
                    for aid in artifact_ids:
                        for kind in kinds:
                            evidence = reader.read_optional(aid, kind)
                            if evidence is not None:
                                result = _materialize_evidence(evidence)
                                if isinstance(result, dict):
                                    return cast("dict[str, Any]", result)
    return None


def _materialize_evidence(value: Any) -> Any:
    from dataclasses import fields, is_dataclass
    if is_dataclass(value):
        return {field.name: _materialize_evidence(getattr(value, field.name)) for field in fields(value) if not field.name.startswith("_")}
    if isinstance(value, dict):
        return {key: _materialize_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_materialize_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [_materialize_evidence(item) for item in value]
    return value


def get_step_maps(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    branches_repo = BranchRepository(store)
    step_map_b = branches_repo.get_step_map(branch_id_baseline, plan_version_id_baseline)
    step_map_c = branches_repo.get_step_map(branch_id_challenger, plan_version_id_challenger)
    return step_map_b, step_map_c
