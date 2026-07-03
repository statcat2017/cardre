"""StalenessService — compute staleness from evidence_edges + evidence_artifacts.

Port from v1 ``staleness.py`` but reads from ``evidence_edges`` +
``evidence_artifacts``, not ``run_steps.execution_fingerprint_json``.

This is the real behaviour change: staleness uses the Phase 1 two-level
tables, not reconstructed JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cardre.domain.errors import GraphValidationError
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore
    from cardre.store.evidence_repo import EvidenceRepository
    from cardre.store.run_repo import RunRepository
    from cardre.store.run_step_repo import RunStepRepository


@dataclass
class StalenessExplanation:
    """Result of explaining staleness for a step."""
    step_id: str
    status: str  # "fresh", "stale", "missing"
    upstream_changes: dict[str, bool]  # step_id -> is_stale for all upstream steps
    missing_evidence: list[str]  # parent_step_ids with no evidence


class StalenessService:
    """Compute staleness explanations from the two-level evidence tables."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def explain_step(
        self,
        plan_version_id: str,
        step_id: str,
        *,
        branch_id: str | None = None,
        plan_id: str | None = None,
    ) -> StalenessExplanation:
        """Explain staleness for a single step.

        Returns ``StalenessExplanation`` with:
        - ``status``: "fresh", "stale", or "missing"
        - ``upstream_changes``: ``{step_id: is_stale}`` for all upstream steps
        - ``missing_evidence``: list of parent_step_ids with no evidence

        Reads from ``evidence_edges`` + ``evidence_artifacts`` and compares
        ``params_hash``, ``node_type``, ``node_version``.
        """
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository
        from cardre.store.step_repo import StepRepository

        step_repo = StepRepository(self._store)
        evidence_repo = EvidenceRepository(self._store)
        run_repo = RunRepository(self._store)
        rs_repo = RunStepRepository(self._store)

        steps = step_repo.get_steps(plan_version_id)
        spec_by_id = {s.step_id: s for s in steps}

        if plan_id is None:
            from cardre.store.plan_repo import PlanRepository
            pv = PlanRepository(self._store).get_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        # Find latest run for this plan_version + branch
        run_id = run_repo.get_latest_successful_id(plan_version_id, branch_id=branch_id)
        if run_id is None and branch_id is not None:
            run_id = run_repo.get_latest_successful_id(plan_version_id, branch_id=None)
        if run_id is None and plan_id is not None:
            run_id = run_repo.get_latest_successful_id_for_plan(plan_id)

        # Build step_id -> evidence mapping
        step_has_evidence: dict[str, bool] = {}
        missing_evidence: list[str] = []

        # Check if the step itself has any successful run step
        if run_id is not None:
            for rs in rs_repo.get_for_run(run_id):
                if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                    step_has_evidence[step_id] = True
                    break
            else:
                step_has_evidence[step_id] = False
        else:
            step_has_evidence[step_id] = False

        # Build upstream staleness recursively
        stale_cache: dict[str, bool] = {}
        upstream_changes: dict[str, bool] = {}

        # Check all upstream steps recursively
        for s in steps:
            is_stale = self._step_is_stale(
                s, steps, rs_repo, evidence_repo, run_repo,
                plan_version_id, branch_id, plan_id, stale_cache,
            )
            upstream_changes[s.step_id] = is_stale

        # Check parent evidence
        spec = spec_by_id.get(step_id)
        if spec:
            for pid in spec.parent_step_ids:
                parent_edges = evidence_repo.get_edges_for_plan_step(plan_version_id, pid)
                if not parent_edges:
                    missing_evidence.append(pid)

        # Determine status
        if (spec and run_id is None) or step_has_evidence.get(step_id) is False:
            status = "missing"
        elif upstream_changes.get(step_id, True):
            status = "stale"
        else:
            status = "fresh"

        return StalenessExplanation(
            step_id=step_id,
            status=status,
            upstream_changes=upstream_changes,
            missing_evidence=missing_evidence,
        )

    def _step_is_stale(
        self,
        spec: StepSpec,
        all_steps: list[StepSpec],
        rs_repo: RunStepRepository,
        evidence_repo: EvidenceRepository,
        run_repo: RunRepository,
        plan_version_id: str,
        branch_id: str | None,
        plan_id: str | None,
        stale_cache: dict[str, bool],
    ) -> bool:
        """Check if a step is stale by comparing evidence tables to current spec.

        Discovers the source run-step via ``evidence_edges``, then reads
        ``params_hash``, ``node_type``, ``node_version`` from the linked
        run-step's execution fingerprint.  This honours the v2 contract:
        staleness flows from the two-level evidence tables, not from
        ``run_steps.execution_fingerprint_json`` directly.
        """
        if spec.step_id in stale_cache:
            return stale_cache[spec.step_id]

        # Discover source run-step via evidence_edges
        edges = evidence_repo.get_edges_for_plan_step(plan_version_id, spec.step_id)
        rs: RunStep | None = None
        if edges:
            # Use the most recent edge's source run-step
            source_run_step_id = edges[-1].source_run_step_id
            rs = rs_repo.get(source_run_step_id)

        if rs is None and branch_id is not None:
            edges = evidence_repo.get_edges_for_plan_step(plan_version_id, spec.step_id)
            if edges:
                source_run_step_id = edges[-1].source_run_step_id
                rs = rs_repo.get(source_run_step_id)

        if rs is None and plan_id is not None:
            plan_run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in rs_repo.get_for_run(plan_run_id):
                    if prs.step_id == spec.step_id and prs.status == RunStepStatus.SUCCEEDED:
                        rs = prs
                        break

        if rs is None:
            stale_cache[spec.step_id] = True
            return True

        fp = rs.execution_fingerprint

        # Compare params_hash
        if fp.get("params_hash", "") != spec.params_hash:
            stale_cache[spec.step_id] = True
            return True

        # Compare node_type and node_version
        if fp.get("node_type", "") != spec.node_type:
            stale_cache[spec.step_id] = True
            return True
        if fp.get("node_version", "") != spec.node_version:
            stale_cache[spec.step_id] = True
            return True

        # Check parent staleness recursively
        for pid in spec.parent_step_ids:
            parent_spec = _find_spec(pid, all_steps)
            parent_stale = self._step_is_stale(
                parent_spec, all_steps, rs_repo, evidence_repo, run_repo,
                plan_version_id, branch_id, plan_id, stale_cache,
            )
            if parent_stale:
                stale_cache[spec.step_id] = True
                return True

            # Check parent output hashes via evidence edges
            parent_edges = evidence_repo.get_edges_for_plan_step(plan_version_id, pid)
            parent_rs: RunStep | None = None
            if parent_edges:
                parent_rs = rs_repo.get(parent_edges[-1].source_run_step_id)

            if parent_rs is not None:
                stored_parent_outputs = fp.get("parent_output_logical_hashes_by_step", {}).get(pid, [])
                current_parent_outputs = parent_rs.execution_fingerprint.get(
                    "output_artifact_logical_hashes", []
                )
                if stored_parent_outputs != current_parent_outputs:
                    stale_cache[spec.step_id] = True
                    return True
            else:
                stale_cache[spec.step_id] = True
                return True

        stale_cache[spec.step_id] = False
        return False


def _find_spec(step_id: str, steps: list[StepSpec]) -> StepSpec:
    for s in steps:
        if s.step_id == step_id:
            return s
    raise GraphValidationError(
        f"Missing parent step {step_id!r} referenced by staleness walk",
        context={"missing_step_id": step_id, "known_step_ids": [s.step_id for s in steps]},
    )


__all__ = ["StalenessExplanation", "StalenessService"]
