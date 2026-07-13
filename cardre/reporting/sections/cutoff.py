"""Cutoff analysis section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    CutoffInfo,
    CutoffRow,
    CutoffTable,
    Limitation,
)
from cardre.reporting.types import SectionCollector, SectionContext


class CutoffSection(SectionCollector):
    canonical_step_id = "cutoff-analysis"
    kinds = (EvidenceKind.CUTOFF_ANALYSIS,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
                message=f"Cutoff analysis step {ref.step_id} has no successful run.",
            ))
            return

        cutoff = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.CUTOFF_ANALYSIS)
        if cutoff is not None:
            tables = []
            for role_name, rows in cutoff.cutoff_tables.items():
                cutoff_rows = [
                    CutoffRow(
                        score_cutoff=r.score_cutoff,
                        approval_rate=r.approval_rate,
                        bad_rate=r.bad_rate,
                        capture_rate=r.capture_rate,
                    )
                    for r in rows
                ]
                tables.append(CutoffTable(role=role_name, rows=cutoff_rows))
            if tables:
                ctx.bundle.cutoffs = CutoffInfo(cutoff_tables=tables, source_step_refs=[ref.to_schema_ref()])
        else:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
                message=f"Cutoff analysis step {ref.step_id} produced no CUTOFF_ANALYSIS evidence.",
            ))
