"""Evidence locator — consolidated run-step/evidence lookup policies.

Phase 5 port from v1.  Uses v2 RunRepository for lookup.
"""

from __future__ import annotations

from cardre.audit import RunStepRecord
from cardre.store import ProjectStore
from cardre.store.run_repo import RunRepository


STATUS_SUCCEEDED = "succeeded"


def latest_successful_run_id(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> str | None:
    """Find the latest successful run ID.

    Tries branch-scoped first, then falls back across plan versions.
    """
    repo = RunRepository(store)
    run_id = repo.get_latest_successful_id(plan_version_id, branch_id=branch_id)
    if run_id is not None:
        return run_id

    pv = store.get_plan_version(plan_version_id)
    if pv is None:
        return None

    if branch_id:
        plan_id = pv["plan_id"] if isinstance(pv, dict) else None
        if plan_id:
            run_id = repo.get_any_successful_id_for_plan(plan_id)
            if run_id is not None:
                return run_id

    return None


def latest_successful_run_step(
    store: ProjectStore,
    plan_version_id: str,
    step_id: str,
    branch_id: str | None = None,
) -> RunStepRecord | None:
    """Find the latest successful run step."""
    repo = RunRepository(store)
    rs = repo.get_latest_successful_step(plan_version_id, step_id, branch_id=branch_id)
    if rs is None and branch_id is not None:
        rs = repo.get_latest_successful_step(plan_version_id, step_id, branch_id=None)
    if rs is None:
        return None
    return RunStepRecord(rs, store=store)


__all__ = [
    "latest_successful_run_id",
    "latest_successful_run_step",
]
