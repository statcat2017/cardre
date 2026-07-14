"""Redundancy review section collector — does its own resolve internally."""

from __future__ import annotations

from cardre._evidence.kinds import EvidenceKind
from cardre.branch_step_resolver import resolve_required_steps
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    Limitation,
    RedundancyCluster,
    RedundancyClusterMember,
    RedundancyReviewInfo,
)
from cardre.reporting.types import SectionCollector, SectionContext
from cardre.store.branch_repo import BranchRepository


class RedundancyReviewSection(SectionCollector):
    canonical_step_id = None
    kinds = (EvidenceKind.VARIABLE_CLUSTERING,)

    def build(self, ctx: SectionContext) -> None:
        from cardre.reporting._resolve import resolve_run_step

        step_map = BranchRepository(ctx.store).get_step_map(ctx.bundle.target_branch_id, ctx.plan_version_id)
        if not step_map:
            return

        ref = None
        for _cid, r in resolve_required_steps(
            branch_id=ctx.bundle.target_branch_id,
            canonical_step_ids=["variable-clustering"],
            branch_step_map=step_map,
        ).items():
            ref = r
            break

        if ref is None:
            return

        rs = resolve_run_step(ctx, ref)
        if rs is None:
            ctx.add_limitation(Limitation(
                severity="warning",
                code=LimitationCode.MISSING_VARIABLE_CLUSTERING_EVIDENCE,
                message=f"Variable clustering step {ref.step_id} has no successful run.",
            ))
            return

        evidence = ctx.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VARIABLE_CLUSTERING)
        if evidence is None:
            ctx.add_limitation(Limitation(
                severity="warning",
                code=LimitationCode.MISSING_VARIABLE_CLUSTERING_EVIDENCE,
                message=f"Variable clustering step {ref.step_id} has no cardre.variable_clustering_evidence.v1 artifact.",
            ))
            return

        clusters = []
        for cl in evidence.clusters:
            members = [
                RedundancyClusterMember(
                    variable=m.variable,
                    iv=m.iv,
                    missing_rate=m.missing_rate,
                )
                for m in cl.variables
            ]
            clusters.append(RedundancyCluster(
                cluster_id=cl.cluster_id,
                variables=members,
                representative_suggestion=cl.representative_suggestion,
                representative_reason=cl.representative_reason,
                max_pairwise_abs_corr=cl.max_pairwise_abs_corr,
                notes=list(cl.notes),
            ))

        ctx.bundle.redundancy_review = RedundancyReviewInfo(
            method=evidence.method,
            input_representation=evidence.input_representation,
            similarity_metric=evidence.similarity_metric,
            threshold=evidence.threshold,
            absolute_correlation=evidence.absolute_correlation,
            missing_handling=evidence.missing_handling,
            candidate_limit=evidence.candidate_limit,
            representative_rule=evidence.representative_rule,
            minimum_pair_count=evidence.minimum_pair_count,
            cluster_count=len(evidence.clusters),
            singleton_count=len(evidence.singleton_variables),
            clusters=clusters,
            singleton_variables=list(evidence.singleton_variables),
            warnings=[dict(w) for w in evidence.warnings],
        )
