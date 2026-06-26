"""EvidencePolicyService — unified staleness, reuse, and short-circuit decisions.

Consolidates logic from:
- cardre/staleness.py (compute_staleness, step_is_stale)
- cardre/services/branch_evidence.py (BranchEvidenceResolver)
- sidecar/routes/runs.py (_is_branch_current, _is_to_node_current)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.audit import ArtifactRef, RunStepRecord, StepSpec
from cardre.errors import Diagnostic
from cardre.evidence_locator import resolve_output_artifacts
from cardre.staleness import compute_staleness, step_is_stale
from cardre.store import ProjectStore
from cardre.topology import validate_topology


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
    step_outputs: dict[str, list[ArtifactRef]] = field(default_factory=dict)
    run_step_records: dict[str, RunStepRecord] = field(default_factory=dict)
    short_circuit_run_id: str | None = None
    source_by_step: dict[str, str | None] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class EvidencePolicyService:

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Short-circuit checks (used by RunService preflight)
    # ------------------------------------------------------------------

    def check_branch_current(self, plan_version_id: str, branch_id: str) -> ShortCircuitResult:
        """Check if a branch run would short-circuit (no stale steps, existing successful run)."""
        from cardre.errors import CardreError
        try:
            ctx = self.prepare_branch_evidence(plan_version_id, branch_id, force=False)
            if ctx.short_circuit_run_id is not None:
                return ShortCircuitResult(run_id=ctx.short_circuit_run_id, reason="branch_current")
        except CardreError:
            pass
        return ShortCircuitResult()

    def check_to_node_current(
        self, plan_version_id: str, target_step_id: str, branch_id: str | None = None,
    ) -> ShortCircuitResult:
        """Check if a to_node run would short-circuit (all closure steps non-stale)."""
        from cardre.step_graph import ancestor_closure
        try:
            steps = self._store.get_plan_version_steps(plan_version_id)
            step_by_id = {s.step_id: s for s in steps}
            if target_step_id not in step_by_id:
                return ShortCircuitResult()
            ancestors = ancestor_closure(target_step_id, steps)
            closure = ancestors | {target_step_id}
            closure_steps = [s for s in steps if s.step_id in closure]
            staleness = compute_staleness(self._store, plan_version_id, branch_id=branch_id)
            if all(not staleness.get(s.step_id, True) for s in closure_steps):
                existing_run_id = self._store.get_latest_successful_run_id(
                    plan_version_id, branch_id=branch_id,
                )
                if existing_run_id is not None:
                    return ShortCircuitResult(run_id=existing_run_id, reason="to_node_current")
        except Exception:
            pass
        return ShortCircuitResult()

    # ------------------------------------------------------------------
    # Branch evidence resolution
    # ------------------------------------------------------------------

    def prepare_branch_evidence(
        self, plan_version_id: str, branch_id: str, force: bool = False,
    ) -> BranchRunEvidence:
        from cardre.errors import BranchEvidenceError

        branch = self._store.get_branch(branch_id)
        if branch is None:
            raise BranchEvidenceError(
                "BRANCH_NOT_FOUND", message=f"Branch {branch_id} not found",
                context={"branch_id": branch_id}, status_code=404,
            )
        if branch.get("status") != "active":
            raise BranchEvidenceError(
                "BRANCH_INACTIVE", message=f"Branch {branch_id} is not active",
                context={"branch_id": branch_id, "status": branch.get("status")}, status_code=400,
            )
        if branch["head_plan_version_id"] != plan_version_id:
            raise BranchEvidenceError(
                "BRANCH_VERSION_MISMATCH",
                message=f"Branch head is {branch['head_plan_version_id']}, requested {plan_version_id}",
                context={"branch_id": branch_id, "head_pv_id": branch["head_plan_version_id"], "requested_pv_id": plan_version_id},
                status_code=409,
            )

        step_map = self._store.get_branch_step_map(branch_id, plan_version_id)
        branch_owned_step_ids = {r["step_id"] for r in step_map if r["is_branch_owned"]}
        shared_upstream_step_ids = {r["step_id"] for r in step_map if r["is_shared_upstream"]}

        steps = self._store.get_plan_version_steps(plan_version_id)
        validate_topology(steps)

        branch_staleness = compute_staleness(self._store, plan_version_id, branch_id=branch_id)

        source_by_step: dict[str, str | None] = {}
        for r in step_map:
            if r["is_shared_upstream"]:
                source_by_step[r["step_id"]] = r.get("source_branch_id") or None

        shared_evidence_map: dict[str, RunStepRecord] = {}
        lookup_diagnostics: list[Diagnostic] = []
        for sid in shared_upstream_step_ids:
            sb = source_by_step.get(sid)
            rs = self._find_shared_evidence(
                branch["plan_id"], plan_version_id, sid,
                source_branch_id=sb, diagnostics=lookup_diagnostics,
            )
            if rs is not None:
                shared_evidence_map[sid] = rs

        stale_shared: list[str] = []
        stale_cache: dict[str, bool] = {}
        spec_by_step = {s.step_id: s for s in steps}
        for sid in shared_upstream_step_ids:
            spec = spec_by_step.get(sid)
            if spec is None or step_is_stale(spec, steps, shared_evidence_map, stale_cache):
                stale_shared.append(sid)

        if stale_shared:
            raise BranchEvidenceError(
                "SHARED_UPSTREAM_STALE",
                message=f"Cannot run branch {branch_id} because shared upstream steps {stale_shared} are stale. Run the shared pathway first.",
                context={"branch_id": branch_id, "stale_shared_steps": stale_shared},
                status_code=409,
            )

        stale_branch_step_ids = list(branch_owned_step_ids) if force else [
            sid for sid in branch_owned_step_ids if branch_staleness.get(sid, True)
        ]

        if not stale_branch_step_ids:
            existing_run_id = self._store.get_latest_successful_run_id(
                plan_version_id, branch_id=branch_id,
            )
            if existing_run_id is not None:
                return BranchRunEvidence(
                    branch=branch, plan_version_id=plan_version_id, step_map=step_map,
                    steps=steps, branch_owned_step_ids=branch_owned_step_ids,
                    shared_upstream_step_ids=shared_upstream_step_ids,
                    source_by_step=source_by_step,
                    short_circuit_run_id=existing_run_id,
                )
            raise BranchEvidenceError(
                "BRANCH_NO_OP_FAILED",
                message=f"All branch-owned steps are current but no prior successful branch run exists for branch {branch_id}.",
                context={"branch_id": branch_id}, status_code=409,
            )

        step_outputs: dict[str, list[ArtifactRef]] = {}
        run_step_records: dict[str, RunStepRecord] = {}

        for sid, rs in shared_evidence_map.items():
            run_step_records[sid] = rs
            step_outputs[sid] = resolve_output_artifacts(self._store, rs)

        if not force:
            for spec in steps:
                if spec.step_id in branch_owned_step_ids and not branch_staleness.get(spec.step_id, True):
                    rs = self._store.get_latest_successful_run_step_for_step(
                        plan_version_id, spec.step_id, branch_id=branch_id,
                    )
                    if rs is not None:
                        run_step_records[spec.step_id] = rs
                        step_outputs[spec.step_id] = resolve_output_artifacts(self._store, rs)

        return BranchRunEvidence(
            branch=branch, plan_version_id=plan_version_id, step_map=step_map,
            steps=steps, branch_owned_step_ids=branch_owned_step_ids,
            shared_upstream_step_ids=shared_upstream_step_ids,
            source_by_step=source_by_step,
            stale_branch_step_ids=stale_branch_step_ids,
            step_outputs=step_outputs, run_step_records=run_step_records,
            diagnostics=lookup_diagnostics,
        )

    def resolve_parent_evidence(self, ctx: BranchRunEvidence, spec: StepSpec) -> None:
        for pid in spec.parent_step_ids:
            if pid in ctx.shared_upstream_step_ids and pid not in ctx.step_outputs:
                sb = ctx.source_by_step.get(pid)
                rs = self._find_shared_evidence(
                    ctx.branch["plan_id"], ctx.plan_version_id, pid,
                    source_branch_id=sb, diagnostics=ctx.diagnostics,
                )
                if rs is not None:
                    ctx.run_step_records[pid] = rs
                    ctx.step_outputs[pid] = resolve_output_artifacts(self._store, rs)

            if pid in ctx.branch_owned_step_ids and pid not in ctx.step_outputs:
                rs = self._store.get_latest_successful_run_step_for_step(
                    ctx.plan_version_id, pid, branch_id=ctx.branch["branch_id"],
                )
                if rs is not None:
                    ctx.run_step_records[pid] = rs
                    ctx.step_outputs[pid] = resolve_output_artifacts(self._store, rs)

    def _find_shared_evidence(
        self, plan_id: str, plan_version_id: str, step_id: str,
        source_branch_id: str | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> RunStepRecord | None:
        policies_tried: list[str] = []
        lookup_branch = source_branch_id or None
        policies_tried.append(f"branch_id={lookup_branch!r}")
        rs = self._store.get_latest_successful_run_step_for_step_across_plan(
            plan_id, step_id, branch_id=lookup_branch,
        )
        if rs is not None:
            return rs
        if lookup_branch is not None:
            policies_tried.append("branch_id=None")
            rs = self._store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=None,
            )
            if rs is not None:
                if diagnostics is not None:
                    diagnostics.append(Diagnostic(
                        code="INHERITED_BASELINE_EVIDENCE",
                        message=(
                            f"Step {step_id}: source branch {source_branch_id} "
                            "has no evidence; fell back to baseline (branch_id=None)."
                        ),
                        source="EvidencePolicyService._find_shared_evidence",
                        severity="warning",
                        context={"step_id": step_id, "plan_id": plan_id,
                                 "source_branch_id": source_branch_id, "fallback_branch_id": None},
                    ))
                return rs
        policies_tried.append("latest_plan_run")
        plan_run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
        if plan_run_id is not None:
            for prs in self._store.get_run_steps(plan_run_id):
                if prs.step_id == step_id and prs.status == "succeeded":
                    return prs
        if diagnostics is not None:
            diagnostics.append(Diagnostic(
                code="REUSE_EVIDENCE_NOT_FOUND",
                message=f"No shared evidence found for step {step_id} in plan {plan_id}",
                source="EvidencePolicyService._find_shared_evidence",
                severity="warning",
                context={"step_id": step_id, "plan_id": plan_id,
                         "plan_version_id": plan_version_id, "source_branch_id": source_branch_id,
                         "policies_tried": policies_tried},
            ))
        return None
