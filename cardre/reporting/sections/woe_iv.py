"""WOE/IV section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    AffectedBinDetail,
    Limitation,
    VariableBin,
    VariableInfo,
    WoeSmoothingInfo,
)
from cardre.reporting.types import SectionCollector, SectionContext


class WoeIvSection(SectionCollector):
    canonical_step_id = "final-woe-iv"
    kinds = (EvidenceKind.WOE_IV_EVIDENCE,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting._resolve import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_WOE_IV_EVIDENCE,
                message=f"WOE/IV step {ref.step_id} has no successful run.",
            ))
            return

        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.WOE_IV_EVIDENCE)
        if evidence is None:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.WOE_SUMMARY_USED_INSTEAD_OF_EVIDENCE,
                message=f"WOE/IV step {ref.step_id} has no cardre.woe_iv_evidence.v1 artifact.",
            ))
            return

        smoothing = evidence.smoothing
        zero_cell_policy = smoothing.zero_cell_policy

        for var in evidence.variables:
            woe_smoothing = WoeSmoothingInfo(
                enabled=smoothing.enabled,
                method=smoothing.method,
                alpha=smoothing.alpha,
                zero_cell_policy=zero_cell_policy,
                smoothing_applied=var.smoothing_applied,
                zero_cell_encountered=var.zero_cell_encountered,
                affected_bin_count=len(var.affected_bins),
            )

            if woe_smoothing.smoothing_applied:
                ctx.add_limitation(Limitation(
                    severity="warning", code=LimitationCode.SMOOTHING_APPLIED,
                    message=f"WOE smoothing applied to variable {var.variable_name}.",
                ))

            affected_bins = [
                AffectedBinDetail(**ab.detail)
                for ab in var.affected_bins
            ]

            var_bins = [
                VariableBin(
                    bin_id=b.bin_id,
                    label=b.label,
                    lower=b.lower,
                    upper=b.upper,
                    good_count=b.good_count,
                    bad_count=b.bad_count,
                    bad_rate=b.bad_rate,
                    woe=b.woe,
                    iv_contribution=b.iv_contribution,
                )
                for b in var.bins
            ]

            ctx.bundle.variables.append(VariableInfo(
                variable_name=var.variable_name,
                role=var.status,
                branch_id=ref.resolved_branch_id,
                final_bin_count=len(var_bins),
                iv=var.iv,
                woe_smoothing=woe_smoothing,
                source_step_refs=[ref.to_schema_ref()],
                bins=var_bins,
                affected_bins=affected_bins,
            ))

        if zero_cell_policy == "block":
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.ZERO_CELL_POLICY_USED,
                message=f"Zero-cell policy '{zero_cell_policy}' is configured.",
            ))


class InitialWoeIvSection(SectionCollector):
    canonical_step_id = "initial-woe-iv"
    kinds = (EvidenceKind.WOE_IV_EVIDENCE,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting._resolve import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.WOE_IV_EVIDENCE)
        if evidence is None:
            return
        for var in evidence.variables:
            ctx.bundle.variables.append(VariableInfo(
                variable_name=var.variable_name,
                role="initial",
                iv=var.iv,
                source_step_refs=[ref.to_schema_ref()],
            ))
