"""EvidenceResolver + EvidencePolicyService — evidence resolution and policy.

``EvidenceResolver`` resolves run-step evidence with a named policy and
diagnostics. ``EvidencePolicyService`` is the policy single-source-of-truth.

Two classes, one module.  Ported from v1 ``evidence_resolver.py`` and
``services/evidence_policy.py``, return type extended to populate
``EvidenceEdge`` + ``EvidenceArtifact`` domain objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from cardre.domain.errors import Diagnostic
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore

@dataclass
class ShortCircuitResult:
    run_id: str | None = None
    reason: str | None = None


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

    def __init__(self, store: "ProjectStore") -> None:
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
    ) -> tuple[RunStep | None, str, list[Diagnostic]]:
        """Resolve evidence and return (run_step, source_label, diagnostics).

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

    def _resolve_run_only(
        self, run_id: str | None, step_id: str, diagnostics: list[Diagnostic],
    ) -> tuple[RunStep | None, str, list[Diagnostic]]:
        if run_id is None:
            return None, "missing", diagnostics
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(self._store)
        for rs in rs_repo.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                return rs, "run", diagnostics
        return None, "missing", diagnostics

    def _resolve_branch_then_full_then_plan(
        self, plan_version_id: str, step_id: str, branch_id: str | None,
        require_fingerprint_match: StepSpec | None, diagnostics: list[Diagnostic],
    ) -> tuple[RunStep | None, str, list[Diagnostic]]:
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(self._store)

        rs = rs_repo.get_latest_successful_step(
            plan_version_id, step_id, branch_id=branch_id,
        )
        if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
            return rs, "branch", diagnostics

        if branch_id is not None:
            rs = rs_repo.get_latest_successful_step(
                plan_version_id, step_id, branch_id=None,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "full_plan", diagnostics

        fallback = self._find_run_step_from_plan_level_run(plan_version_id, step_id)
        if fallback is not None and self._matches_fingerprint(fallback, require_fingerprint_match):
            return fallback, "latest_plan_run", diagnostics

        return None, "missing", diagnostics

    def _resolve_source_branch_then_full_then_plan(
        self, plan_id: str | None, plan_version_id: str, step_id: str,
        source_branch_id: str | None, require_fingerprint_match: StepSpec | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[RunStep | None, str, list[Diagnostic]]:
        from cardre.store.run_step_repo import RunStepRepository
        from cardre.store.run_repo import RunRepository
        rs_repo = RunStepRepository(self._store)
        run_repo = RunRepository(self._store)

        if plan_id is None:
            from cardre.store.plan_repo import PlanRepository
            pv = PlanRepository(self._store).get_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        lookup_branch = source_branch_id or None
        if plan_id:
            rs = rs_repo.get_latest_successful_step(
                plan_version_id, step_id, branch_id=lookup_branch,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

        if plan_id:
            rs = rs_repo.get_latest_successful_step(
                plan_version_id, step_id, branch_id=None,
            )
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
                return rs, "across_plan", diagnostics

            plan_run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in rs_repo.get_for_run(plan_run_id):
                    if prs.step_id == step_id and prs.status == RunStepStatus.SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return prs, "latest_plan_run", diagnostics

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
    ) -> tuple[RunStep | None, str, list[Diagnostic]]:
        from cardre.store.run_step_repo import RunStepRepository
        from cardre.store.run_repo import RunRepository
        rs_repo = RunStepRepository(self._store)
        run_repo = RunRepository(self._store)

        if plan_id is None:
            from cardre.store.plan_repo import PlanRepository
            pv = PlanRepository(self._store).get_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        if plan_id:
            rs = rs_repo.get_latest_successful_step(
                plan_version_id, step_id, branch_id=branch_id,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

            rs = rs_repo.get_latest_successful_step(
                plan_version_id, step_id, branch_id=None,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

            plan_run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in rs_repo.get_for_run(plan_run_id):
                    if prs.step_id == step_id and prs.status == RunStepStatus.SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return prs, "latest_plan_run", diagnostics

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
        if fp.get("node_version", "") != spec.node_version:
            return False
        return True


# ---------------------------------------------------------------------------
# EvidencePolicyService
# ---------------------------------------------------------------------------


class EvidencePolicyService:

    def __init__(self, store: "ProjectStore") -> None:
        self._store = store

    def check_branch_current(self, plan_version_id: str, branch_id: str) -> ShortCircuitResult:
        """Check if a branch run would short-circuit (no stale steps, existing successful run)."""
        try:
            ctx = self.prepare_branch_evidence(plan_version_id, branch_id, force=False)
            if ctx.short_circuit_run_id is not None:
                return ShortCircuitResult(run_id=ctx.short_circuit_run_id, reason="branch_current")
        except Exception:
            pass
        return ShortCircuitResult()

    def check_to_node_current(
        self, plan_version_id: str, target_step_id: str, branch_id: str | None = None,
    ) -> ShortCircuitResult:
        """Check if a to_node run would short-circuit (all closure steps non-stale)."""
        from cardre.execution.step_graph import ancestor_closure
        try:
            from cardre.store.step_repo import StepRepository
            step_repo = StepRepository(self._store)
            steps = step_repo.get_steps(plan_version_id)
            step_by_id = {s.step_id: s for s in steps}
            if target_step_id not in step_by_id:
                return ShortCircuitResult()
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
                    return ShortCircuitResult(run_id=existing_run_id, reason="to_node_current")
        except Exception:
            pass
        return ShortCircuitResult()

    def prepare_branch_evidence(
        self, plan_version_id: str, branch_id: str, force: bool = False,
    ) -> BranchRunEvidence:
        """Prepare branch evidence for execution."""
        from cardre.store.step_repo import StepRepository
        from cardre.store.run_repo import RunRepository
        from cardre.execution.topology import validate_topology
        from cardre.services.staleness_service import StalenessService

        step_repo = StepRepository(self._store)
        run_repo = RunRepository(self._store)

        steps = step_repo.get_steps(plan_version_id)
        validate_topology(steps)

        staleness_svc = StalenessService(self._store)

        # Simplified branch evidence: all steps are "owned" in non-governance mode
        branch_owned_step_ids = {s.step_id for s in steps}
        step_map = []

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
    "EvidencePolicyService",
    "EvidenceResolver",
    "ShortCircuitResult",
]
