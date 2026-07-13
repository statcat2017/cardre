"""Model section collector — model info, limitations, and modelling metadata."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    Limitation,
    ModelFeature,
    ModelInfo,
)
from cardre.reporting.types import SectionCollector, SectionContext


class ModelSection(SectionCollector):
    canonical_step_id = "model-fit"
    kinds = (EvidenceKind.MODEL_ARTIFACT,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
                message=f"Model step {ref.step_id} has no successful run.",
            ))
            return

        model_art = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.MODEL_ARTIFACT)
        if model_art is not None:
            target_column = model_art.target_column
            if target_column and not ctx.bundle.summary.target_column:
                ctx.bundle.summary.target_column = target_column
            features = [
                ModelFeature(
                    variable_name=c.variable_name,
                    coefficient=c.coefficient,
                    standard_error=c.standard_error,
                    p_value=c.p_value,
                )
                for c in model_art.coefficients
            ]
            ctx.bundle.model = ModelInfo(
                model_type="logistic_regression_scorecard",
                branch_id=ref.resolved_branch_id,
                target=target_column or ctx.bundle.summary.target_column or "",
                features=features,
                intercept=model_art.intercept,
                fit_dataset_role="train",
                source_step_refs=[ref.to_schema_ref()],
            )
        else:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
                message=f"Model step {ref.step_id} produced no MODEL_ARTIFACT evidence.",
            ))


class ModelLimitationsSection(SectionCollector):
    canonical_step_id = "model-limitations"
    kinds = (EvidenceKind.EXPLAINABILITY_REPORT,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting.collector import _resolve_run_step
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return

        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.EXPLAINABILITY_REPORT)
        if evidence is None:
            return
        for limitation in evidence.limitations:
            if limitation.accepted:
                continue
            raw_severity = limitation.severity
            severity = "blocker" if raw_severity == "block" else "warning"
            ctx.add_limitation(Limitation(
                severity=severity,
                code=limitation.code or "MODEL_LIMITATION",
                message=limitation.message or "Model limitation evidence is present.",
            ))


class ModellingMetadataSection(SectionCollector):
    canonical_step_id = None
    kinds = (EvidenceKind.MODELLING_METADATA,)

    def build(self, ctx: SectionContext) -> None:
        from cardre.branch_step_resolver import resolve_step_for_branch
        from cardre.reporting.collector import _resolve_run_step

        step_map = ctx.store.get_branch_step_map(ctx.bundle.target_branch_id, ctx.plan_version_id)
        if not step_map:
            return
        ref = resolve_step_for_branch(
            branch_id=ctx.bundle.target_branch_id,
            canonical_step_id="define-metadata",
            branch_step_map=step_map,
        )
        if ref is None:
            return
        rs = _resolve_run_step(ctx.store, ref, ctx.plan_version_id)
        if rs is None:
            return

        meta = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.MODELLING_METADATA)
        if meta is None:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.MISSING_MODELLING_METADATA,
                message=f"Modelling metadata step {ref.step_id} produced no MODELLING_METADATA evidence.",
            ))
            return

        target_column = meta.target_column
        if target_column and not ctx.bundle.summary.target_column:
            ctx.bundle.summary.target_column = target_column
        ctx.bundle.modelling_metadata = meta.to_dict()
