"""Step resolution service — canonical step ID resolution with alias fallback.

Consolidates the branch-step-map resolution and legacy alias handling that
was scattered across readiness, collector, comparison, and manual-binning.
"""

from __future__ import annotations

from typing import Any, Literal

from cardre.reporting.evidence_contract import canonical_alias_candidates
from cardre.services.step_topology import (
    find_nearest_ancestor_by_canonical_step_id,
    find_nearest_binning_source,
)
from cardre.step_id import ResolvedStepRef, resolve_required_steps, resolve_step_for_branch
from cardre.store import ProjectStore


class StepResolutionService:
    """Resolve canonical step IDs to branch-scoped step IDs.

    ``exact`` and ``ancestor`` modes delegate to ``resolve_step_for_branch``
    / ``resolve_required_steps`` after loading the branch step map.
    ``nearest_upstream`` delegates to topology helpers for manual-binning.
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve_canonical(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_id: str,
        mode: Literal["exact", "ancestor", "nearest_upstream"] = "ancestor",
        from_step_id: str | None = None,
    ) -> ResolvedStepRef | None:
        step_map = self._store.get_branch_step_map(branch_id, plan_version_id)
        if not step_map:
            return None

        if mode == "nearest_upstream":
            return self._resolve_nearest_upstream(
                branch_id, plan_version_id, canonical_step_id, step_map, from_step_id,
            )

        allow_ancestor = mode == "ancestor"
        ref = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=canonical_step_id,
            branch_step_map=step_map,
            allow_ancestor=allow_ancestor,
        )
        if ref is not None:
            return ref

        for candidate in canonical_alias_candidates(canonical_step_id):
            if candidate == canonical_step_id:
                continue
            ref = resolve_step_for_branch(
                branch_id=branch_id,
                canonical_step_id=candidate,
                branch_step_map=step_map,
                allow_ancestor=allow_ancestor,
            )
            if ref is not None:
                return ref

        return None

    def resolve_required(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_ids: list[str],
        mode: Literal["exact", "ancestor", "nearest_upstream"] = "ancestor",
    ) -> dict[str, ResolvedStepRef | None]:
        step_map = self._store.get_branch_step_map(branch_id, plan_version_id)
        if not step_map:
            return {cid: None for cid in canonical_step_ids}

        if mode == "nearest_upstream":
            result: dict[str, ResolvedStepRef | None] = {}
            for cid in canonical_step_ids:
                result[cid] = self._resolve_nearest_upstream(
                    branch_id, plan_version_id, cid, step_map, from_step_id=None,
                )
            return result

        allow_ancestor = mode == "ancestor"
        result = resolve_required_steps(
            branch_id=branch_id,
            canonical_step_ids=canonical_step_ids,
            branch_step_map=step_map,
            allow_ancestor=allow_ancestor,
        )

        for cid in canonical_step_ids:
            if result.get(cid) is not None:
                continue
            for candidate in canonical_alias_candidates(cid):
                if candidate == cid:
                    continue
                candidate_ref = resolve_step_for_branch(
                    branch_id=branch_id,
                    canonical_step_id=candidate,
                    branch_step_map=step_map,
                    allow_ancestor=allow_ancestor,
                )
                if candidate_ref is not None:
                    result[cid] = candidate_ref
                    break

        return result

    def _resolve_nearest_upstream(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_id: str,
        step_map: list[dict[str, Any]],
        from_step_id: str | None,
    ) -> ResolvedStepRef | None:
        steps = self._store.get_plan_version_steps(plan_version_id)
        actual_step_id = from_step_id or canonical_step_id

        if canonical_step_id == "binning":
            spec = find_nearest_binning_source(steps, actual_step_id, step_map)
        else:
            spec = find_nearest_ancestor_by_canonical_step_id(
                steps, actual_step_id, step_map, canonical_step_id,
            )

        if spec is None:
            return None

        return resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=spec.canonical_step_id,
            branch_step_map=step_map,
            allow_ancestor=True,
        )
