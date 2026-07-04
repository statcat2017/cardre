"""EvidenceResolver + EvidencePolicyService — evidence resolution and policy.

``EvidenceResolver`` resolves run-step evidence with a named policy and
diagnostics. ``EvidencePolicyService`` is the policy single-source-of-truth.

Two classes, one module.  Ported from v1 ``evidence_resolver.py`` and
``services/evidence_policy.py``, return type extended to populate
``EvidenceEdge`` + ``EvidenceArtifact`` domain objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from cardre.domain.errors import Diagnostic
from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore

@dataclass
class ShortCircuitResult:
    run_id: str | None = None
    reason: str | None = None


@dataclass
class EvidenceCheckResult:
    """Typed result for evidence policy checks (#215).

    ``status`` is one of:
    - ``current``: evidence is fresh; short-circuit is possible;
    - ``stale``: evidence exists but is stale; execution is needed;
    - ``missing``: no prior evidence; execution is needed;
    - ``error``: an infrastructure error occurred; do not silently retry.
    """
    status: Literal["current", "stale", "missing", "error"]
    run_id: str | None = None
    diagnostics: list[Any] = field(default_factory=list)


@dataclass
class BranchRunEvidence:
    branch: dict[str, Any]
    plan_version_id: str
    step_map: list[dict[str, Any]]
    steps: list[StepSpec]
    branch_owned_step_ids: set[str] = field(default_factory=set)
    shared_upstream_step_ids: set[str] = field(default_factory=set)
    stale_branch_step_ids: list[str] = field(default_factory=list)
    step_outputs: dict[str, list[Any]] = field(default_factory=dict)
    run_step_records: dict[str, RunStep] = field(default_factory=dict)
    short_circuit_run_id: str | None = None
    source_by_step: dict[str, str | None] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)


STATUS_SUCCEEDED = "succeeded"


class EvidenceResolver:
    """Resolve run-step evidence with a named policy and diagnostics."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve(
        self,
        plan_version_id: str,
        step_id: str,
        *,
        branch_id: str | None = None,
        source_branch_id: str | None = None,
        run_id: str | None = None,
        plan_id: str | None = None,
        require_fingerprint_match: StepSpec | None = None,
        policy: Literal[
            "run_only",
            "branch_then_full_then_plan",
            "source_branch_then_full_then_plan",
            "across_plan",
        ] = "branch_then_full_then_plan",
    ) -> tuple[ResolvedEvidence | None, str, list[Diagnostic]]:
        """Resolve evidence and return (resolved_evidence, source_label, diagnostics).

        Source labels: ``run``, ``branch``, ``full_plan``, ``across_plan``,
        ``latest_plan_run``, ``missing``.
        """
        diagnostics: list[Diagnostic] = []

        if policy == "run_only":
            return self._resolve_run_only(run_id, step_id, diagnostics)

        if policy == "branch_then_full_then_plan":
            return self._resolve_branch_then_full_then_plan(
                plan_version_id, step_id, branch_id, require_fingerprint_match, diagnostics,
            )

        if policy == "source_branch_then_full_then_plan":
            return self._resolve_source_branch_then_full_then_plan(
                plan_id, plan_version_id, step_id, source_branch_id, require_fingerprint_match, diagnostics,
            )

        if policy == "across_plan":
            return self._resolve_across_plan(
                plan_id, plan_version_id, step_id, branch_id, require_fingerprint_match, diagnostics,
            )

        return None, "missing", diagnostics

    def _build_resolved_evidence(self, rs: RunStep) -> ResolvedEvidence:
        """Fetch evidence edges/artifacts for a RunStep and bundle as ResolvedEvidence."""
        from cardre.store.evidence_repo import EvidenceRepository
        evidence_repo = EvidenceRepository(self._store)
        edges = evidence_repo.get_edges_for_run_step(rs.run_step_id)
        artifacts = evidence_repo.get_artifacts_for_run_step(rs.run_step_id)
        return ResolvedEvidence(
            run_step_id=rs.run_step_id,
            run_step=rs,
            edges=edges,
            artifacts=artifacts,
        )

    def _resolve_run_only(
        self, run_id: str | None, step_id: str, diagnostics: list[Diagnostic],
    ) -> tuple[ResolvedEvidence | None, str, list[Diagnostic]]:
        if run_id is None:
            return None, "missing", diagnostics
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(self._store)
        for rs in rs_repo.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                return self._build_resolved_evidence(rs), "run", diagnostics
        return None, "missing", diagnostics

    def _resolve_branch_then_full_then_plan(
        self, plan_version_id: str, step_id: str, branch_id: str | None,
        require_fingerprint_match: StepSpec | None, diagnostics: list[Diagnostic],
    ) -> tuple[ResolvedEvidence | None, str, list[Diagnostic]]:
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_step_repo import RunStepRepository
        evidence_repo = EvidenceRepository(self._store)
        rs_repo = RunStepRepository(self._store)

        # Discover the candidate run-step via evidence_edges.
        # The edge for "step_b consumed from step_a" has:
        #   run_step_id = rs_b (the consuming step's run-step)
        #   source_run_step_id = rs_a (the parent/source run-step)
        # We want the consuming step's run-step, so we read run_step_id.
        edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
        rs: RunStep | None = None
        if edges:
            rs = rs_repo.get(edges[-1].run_step_id)

        if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
            return self._build_resolved_evidence(rs), "branch", diagnostics

        if branch_id is not None:
            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
            rs = rs_repo.get(edges[-1].run_step_id) if edges else None
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return self._build_resolved_evidence(rs), "full_plan", diagnostics

        fallback = self._find_run_step_from_plan_level_run(plan_version_id, step_id)
        if fallback is not None and self._matches_fingerprint(fallback, require_fingerprint_match):
            return self._build_resolved_evidence(fallback), "latest_plan_run", diagnostics

        return None, "missing", diagnostics

    def _resolve_source_branch_then_full_then_plan(
        self, plan_id: str | None, plan_version_id: str, step_id: str,
        source_branch_id: str | None, require_fingerprint_match: StepSpec | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[ResolvedEvidence | None, str, list[Diagnostic]]:
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        evidence_repo = EvidenceRepository(self._store)
        rs_repo = RunStepRepository(self._store)
        run_repo = RunRepository(self._store)

        if plan_id is None:
            from cardre.store.plan_repo import PlanRepository
            pv = PlanRepository(self._store).get_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        lookup_branch = source_branch_id or None
        if plan_id:
            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
            rs: RunStep | None = None
            if edges:
                rs = rs_repo.get(edges[-1].run_step_id)
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return self._build_resolved_evidence(rs), "across_plan", diagnostics

        if plan_id:
            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
            rs = rs_repo.get(edges[-1].run_step_id) if edges else None
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                if lookup_branch is not None:
                    diagnostics.append(Diagnostic(
                        code="INHERITED_BASELINE_EVIDENCE",
                        message=(
                            f"Step {step_id}: source branch {source_branch_id} "
                            "has no evidence; fell back to baseline (branch_id=None)."
                        ),
                        source="EvidenceResolver._resolve_source_branch_then_full_then_plan",
                        severity="warning",
                        context={
                            "step_id": step_id,
                            "plan_id": plan_id,
                            "source_branch_id": source_branch_id,
                            "fallback_branch_id": None,
                        },
                    ))
                return self._build_resolved_evidence(rs), "across_plan", diagnostics

            plan_run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in rs_repo.get_for_run(plan_run_id):
                    if prs.step_id == step_id and prs.status == RunStepStatus.SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return self._build_resolved_evidence(prs), "latest_plan_run", diagnostics

        diagnostics.append(Diagnostic(
            code="REUSE_EVIDENCE_NOT_FOUND",
            message=f"No shared evidence found for step {step_id} in plan {plan_id}",
            source="EvidenceResolver._resolve_source_branch_then_full_then_plan",
            severity="warning",
            context={
                "step_id": step_id,
                "plan_version_id": plan_version_id,
                "source_branch_id": source_branch_id,
            },
        ))
        return None, "missing", diagnostics

    def _resolve_across_plan(
        self, plan_id: str | None, plan_version_id: str, step_id: str,
        branch_id: str | None, require_fingerprint_match: StepSpec | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[ResolvedEvidence | None, str, list[Diagnostic]]:
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        evidence_repo = EvidenceRepository(self._store)
        rs_repo = RunStepRepository(self._store)
        run_repo = RunRepository(self._store)

        if plan_id is None:
            from cardre.store.plan_repo import PlanRepository
            pv = PlanRepository(self._store).get_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        if plan_id:
            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
            rs: RunStep | None = None
            if edges:
                rs = rs_repo.get(edges[-1].run_step_id)
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return self._build_resolved_evidence(rs), "across_plan", diagnostics

            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
            rs = rs_repo.get(edges[-1].run_step_id) if edges else None
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return self._build_resolved_evidence(rs), "across_plan", diagnostics

            plan_run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in rs_repo.get_for_run(plan_run_id):
                    if prs.step_id == step_id and prs.status == RunStepStatus.SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return self._build_resolved_evidence(prs), "latest_plan_run", diagnostics

        return None, "missing", diagnostics

    def _find_run_step_from_plan_level_run(
        self, plan_version_id: str, step_id: str,
    ) -> RunStep | None:
        from cardre.store.plan_repo import PlanRepository
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        plan_repo = PlanRepository(self._store)
        run_repo = RunRepository(self._store)
        rs_repo = RunStepRepository(self._store)

        pv = plan_repo.get_version(plan_version_id)
        if pv is None:
            return None
        plan_run_id = run_repo.get_latest_successful_id_for_plan(pv["plan_id"])
        if plan_run_id is None:
            return None
        for prs in rs_repo.get_for_run(plan_run_id):
            if prs.step_id == step_id and prs.status == RunStepStatus.SUCCEEDED:
                return prs
        return None

    @staticmethod
    def _matches_fingerprint(
        rs: RunStep | None, spec: StepSpec | None,
    ) -> bool:
        if spec is None or rs is None:
            return True
        fp = rs.execution_fingerprint
        if fp.get("params_hash", "") != spec.params_hash:
            return False
        if fp.get("node_type", "") != spec.node_type:
            return False
        return cast(bool, fp.get("node_version", "") == spec.node_version)


# ---------------------------------------------------------------------------
# EvidencePolicyService
# ---------------------------------------------------------------------------


class EvidencePolicyService:

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def check_branch_current(self, plan_version_id: str, branch_id: str) -> EvidenceCheckResult:
        """Check if a branch run would short-circuit (no stale steps, existing successful run).

        Returns a typed EvidenceCheckResult (#215):
        - ``current`` if an existing run can be reused;
        - ``missing`` if no prior evidence exists;
        - ``error`` if an infrastructure error occurs.
        """
        try:
            ctx = self.prepare_branch_evidence(plan_version_id, branch_id, force=False)
            if ctx.short_circuit_run_id is not None:
                return EvidenceCheckResult(
                    status="current",
                    run_id=ctx.short_circuit_run_id,
                    diagnostics=[{"code": "BRANCH_CURRENT", "message": "Branch evidence is current."}],
                )
            return EvidenceCheckResult(status="missing")
        except (KeyError, ValueError, TypeError) as exc:
            return EvidenceCheckResult(
                status="error",
                diagnostics=[{
                    "code": "EVIDENCE_CHECK_ERROR",
                    "message": f"Evidence check failed: {exc}",
                    "severity": "error",
                }],
            )

    def check_to_node_current(
        self, plan_version_id: str, target_step_id: str, branch_id: str | None = None,
    ) -> EvidenceCheckResult:
        """Check if a to_node run would short-circuit (all closure steps non-stale).

        Returns a typed EvidenceCheckResult (#215).
        """
        from cardre.execution.step_graph import ancestor_closure
        try:
            from cardre.store.step_repo import StepRepository
            step_repo = StepRepository(self._store)
            steps = step_repo.get_steps(plan_version_id)
            step_by_id = {s.step_id: s for s in steps}
            if target_step_id not in step_by_id:
                return EvidenceCheckResult(status="missing")
            ancestors = ancestor_closure(target_step_id, steps)
            closure = ancestors | {target_step_id}
            closure_steps = [s for s in steps if s.step_id in closure]

            from cardre.services.staleness_service import StalenessService
            staleness_svc = StalenessService(self._store)
            explanation = staleness_svc.explain_step(plan_version_id, target_step_id)

            if all(
                not explanation.upstream_changes.get(s.step_id, True)
                for s in closure_steps
            ):
                from cardre.store.run_repo import RunRepository
                run_repo = RunRepository(self._store)
                existing_run_id = run_repo.get_latest_successful_id(
                    plan_version_id, branch_id=branch_id,
                )
                if existing_run_id is not None:
                    return EvidenceCheckResult(
                        status="current",
                        run_id=existing_run_id,
                        diagnostics=[{"code": "TO_NODE_CURRENT", "message": "To-node evidence is current."}],
                    )
            return EvidenceCheckResult(status="missing")
        except (KeyError, ValueError, TypeError) as exc:
            return EvidenceCheckResult(
                status="error",
                diagnostics=[{
                    "code": "EVIDENCE_CHECK_ERROR",
                    "message": f"Evidence check failed: {exc}",
                    "severity": "error",
                }],
            )

    def prepare_branch_evidence(
        self, plan_version_id: str, branch_id: str, force: bool = False,
    ) -> BranchRunEvidence:
        """Prepare branch evidence for execution."""
        from cardre.execution.topology import validate_topology
        from cardre.services.staleness_service import StalenessService
        from cardre.store.run_repo import RunRepository
        from cardre.store.step_repo import StepRepository

        step_repo = StepRepository(self._store)
        run_repo = RunRepository(self._store)

        steps = step_repo.get_steps(plan_version_id)
        validate_topology(steps)

        staleness_svc = StalenessService(self._store)

        # Simplified branch evidence: all steps are "owned" in non-governance mode
        branch_owned_step_ids = {s.step_id for s in steps}
        step_map: list[dict[str, Any]] = []

        explanation = staleness_svc.explain_step(plan_version_id, list(steps)[0].step_id if steps else "")

        stale_branch_step_ids = list(branch_owned_step_ids) if force else [
            sid for sid in branch_owned_step_ids
            if explanation.upstream_changes.get(sid, True)
        ]

        if not stale_branch_step_ids:
            existing_run_id = run_repo.get_latest_successful_id(
                plan_version_id, branch_id=branch_id,
            )
            if existing_run_id is not None:
                return BranchRunEvidence(
                    branch={}, plan_version_id=plan_version_id,
                    step_map=step_map, steps=steps,
                    branch_owned_step_ids=branch_owned_step_ids,
                    short_circuit_run_id=existing_run_id,
                )

        step_outputs: dict[str, list[Any]] = {}
        run_step_records: dict[str, RunStep] = {}

        return BranchRunEvidence(
            branch={}, plan_version_id=plan_version_id,
            step_map=step_map, steps=steps,
            branch_owned_step_ids=branch_owned_step_ids,
            stale_branch_step_ids=stale_branch_step_ids,
            step_outputs=step_outputs,
            run_step_records=run_step_records,
        )

    def resolve_parent_evidence(self, ctx: BranchRunEvidence, spec: StepSpec) -> None:
        """Resolve parent evidence for a step within branch context."""
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(self._store)

        for pid in spec.parent_step_ids:
            if pid not in ctx.step_outputs:
                rs = rs_repo.get_latest_successful_step(
                    ctx.plan_version_id, pid, branch_id=None,
                )
                if rs is not None:
                    ctx.run_step_records[pid] = rs


__all__ = [
    "BranchRunEvidence",
    "EvidenceCheckResult",
    "EvidencePolicyService",
    "EvidenceResolver",
    "ShortCircuitResult",
]
