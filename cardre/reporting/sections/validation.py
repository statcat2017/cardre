"""Validation section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    Limitation,
    MetricsByRole,
    PsiEntry,
    ValidationInfo,
)
from cardre.reporting.types import SectionCollector, SectionContext


class ValidationSection(SectionCollector):
    canonical_step_id = "validation-metrics"
    kinds = (EvidenceKind.VALIDATION_EVIDENCE, EvidenceKind.VALIDATION_METRICS)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                message=f"Validation step {ref.step_id} has no successful run.",
            ))
            return

        val = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VALIDATION_EVIDENCE)
        if val is None:
            val = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VALIDATION_METRICS)
        if val is None:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                message=f"Validation step {ref.step_id} produced no VALIDATION_EVIDENCE or VALIDATION_METRICS evidence.",
            ))
            return

        validation = ValidationInfo(source_step_refs=[ref.to_schema_ref()])
        for role_name, rm in val.metrics_by_role.items():
            validation.metrics_by_role.append(MetricsByRole(
                role=role_name,
                row_count=rm.row_count,
                auc=rm.auc,
                gini=rm.gini,
                ks=rm.ks,
                bad_rate=rm.bad_rate,
            ))
        for comp, psi_val in val.psi.items():
            validation.stability.psi_by_role.append(PsiEntry(
                comparison=comp,
                score_psi=psi_val,
            ))
        ctx.bundle.validation = validation
