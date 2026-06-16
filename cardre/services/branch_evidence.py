"""BranchEvidenceResolver — evidence resolution for branch runs.

Extracts inline evidence-seeding logic from PlanExecutor.run_branch()
into a dedicated resolver so the executor can focus on step iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from cardre.audit import ArtifactRef, RunStepRecord, StepSpec
from cardre.store import ProjectStore

if TYPE_CHECKING:
    from cardre.executor import PlanExecutor

STATUS_SUCCEEDED = "succeeded"


@dataclass
class BranchRunContext:
    """Resolved evidence for running a branch.

    Fields with defaults are populated incrementally by the resolver
    and updated by the executor during execution.
    """

    branch: dict[str, Any]
    plan_version_id: str
    step_map: list[dict[str, Any]]
    steps: list[StepSpec]
    branch_owned_step_ids: set[str] = field(default_factory=set)
    shared_upstream_step_ids: set[str] = field(default_factory=set)
    stale_branch_step_ids: list[str] = field(default_factory=list)
    step_outputs: dict[str, list[ArtifactRef]] = field(default_factory=dict)
    run_step_records: dict[str, RunStepRecord] = field(default_factory=dict)
    short_circuit_run_id: str | None = None
    source_by_step: dict[str, str | None] = field(default_factory=dict)


class BranchEvidenceResolver:
    """Resolve all evidence needed to execute a branch version.

    Encapsulates branch validation, staleness computation, shared
    upstream staleness checks, evidence seeding for both shared
    upstream and branch-owned steps, per-step parent evidence
    resolution, and short-circuit logic.
    """

    def __init__(self, executor: PlanExecutor) -> None:
        self._exec = executor

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def prepare_branch_run(
        self,
        store: ProjectStore,
        branch_id: str,
        plan_version_id: str,
    ) -> BranchRunContext:
        """Validate branch state, compute staleness, and seed initial evidence.

        Returns a ``BranchRunContext``.  When all branch-owned steps are
        already current and a prior successful branch run exists the
        returned context has ``short_circuit_run_id`` set; the caller
        should return that run-id immediately.
        """

        # 1. Branch validation
        branch = store.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Branch {branch_id} not found")
        if branch.get("status") != "active":
            raise ValueError(f"Branch {branch_id} is not active")

        if branch["head_plan_version_id"] != plan_version_id:
            raise ValueError(
                f"BRANCH_VERSION_MISMATCH: Branch head is {branch['head_plan_version_id']}, "
                f"requested {plan_version_id}"
            )

        # 2. Step map and classification
        step_map = store.get_branch_step_map(branch_id, plan_version_id)
        branch_owned_step_ids = {
            r["step_id"] for r in step_map if r["is_branch_owned"]
        }
        shared_upstream_step_ids = {
            r["step_id"] for r in step_map if r["is_shared_upstream"]
        }

        # 3. Steps and topology
        steps = store.get_plan_version_steps(plan_version_id)
        self._exec._validate_topology(steps)

        # 4. Branch-owned staleness
        branch_staleness = self._exec.compute_staleness(
            store, plan_version_id, branch_id=branch_id,
        )

        # 5. Shared upstream staleness — check for evidence across all
        #    plan versions under the source branch (not just the child's
        #    plan version, which won't have the parent branch's runs).
        source_by_step: dict[str, str | None] = {}
        for r in step_map:
            if r["is_shared_upstream"]:
                source_by_step[r["step_id"]] = r.get("source_branch_id") or None

        stale_shared: list[str] = []
        for sid in shared_upstream_step_ids:
            sb = source_by_step.get(sid)
            rs = self._find_shared_evidence(
                store, branch["plan_id"], plan_version_id, sid,
                source_branch_id=sb,
            )
            if rs is None:
                stale_shared.append(sid)

        if stale_shared:
            raise ValueError(
                f"SHARED_UPSTREAM_STALE: Cannot run branch {branch_id} because "
                f"shared upstream steps {stale_shared} are stale. "
                "Run the shared pathway first."
            )

        # 6. Identify stale branch-owned steps
        stale_branch_step_ids = [
            sid for sid in branch_owned_step_ids
            if branch_staleness.get(sid, True)
        ]

        # 7. Short-circuit when nothing to run
        if not stale_branch_step_ids:
            existing_run_id = store.get_latest_successful_run_id(
                plan_version_id, branch_id=branch_id,
            )
            if existing_run_id is not None:
                return BranchRunContext(
                    branch=branch,
                    plan_version_id=plan_version_id,
                    step_map=step_map,
                    steps=steps,
                    branch_owned_step_ids=branch_owned_step_ids,
                    shared_upstream_step_ids=shared_upstream_step_ids,
                    source_by_step=source_by_step,
                    short_circuit_run_id=existing_run_id,
                )
            raise ValueError(
                f"BRANCH_NO_OP_FAILED: All branch-owned steps are current "
                f"but no prior successful branch run exists for branch {branch_id}."
            )

        # 8. Seed step_outputs and run_step_records from latest evidence

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}

        # 8a. Shared upstream evidence (use source branch for child-of-child)
        for sid in shared_upstream_step_ids:
            sb = source_by_step.get(sid)
            rs = self._find_shared_evidence(
                store, branch["plan_id"], plan_version_id, sid,
                source_branch_id=sb,
            )
            if rs is not None:
                run_step_records[sid] = rs
                step_outputs[sid] = self._exec._resolve_output_artifacts(store, rs)

        # 8b. Current (non-stale) branch-owned step evidence
        for spec in steps:
            if spec.step_id in branch_owned_step_ids and not branch_staleness.get(spec.step_id, True):
                rs = store.get_latest_successful_run_step_for_step(
                    plan_version_id, spec.step_id, branch_id=branch_id,
                )
                if rs is not None:
                    run_step_records[spec.step_id] = rs
                    step_outputs[spec.step_id] = self._exec._resolve_output_artifacts(store, rs)

        return BranchRunContext(
            branch=branch,
            plan_version_id=plan_version_id,
            step_map=step_map,
            steps=steps,
            branch_owned_step_ids=branch_owned_step_ids,
            shared_upstream_step_ids=shared_upstream_step_ids,
            source_by_step=source_by_step,
            stale_branch_step_ids=stale_branch_step_ids,
            step_outputs=step_outputs,
            run_step_records=run_step_records,
        )

    def resolve_parent_evidence(
        self,
        store: ProjectStore,
        ctx: BranchRunContext,
        spec: StepSpec,
    ) -> None:
        """Seed any missing parent evidence for *spec* before execution.

        Mutates ``ctx.step_outputs`` and ``ctx.run_step_records``.
        """
        for pid in spec.parent_step_ids:
            if pid in ctx.shared_upstream_step_ids and pid not in ctx.step_outputs:
                sb = ctx.source_by_step.get(pid)
                rs = self._find_shared_evidence(
                    store, ctx.branch["plan_id"], ctx.plan_version_id, pid,
                    source_branch_id=sb,
                )
                if rs is not None:
                    ctx.run_step_records[pid] = rs
                    ctx.step_outputs[pid] = self._exec._resolve_output_artifacts(store, rs)

            if pid in ctx.branch_owned_step_ids and pid not in ctx.step_outputs:
                rs = store.get_latest_successful_run_step_for_step(
                    ctx.plan_version_id, pid, branch_id=ctx.branch["branch_id"],
                )
                if rs is not None:
                    ctx.run_step_records[pid] = rs
                    ctx.step_outputs[pid] = self._exec._resolve_output_artifacts(store, rs)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _find_shared_evidence(
        self,
        store: ProjectStore,
        plan_id: str,
        plan_version_id: str,
        step_id: str,
        source_branch_id: str | None = None,
    ) -> RunStepRecord | None:
        """Look up successful evidence for a shared upstream step.

        Searches across all plan versions so inherited parent-branch
        evidence (produced under the parent's plan version) is found.
        """
        lookup_branch = source_branch_id or None
        rs = store.get_latest_successful_run_step_for_step_across_plan(
            plan_id, step_id, branch_id=lookup_branch,
        )
        if rs is not None:
            return rs
        if lookup_branch is not None:
            rs = store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=None,
            )
            if rs is not None:
                return rs
        plan_run_id = store.get_latest_successful_run_id_for_plan(plan_id)
        if plan_run_id is not None:
            for prs in store.get_run_steps(plan_run_id):
                if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                    return prs
        return None
