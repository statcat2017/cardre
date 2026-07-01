"""Canonical step ID resolution — maps canonical_step_id to branch-scoped step_id.

Pure functions + one store-dependent resolver.  The pure resolvers operate on
the branch_step_map dict; the store-dependent resolve_run_step() handles
cross-version fallback logic for evidence retrieval.

Phase 5 rule: the report collector must not infer step IDs.
It must resolve evidence using target_branch_id + canonical_step_id
through the branch_step_map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.audit import RunStepRecord
from cardre.store import ProjectStore
from cardre.store.run_repo import RunRepository


@dataclass
class ResolvedStepRef:
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str  # "exact" or "ancestor"
    artifact_ids: list[str] = field(default_factory=list)


def resolve_step_for_branch(
    *,
    branch_id: str,
    canonical_step_id: str,
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> ResolvedStepRef | None:
    for row in branch_step_map:
        if row["canonical_step_id"] != canonical_step_id:
            continue

        is_shared = bool(row.get("is_shared_upstream", False))
        is_owned = bool(row.get("is_branch_owned", True))
        source_branch_id = row.get("source_branch_id")

        if is_owned and not is_shared:
            return ResolvedStepRef(
                requested_branch_id=branch_id,
                resolved_branch_id=branch_id,
                canonical_step_id=canonical_step_id,
                step_id=row["step_id"],
                resolution="exact",
            )

        if is_shared and source_branch_id:
            if allow_ancestor:
                return ResolvedStepRef(
                    requested_branch_id=branch_id,
                    resolved_branch_id=source_branch_id,
                    canonical_step_id=canonical_step_id,
                    step_id=row["step_id"],
                    resolution="ancestor",
                )
            return None

        return ResolvedStepRef(
            requested_branch_id=branch_id,
            resolved_branch_id=branch_id,
            canonical_step_id=canonical_step_id,
            step_id=row["step_id"],
            resolution="exact",
        )

    return None


def resolve_required_steps(
    *,
    branch_id: str,
    canonical_step_ids: list[str],
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> dict[str, ResolvedStepRef]:
    """Resolve multiple canonical steps, returning a dict keyed by canonical_step_id."""
    result: dict[str, ResolvedStepRef] = {}
    for cid in canonical_step_ids:
        ref = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=cid,
            branch_step_map=branch_step_map,
            allow_ancestor=allow_ancestor,
        )
        if ref is not None:
            result[cid] = ref
    return result


def resolve_run_step(
    store: ProjectStore,
    ref: ResolvedStepRef,
    plan_version_id: str,
) -> RunStepRecord | None:
    """Resolve a ``RunStepRecord`` for the given step reference.

    Looks up the latest successful run step by ``(plan_version_id, step_id)``
    on the resolved branch, falling back to plan-level if no branch runs exist.
    """
    branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None

    repo = RunRepository(store)
    rs = repo.get_latest_successful_step(plan_version_id, ref.step_id, branch_id=branch_id)
    if rs is None and branch_id is not None:
        rs = repo.get_latest_successful_step(plan_version_id, ref.step_id, branch_id=None)

    if rs is None:
        return None

    return RunStepRecord(rs, store=store)


__all__ = [
    "ResolvedStepRef",
    "resolve_run_step",
    "resolve_step_for_branch",
    "resolve_required_steps",
]
