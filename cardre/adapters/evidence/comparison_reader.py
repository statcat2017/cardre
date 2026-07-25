"""ComparisonEvidenceReader — adapter implementing ``ComparisonEvidencePort``.

Resolves canonical step IDs through the branch step map, locates the latest
successful run-step evidence, matches artifacts to the requested evidence
profile (role/type/media/schema), and returns the validated JSON mapping
that ``RefreshComparison`` consumes.

This adapter lives in ``cardre.adapters`` so that the API layer never
imports adapters directly; it is wired in the composition root
(``cardre.bootstrap.container``) and injected into ``RefreshComparison``.
"""

from __future__ import annotations

import json
from typing import Any

from cardre._evidence.kinds import EvidenceKind, EvidenceParseError
from cardre.adapters.evidence.parsers import get_adapter, match
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import UnitOfWorkFactory


class ComparisonEvidenceReader:
    """Filesystem-backed implementation of ``ComparisonEvidencePort``.

    Bound to a single project at construction so that ``find_typed`` can
    resolve artifacts through the project root while looking up run-step
    evidence by ``plan_version_id``.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        artifact_reader: ArtifactReader,
        project_id: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader = artifact_reader
        self._project_id = project_id

    def find_typed(
        self,
        step_map: list[dict[str, Any]],
        canonical_step_id: str,
        plan_version_id: str,
        evidence_branch_id: str | None,
        kinds: tuple[EvidenceKind, ...],
    ) -> dict[str, Any] | None:
        with self._uow_factory.read_only(self._project_id) as uow:
            for row in step_map:
                if row.get("canonical_step_id") != canonical_step_id:
                    continue
                step_id = row.get("source_step_id") or row.get("step_id", "")
                rs = uow.run_steps.get_latest_successful_step(
                    plan_version_id, step_id, evidence_branch_id,
                )
                if rs is None:
                    continue
                artifact_ids = uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id)
                artifacts = [a for a in (uow.artifacts.get(aid) for aid in artifact_ids) if a is not None]
                if not artifacts:
                    continue
                for kind in kinds:
                    spec = get_adapter(kind)
                    matched = match(artifacts, spec.profile, self._artifact_reader)
                    if not matched:
                        continue
                    for art in matched:
                        path = self._artifact_reader.resolve_path(art)
                        if not path.exists():
                            continue
                        try:
                            return json.loads(path.read_text(encoding="utf-8"))
                        except json.JSONDecodeError as exc:
                            raise EvidenceParseError(
                                f"Artifact {art.artifact_id} matched profile "
                                f"{kind.value} but contained malformed JSON: {exc}"
                            ) from exc
        return None
