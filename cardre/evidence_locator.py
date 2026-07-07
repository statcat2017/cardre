"""Evidence Locator — the single lookup path for run-step evidence.

Implements ADR-0005 §3: the branch→full→plan fallback lives here and only
here.  Services call ``EvidenceLocator.resolve`` with a named policy; they
do not reimplement fallback logic.

The locator walks ``evidence_edges`` → ``run_steps`` (the v2 two-level
model), applies an optional fingerprint match against the current
``StepSpec``, and returns a ``ResolvedEvidence`` bundle (run-step + edges +
artifacts).  ``evidence_edges`` are queried once per step — the duplicate
query bug in the former ``evidence_resolver._resolve_branch_then_full_then_plan``
is eliminated by design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore
    from cardre.store.run_step_repo import RunStepRepository


class EvidenceLocator:
    """Resolve run-step evidence through the canonical fallback chain.

    Single lookup path mandated by ADR-0005 §3.  Owns:

    - The ``evidence_edges`` → ``run_steps`` walk (the v2 path).
    - The branch → full-plan → plan-level fallback.
    - The fingerprint comparison (``params_hash``, ``node_type``,
      ``node_version``) against an optional current ``StepSpec``.
    - The ``ResolvedEvidence`` assembly (edges + artifacts).
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve(
        self,
        plan_version_id: str,
        step_id: str,
        *,
        branch_id: str | None = None,
        plan_id: str | None = None,
        fingerprint_match: StepSpec | None = None,
    ) -> ResolvedEvidence | None:
        """Resolve evidence for a step, applying the canonical fallback.

        Fallback order:

        1. ``evidence_edges`` for (``plan_version_id``, ``step_id``) → the
           consuming step's run-step.  Branch scoping happens at the run
           level: a branch has its own run with its own run_steps, and
           ``evidence_edges`` point to those run_steps.  ``evidence_edges``
           has no ``branch_id`` column, so a single query suffices.
        2. If no edge exists, fall back to the latest plan-level run for
           this plan (``branch_id IS NULL``) and scan its run_steps.
        3. If ``plan_id`` is provided but no plan-level run exists for this
           ``plan_version_id``, look up the latest successful run for the
           plan and scan its run_steps.

        The optional ``fingerprint_match`` ``StepSpec`` filters candidates
        by ``params_hash``, ``node_type``, ``node_version``.  Non-matching
        candidates are skipped and the fallback continues.
        """
        from cardre.store.evidence_repo import EvidenceRepository
        from cardre.store.run_step_repo import RunStepRepository

        evidence_repo = EvidenceRepository(self._store)
        rs_repo = RunStepRepository(self._store)

        # Step 1: edge-walking.  Query edges ONCE — the evidence_edges
        # table has no branch_id column, so the "branch then full-plan"
        # fallback is a single query.
        edges = evidence_repo.get_edges_for_plan_step(plan_version_id, step_id)
        rs: RunStep | None = None
        if edges:
            rs = rs_repo.get(edges[-1].run_step_id)

        if rs is not None and self._matches_fingerprint(rs, fingerprint_match):
            return self._build_resolved_evidence(rs)

        # Step 2: plan-level run fallback.  Find the latest successful run
        # for this plan_version (branch_id=None) and scan its run_steps.
        plan_level_rs = self._find_run_step_from_plan_version(
            rs_repo, plan_version_id, step_id,
        )
        if plan_level_rs is not None and self._matches_fingerprint(
            plan_level_rs, fingerprint_match,
        ):
            return self._build_resolved_evidence(plan_level_rs)

        # Step 3: across-plan fallback.  If plan_id is provided (or can be
        # resolved from the plan_version), find the latest successful run
        # for the entire plan and scan its run_steps.
        resolved_plan_id = plan_id
        if resolved_plan_id is None:
            resolved_plan_id = self._plan_id_for_version(plan_version_id)

        if resolved_plan_id is not None:
            across_plan_rs = self._find_run_step_for_plan(
                rs_repo, resolved_plan_id, step_id,
            )
            if across_plan_rs is not None and self._matches_fingerprint(
                across_plan_rs, fingerprint_match,
            ):
                return self._build_resolved_evidence(across_plan_rs)

        return None

    def resolve_for_run(
        self,
        run_id: str,
        step_id: str,
    ) -> ResolvedEvidence | None:
        """Resolve evidence scoped to a single run (the ``run_only`` policy).

        No fallback.  Returns ``None`` if no successful run-step for
        ``step_id`` exists in ``run_id``.
        """
        from cardre.store.run_step_repo import RunStepRepository

        rs_repo = RunStepRepository(self._store)
        for rs in rs_repo.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                return self._build_resolved_evidence(rs)
        return None

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

    def _find_run_step_from_plan_version(
        self,
        rs_repo: RunStepRepository,
        plan_version_id: str,
        step_id: str,
    ) -> RunStep | None:
        """Find the latest successful run-step for ``step_id`` in any
        plan-level run (``branch_id IS NULL``) of ``plan_version_id``.
        """
        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(self._store)
        run_id = run_repo.get_latest_successful_id(plan_version_id, branch_id=None)
        if run_id is None:
            return None
        for rs in rs_repo.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                return rs
        return None

    def _find_run_step_for_plan(
        self,
        rs_repo: RunStepRepository,
        plan_id: str,
        step_id: str,
    ) -> RunStep | None:
        """Find the latest successful run-step for ``step_id`` in any
        successful run of any plan_version belonging to ``plan_id``.
        """
        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(self._store)
        run_id = run_repo.get_latest_successful_id_for_plan(plan_id)
        if run_id is None:
            return None
        for rs in rs_repo.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                return rs
        return None

    def _plan_id_for_version(self, plan_version_id: str) -> str | None:
        """Resolve the ``plan_id`` for a ``plan_version_id``."""
        from cardre.store.plan_repo import PlanRepository
        pv = PlanRepository(self._store).get_version(plan_version_id)
        if pv is None:
            return None
        return cast(str | None, pv.get("plan_id"))

    @staticmethod
    def _matches_fingerprint(
        rs: RunStep | None, spec: StepSpec | None,
    ) -> bool:
        """Compare a run-step's fingerprint to the current StepSpec.

        Returns ``True`` if ``spec`` is ``None`` (no filtering requested)
        or if ``params_hash``, ``node_type``, and ``node_version`` all
        match the run-step's ``execution_fingerprint``.
        """
        if spec is None or rs is None:
            return True
        fp = rs.execution_fingerprint
        if fp.get("params_hash", "") != spec.params_hash:
            return False
        if fp.get("node_type", "") != spec.node_type:
            return False
        return cast(bool, fp.get("node_version", "") == spec.node_version)


__all__ = ["EvidenceLocator"]
