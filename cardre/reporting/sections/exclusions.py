"""Exclusion summary section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.reporting.schema import ExclusionRuleInfo, ExclusionSummaryInfo
from cardre.reporting.types import SectionCollector, SectionContext


class ExclusionSummarySection(SectionCollector):
    canonical_step_id = "apply-exclusions"
    kinds = (EvidenceKind.EXCLUSION_SUMMARY,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.EXCLUSION_SUMMARY)
        if evidence is None:
            return
        rules = [
            ExclusionRuleInfo(rule_id=str(i), reason=r.get("reason", ""), rows_removed=r.get("rows_removed", 0))
            for i, r in enumerate(evidence.rules)
        ]
        ctx.bundle.exclusion_summary = ExclusionSummaryInfo(
            rows_before=evidence.rows_before,
            rows_after=evidence.rows_after,
            rules=rules,
            source_step_refs=[ref.to_schema_ref()],
        )
