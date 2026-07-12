"""Canonical branch step resolution — single shared resolver for step lookups.

Replaces three private copies of ``ResolvedStepRef`` and the associated
resolution helpers.  All consumers (collector, readiness check) import
from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cardre.reporting.schema import ResolvedStepRef as SchemaResolvedStepRef
    from cardre.store import ProjectStore


@dataclass
class ResolvedStepRef:
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str = "exact"  # "exact" | "ancestor"

    def to_schema_ref(self) -> SchemaResolvedStepRef:
        """Convert to the Pydantic schema version for report bundles."""
        from cardre.reporting.schema import ResolvedStepRef as SchemaResolvedStepRef
        return SchemaResolvedStepRef(
            requested_branch_id=self.requested_branch_id,
            resolved_branch_id=self.resolved_branch_id,
            canonical_step_id=self.canonical_step_id,
            step_id=self.step_id,
            resolution=self.resolution,
        )


def _get_branch_step_map(
    store: ProjectStore,
    branch_id: str,
    plan_version_id: str,
) -> list[dict[str, Any]]:
    """Fetch the branch step map, falling back to head plan version."""
    step_map = store.get_branch_step_map(branch_id, plan_version_id)
    if not step_map:
        branch = store.get_branch(branch_id)
        if branch and branch.get("head_plan_version_id"):
            step_map = store.get_branch_step_map(branch_id, branch["head_plan_version_id"])
    return step_map or []


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


def resolve_step_for_branch_by_store(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str,
    canonical_step_id: str,
    *,
    allow_ancestor: bool = True,
) -> ResolvedStepRef | None:
    """Resolve a single canonical step for a branch, fetching the step map from the store."""
    step_map = _get_branch_step_map(store, branch_id, plan_version_id)
    return resolve_step_for_branch(
        branch_id=branch_id,
        canonical_step_id=canonical_step_id,
        branch_step_map=step_map,
        allow_ancestor=allow_ancestor,
    )


def resolve_required_steps_by_store(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str,
    canonical_step_ids: list[str],
    *,
    allow_ancestor: bool = True,
) -> dict[str, ResolvedStepRef]:
    """Resolve multiple canonical steps for a branch, fetching the step map from the store."""
    step_map = _get_branch_step_map(store, branch_id, plan_version_id)
    return resolve_required_steps(
        branch_id=branch_id,
        canonical_step_ids=canonical_step_ids,
        branch_step_map=step_map,
        allow_ancestor=allow_ancestor,
    )


__all__ = [
    "ResolvedStepRef",
    "resolve_step_for_branch",
    "resolve_step_for_branch_by_store",
    "resolve_required_steps",
    "resolve_required_steps_by_store",
]
