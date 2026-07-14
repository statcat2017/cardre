"""Score scaling section collector."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import Limitation, ScoreScalingInfo
from cardre.reporting.types import SectionCollector, SectionContext


class ScoreScalingSection(SectionCollector):
    canonical_step_id = "score-scaling"
    kinds = (EvidenceKind.SCORE_SCALING,)

    def build(self, ctx: SectionContext) -> None:
        ref = ctx.resolved.get(self.canonical_step_id)
        if ref is None:
            return
        from cardre.reporting._resolve import resolve_run_step
        rs = resolve_run_step(ctx, ref)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
                message=f"Score scaling step {ref.step_id} has no successful run.",
            ))
            return

        scaling = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.SCORE_SCALING)
        if scaling is not None:
            ctx.bundle.score_scaling = ScoreScalingInfo(
                base_score=scaling.base_score,
                base_odds=scaling.base_odds_text,
                pdo=scaling.pdo,
                factor=scaling.factor,
                offset=scaling.offset,
                score_direction=scaling.score_direction,
                rounding=scaling.rounding,
                min_score=scaling.min_score,
                max_score=scaling.max_score,
                source_step_refs=[ref.to_schema_ref()],
            )
        else:
            ctx.add_limitation(Limitation(
                severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
                message=f"Score scaling step {ref.step_id} produced no SCORE_SCALING evidence.",
            ))
