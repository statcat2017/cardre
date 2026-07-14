"""Sample definition section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.reporting.schema import SampleDefinitionInfo
from cardre.reporting.types import SectionCollector, SectionContext


class SampleDefinitionSection(SectionCollector):
    canonical_step_id = "sample-definition"
    kinds = (EvidenceKind.SAMPLE_DEFINITION,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting._resolve import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.SAMPLE_DEFINITION)
        if evidence is None:
            return
        ctx.bundle.sample_definition = SampleDefinitionInfo(
            sample_method=evidence.sample_method,
            sample_domain=evidence.sample_domain,
            sample_description=evidence.sample_description,
            source_step_refs=[ref.to_schema_ref()],
        )
