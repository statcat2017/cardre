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
from cardre.evidence_resolver import EvidenceResolver
from cardre.store import ProjectStore


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
) -> dict[str, ResolvedStepRef | None]:
    result: dict[str, ResolvedStepRef | None] = {}
    for cid in canonical_step_ids:
        result[cid] = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=cid,
            branch_step_map=branch_step_map,
            allow_ancestor=allow_ancestor,
        )
    return result


def resolve_run_step(
    store: ProjectStore,
    plan_version_id: str,
    step_id: str,
    resolved_branch_id: str | None = None,
    resolution: str = "exact",
    run_id: str | None = None,
) -> RunStepRecord | None:
    resolver = EvidenceResolver(store)

    if run_id is not None:
        rs, source, _diags = resolver.resolve(
            plan_version_id, step_id, run_id=run_id, policy="run_only",
        )
        if rs is not None:
            return rs

    if resolution == "exact":
        return None

    branch_id_for_lookup = resolved_branch_id if resolution in ("exact", "ancestor") else None
    rs, source, _diags = resolver.resolve(
        plan_version_id, step_id, branch_id=branch_id_for_lookup,
        policy="branch_then_full_then_plan",
    )
    if rs is not None:
        return rs

    if resolution == "ancestor":
        plan_id = store.get_plan_id_for_version(plan_version_id)
        rs, source, _diags = resolver.resolve(
            plan_version_id, step_id, branch_id=branch_id_for_lookup,
            plan_id=plan_id, policy="across_plan",
        )
        if rs is not None:
            return rs

    return None
