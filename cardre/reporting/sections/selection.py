"""Variable selection section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.reporting.schema import VariableSelectionInfo
from cardre.reporting.types import SectionCollector, SectionContext


class VariableSelectionSection(SectionCollector):
    canonical_step_id = "variable-selection"
    kinds = (EvidenceKind.SELECTION_DEFINITION,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting._resolve import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.SELECTION_DEFINITION)
        if evidence is None:
            return
        ctx.bundle.variable_selection = VariableSelectionInfo(
            selected_variables=[item.variable for item in evidence.selected],
            rejected_variables=[str(item.get("variable", "")) for item in evidence.rejected if item.get("variable")],
            min_iv=evidence.min_iv,
            source_step_refs=[ref.to_schema_ref()],
        )
