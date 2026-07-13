"""Reproducibility section collector — needs manifest_digest from ctx."""

from __future__ import annotations

from cardre.reporting.schema import (
    ExecutionFingerprint,
    ReportGenerationInfo,
    ReproducibilityInfo,
)
from cardre.reporting.types import SectionCollector, SectionContext


class ReproducibilitySection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        run_steps = ctx.store.get_run_steps(ctx.run["run_id"])
        fingerprints = []
        for rs in run_steps:
            fp = rs.execution_fingerprint
            fingerprints.append(ExecutionFingerprint(
                step_id=rs.step_id,
                canonical_step_id=fp.get("canonical_step_id", rs.step_id),
                python_version=fp.get("python_version", ""),
                platform=fp.get("platform", ""),
                package_fingerprint={},
            ))

        ctx.bundle.reproducibility = ReproducibilityInfo(
            run_id=ctx.run["run_id"],
            manifest_hash=ctx.manifest_digest.manifest_hash or "",
            pathway_hash=ctx.manifest_digest.pathway_hash or "",
            execution_fingerprints=fingerprints,
            report_generation=ReportGenerationInfo(
                generated_at=ctx.bundle.generated_at,
                cardre_version="0.1.0",
            ),
        )
