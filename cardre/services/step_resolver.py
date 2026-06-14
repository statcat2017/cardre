"""Shared branch step resolver — resolves canonical_step_id to branch-scoped step_id.

Phase 5 rule: the report collector must not infer step IDs.
It must resolve evidence using target_branch_id + canonical_step_id
through the branch_step_map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    """Resolve a canonical_step_id to a branch-scoped step_id.

    Looks up the branch_step_map for the target branch.  If the step
    exists as a branch-owned entry the resolution is "exact".  If the
    step is shared upstream (inherited from a parent branch) the
    resolution is "ancestor".

    Returns None if the canonical_step_id is not found in the
    branch_step_map for this branch.
    """
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
) -> dict[str, ResolvedStepRef | None]:
    """Resolve multiple canonical_step_ids for a branch.

    Returns a dict mapping canonical_step_id to ResolvedStepRef or None.
    """
    result: dict[str, ResolvedStepRef | None] = {}
    for cid in canonical_step_ids:
        result[cid] = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=cid,
            branch_step_map=branch_step_map,
            allow_ancestor=allow_ancestor,
        )
    return result
