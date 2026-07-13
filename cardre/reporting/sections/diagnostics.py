"""Diagnostics section collector — coefficient sign, separation, VIF, calibration."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.reporting.schema import (
    CalibrationBin,
    CalibrationRole,
    CoefficientSignEntry,
    SeparationEntry,
    VifEntry,
)
from cardre.reporting.types import SectionCollector, SectionContext


class CoefficientSignSection(SectionCollector):
    canonical_step_id = "coefficient-sign-check"
    kinds = (EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS)
        if evidence is None:
            return
        entries = [
            CoefficientSignEntry(
                variable_name=v.variable_name,
                feature_name=v.feature_name,
                coefficient=v.coefficient,
                coefficient_is_infinite=v.coefficient_is_infinite,
                coefficient_sign=v.coefficient_sign,
                expected_sign=v.expected_sign,
                status=v.status,
                reason=v.reason,
            )
            for v in evidence.variables
        ]
        ctx.bundle.model_diagnostics.coefficient_sign_check = entries
        ctx.bundle.model_diagnostics.source_step_refs.append(ref.to_schema_ref())


class SeparationSection(SectionCollector):
    canonical_step_id = "separation-diagnostics"
    kinds = (EvidenceKind.SEPARATION_DIAGNOSTICS,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.SEPARATION_DIAGNOSTICS)
        if evidence is None:
            return
        entries = [
            SeparationEntry(
                feature_name=v.feature_name,
                coefficient=v.coefficient,
                coefficient_is_infinite=v.coefficient_is_infinite,
                abs_coefficient=v.abs_coefficient,
                standard_error=v.standard_error,
                standard_error_is_infinite=v.standard_error_is_infinite,
                status=v.status,
                reason=v.reason,
            )
            for v in evidence.variables
        ]
        ctx.bundle.model_diagnostics.separation_diagnostics = entries
        ctx.bundle.model_diagnostics.source_step_refs.append(ref.to_schema_ref())


class VifSection(SectionCollector):
    canonical_step_id = "vif-diagnostics"
    kinds = (EvidenceKind.VIF_DIAGNOSTICS,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VIF_DIAGNOSTICS)
        if evidence is None:
            return
        entries = [
            VifEntry(
                feature_name=v.feature_name,
                vif=v.vif,
                vif_is_infinite=v.vif_is_infinite,
                r_squared=v.r_squared,
                status=v.status,
                reason=v.reason,
            )
            for v in evidence.variables
        ]
        ctx.bundle.model_diagnostics.vif_diagnostics = entries
        ctx.bundle.model_diagnostics.source_step_refs.append(ref.to_schema_ref())


class CalibrationSection(SectionCollector):
    canonical_step_id = "calibration-diagnostics"
    kinds = (EvidenceKind.CALIBRATION_DIAGNOSTICS,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return
        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.CALIBRATION_DIAGNOSTICS)
        if evidence is None:
            return
        role_entries: dict[str, CalibrationRole] = {}
        for role_data in evidence.roles:
            decile_bins = [
                CalibrationBin(
                    bin=b.bin,
                    count=b.count,
                    observed_events=b.observed_events,
                    expected_events=b.expected_events,
                    observed_event_rate=b.observed_event_rate,
                    predicted_event_rate=b.predicted_event_rate,
                    abs_deviation=b.abs_deviation,
                )
                for b in role_data.decile_bins
            ]
            role_entries[role_data.role] = CalibrationRole(
                row_count=role_data.row_count,
                known_count=role_data.known_count,
                n_bins=role_data.n_bins,
                hosmer_lemeshow_statistic=role_data.hosmer_lemeshow_statistic,
                hosmer_lemeshow_p_value=role_data.hosmer_lemeshow_p_value,
                calibration_error=role_data.calibration_error,
                auc=role_data.auc,
                decile_bins=decile_bins,
                status=role_data.status,
            )
        ctx.bundle.model_diagnostics.calibration_diagnostics = role_entries
        ctx.bundle.model_diagnostics.source_step_refs.append(ref.to_schema_ref())
