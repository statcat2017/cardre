"""Shared evidence resolver — consolidates store-query patterns used by
readiness.py and collector.py, eliminating duplicated bootstrapping logic.

Every function is stateless: takes the store and parameters, returns data.
"""

from __future__ import annotations

from typing import Any

from cardre.audit import RunStepRecord
from cardre.store import ProjectStore

from cardre.services.step_resolver import (
    resolve_step_for_branch as _resolve_step,
    resolve_required_steps as _resolve_required,
    ResolvedStepRef,
)


def resolve_project(store: ProjectStore, project_id: str) -> dict[str, Any] | None:
    return store.get_project(project_id)


def resolve_branch(store: ProjectStore, branch_id: str) -> dict[str, Any] | None:
    return store.get_branch(branch_id)


def resolve_run(store: ProjectStore, run_id: str) -> dict[str, Any] | None:
    return store.get_run(run_id)


def resolve_plan_context(
    store: ProjectStore, plan_version_id: str,
) -> tuple[str | None, str | None]:
    """Return (plan_id, plan_version_id). plan_id may be None."""
    plan_id = store.get_plan_id_for_version(plan_version_id)
    return plan_id, plan_version_id


def resolve_step_map(
    store: ProjectStore,
    branch_id: str,
    plan_version_id: str,
    head_plan_version_id: str | None = None,
) -> list[dict[str, Any]]:
    step_map = store.get_branch_step_map(branch_id, plan_version_id)
    if not step_map and head_plan_version_id:
        step_map = store.get_branch_step_map(branch_id, head_plan_version_id)
    return step_map


def resolve_required_steps(
    branch_id: str,
    canonical_step_ids: list[str],
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> dict[str, ResolvedStepRef | None]:
    return _resolve_required(
        branch_id=branch_id,
        canonical_step_ids=canonical_step_ids,
        branch_step_map=branch_step_map,
        allow_ancestor=allow_ancestor,
    )


def resolve_run_step(
    store: ProjectStore,
    plan_version_id: str,
    step_id: str,
    resolved_branch_id: str | None = None,
    resolution: str = "exact",
    run_id: str | None = None,
) -> RunStepRecord | None:
    """Resolve a successful run step for the given step_id, with fallback.

    When run_id is provided, first searches the requested run's own steps.
    Only falls back to the latest successful step when:
      - resolution is "ancestor" (inherited/shared-upstream evidence), OR
      - no run_id was provided (caller did not constrain to a specific run).

    When resolution is "exact", a miss in the requested run returns None
    (the step must be present in this run to count as evidence).  This
    prevents silently borrowing evidence from a different run.
    """
    # 1. Try the requested run's own run steps first (governance-grade)
    if run_id is not None:
        for rs in store.get_run_steps(run_id):
            if rs.step_id == step_id and rs.status == "succeeded":
                return rs

    # 2. Fall back: only ancestor/inherited evidence may come from outside
    #    the requested run.  Exact branch-owned steps missing from the run
    #    are treated as not found (the caller will emit a blocker).
    if resolution == "exact":
        return None

    branch_id_for_lookup = resolved_branch_id if resolution == "exact" else None
    rs = store.get_latest_successful_run_step_for_step(
        plan_version_id, step_id, branch_id=branch_id_for_lookup,
    )
    if rs is None and branch_id_for_lookup is not None:
        rs = store.get_latest_successful_run_step_for_step(
            plan_version_id, step_id, branch_id=None,
        )
    return rs


def get_champion_assignment(store: ProjectStore, plan_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
    """Get the current champion assignment for a plan, optionally filtered by branch."""
    return store.get_champion_assignment(plan_id, branch_id)


def check_oot_exists(store: ProjectStore, run_id: str) -> bool:
    """Check whether any artifact in the run has the 'oot' role."""
    for rs in store.get_run_steps(run_id):
        for aid in rs.output_artifact_ids:
            art = store.get_artifact(aid)
            if art and art.role == "oot":
                return True
    return False
