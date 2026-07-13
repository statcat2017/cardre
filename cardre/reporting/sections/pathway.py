"""Pathway and branches section collector — inlined in collect()."""

from __future__ import annotations

from cardre.reporting.schema import (
    BranchInfo,
    BranchSummary,
    PathwayStep,
    PathwaySummary,
)
from cardre.reporting.types import SectionCollector, SectionContext
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository


class PathwaySection(SectionCollector):
    canonical_step_id = None
    kinds = ()

    def build(self, ctx: SectionContext) -> None:
        plan_steps = PlanRepository(ctx.store).get_version_steps(ctx.plan_version_id)
        pathway_steps: list[PathwayStep] = []
        for ps in plan_steps:
            resolution = "exact"
            step_branch_id = ps.branch_id or ""
            for _cid, ref in ctx.resolved.items():
                if ref and ref.canonical_step_id == ps.canonical_step_id:
                    resolution = ref.resolution
                    step_branch_id = ref.resolved_branch_id
                    break
            pathway_steps.append(PathwayStep(
                canonical_step_id=ps.canonical_step_id,
                step_id=ps.step_id,
                branch_id=step_branch_id,
                step_type=ps.node_type,
                status="",
                config_hash=ps.params_hash,
                resolution=resolution,
            ))
        ctx.bundle.pathway = PathwaySummary(pathway_id="scorecard_pathway", steps=pathway_steps)

        plan_id = PlanRepository(ctx.store).get_plan_id_for_version(ctx.plan_version_id)
        all_branches = BranchRepository(ctx.store).list(ctx.bundle.project_id, plan_id=plan_id)
        branch_infos: list[BranchInfo] = []
        for b in all_branches:
            branch_infos.append(BranchInfo(
                branch_id=b["branch_id"],
                name=b.get("name", ""),
                parent_branch_id=b.get("base_branch_id"),
                created_from_canonical_step_id=b.get("branch_point_canonical_step_id"),
                is_target_branch=b["branch_id"] == ctx.bundle.target_branch_id,
                is_champion=False,
                status=b.get("status", ""),
            ))
        ctx.bundle.branches = BranchSummary(
            branching_model="plan_derived_lanes",
            target_branch_id=ctx.bundle.target_branch_id,
            branches=branch_infos,
        )

        # Update is_champion in branch list
        if ctx.bundle.champion.champion_branch_id:
            for bi in ctx.bundle.branches.branches:
                if bi.branch_id == ctx.bundle.champion.champion_branch_id:
                    bi.is_champion = True
