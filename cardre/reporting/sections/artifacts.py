"""Artifacts section collector — no ref, returns list."""

from __future__ import annotations

from cardre.reporting.schema import ArtifactEntry
from cardre.reporting.types import SectionCollector, SectionContext
from cardre.store.artifact_repo import ArtifactRepository


class ArtifactsSection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        entries: list[ArtifactEntry] = []
        seen: set[str] = set()
        for aid in ArtifactRepository(ctx.store).output_artifact_ids_for_run(ctx.run["run_id"]):
            if aid in seen:
                continue
            seen.add(aid)
            art = ArtifactRepository(ctx.store).get(aid)
            if art:
                entries.append(ArtifactEntry(
                    artifact_id=art.artifact_id,
                    artifact_type=art.artifact_type,
                    role=art.role,
                    logical_hash=art.logical_hash,
                    physical_hash=art.physical_hash,
                    path=art.path,
                ))
        ctx.bundle.artifacts = entries
