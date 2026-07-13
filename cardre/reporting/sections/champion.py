"""Champion section collector — no ref, uses plan_id from ctx."""

from __future__ import annotations

from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import ChampionInfo, Limitation
from cardre.reporting.types import SectionCollector, SectionContext


class ChampionSection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        plan_id = ctx.store.get_plan_id_for_version(ctx.plan_version_id)
        if plan_id is None:
            ctx.bundle.champion = ChampionInfo(champion_status="not_available")
            return

        row = ctx.store.get_champion_assignment(plan_id)
        if row is None:
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.NO_CHAMPION_ASSIGNMENT,
                message="No champion branch has been assigned for this run.",
            ))
            ctx.bundle.champion = ChampionInfo(champion_status="not_available")
            return

        is_target = row["champion_branch_id"] == ctx.bundle.target_branch_id
        if not is_target and ctx.report_mode == "branch":
            ctx.add_limitation(Limitation(
                severity="warning", code=LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                message=f"Target branch {ctx.bundle.target_branch_id!r} is not the champion.",
            ))

        ctx.bundle.champion = ChampionInfo(
            champion_status="selected",
            assignment_id=row["champion_assignment_id"],
            champion_branch_id=row["champion_branch_id"],
            comparison_artifact_id=row["comparison_artifact_id"],
            rationale=row["assigned_reason"],
            selected_at=row["assigned_at"],
            target_branch_is_champion=is_target,
        )
