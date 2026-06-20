"""Evidence locator — consolidated run-step/evidence lookup policies.

Extracts the duplicated evidence-finding loops scattered across
staleness.py, branch_evidence.py, comparison_service.py, export_service.py,
and step_id.py into a single module with named lookup policies.

Each policy encodes a fallback chain: branch-scoped → full-plan →
across-plan-versions.
"""

from __future__ import annotations

from cardre.audit import RunStepRecord
from cardre.store import ProjectStore

STATUS_SUCCEEDED = "succeeded"


def latest_successful_run_id(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> str | None:
    """Find the latest successful run ID.

    Tries branch-scoped first, then falls back across plan versions
    (branches may reuse shared upstream from earlier plan-level runs).
    """
    run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=branch_id)
    if run_id is not None:
        return run_id

    pv = store.get_plan_version(plan_version_id)
    if pv is None:
        return None

    if branch_id:
        run_id = store.get_any_successful_run_id_for_plan(pv["plan_id"])
        if run_id is not None:
            return run_id

    return store.get_latest_successful_run_id_for_plan(pv["plan_id"])


def latest_successful_run_step(
    store: ProjectStore,
    plan_version_id: str,
    step_id: str,
    branch_id: str | None = None,
) -> RunStepRecord | None:
    """Find the latest successful run step for a step.

    Tries branch-scoped first, then full-plan, then across plan versions.
    """
    rs = store.get_latest_successful_run_step_for_step(
        plan_version_id, step_id, branch_id=branch_id,
    )
    if rs is not None:
        return rs

    if branch_id is not None:
        rs = store.get_latest_successful_run_step_for_step(
            plan_version_id, step_id, branch_id=None,
        )
        if rs is not None:
            return rs

    fallback = _find_run_step_from_plan_level_run(store, plan_version_id, step_id)
    if fallback is not None:
        return fallback

    return None


def latest_successful_run_step_across_plan(
    store: ProjectStore,
    plan_id: str,
    step_id: str,
    branch_id: str | None = None,
) -> RunStepRecord | None:
    """Find the latest successful run step across all plan versions.

    Searches plan-level runs when branch-scoped lookup fails.
    """
    rs = store.get_latest_successful_run_step_for_step_across_plan(
        plan_id, step_id, branch_id=branch_id,
    )
    if rs is not None:
        return rs

    if branch_id is not None:
        rs = store.get_latest_successful_run_step_for_step_across_plan(
            plan_id, step_id, branch_id=None,
        )
        if rs is not None:
            return rs

    plan_run_id = store.get_latest_successful_run_id_for_plan(plan_id)
    if plan_run_id is not None:
        for prs in store.get_run_steps(plan_run_id):
            if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                return prs

    return None


def collect_run_steps_for_plan_version(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> dict[str, RunStepRecord]:
    """Collect run steps for a plan version into a step_id->record map.

    When *branch_id* is provided, merges full-plan evidence for steps
    that the branch run did not execute (shared upstream).
    """
    run_id = latest_successful_run_id(store, plan_version_id, branch_id=branch_id)
    if run_id is None:
        return {}

    rs_by_step: dict[str, RunStepRecord] = {}
    for rs in store.get_run_steps(run_id):
        rs_by_step[rs.step_id] = rs

    if branch_id:
        _merge_full_plan_steps(store, plan_version_id, rs_by_step)

    return rs_by_step


def _find_run_step_from_plan_level_run(
    store: ProjectStore,
    plan_version_id: str,
    step_id: str,
) -> RunStepRecord | None:
    """Fallback: scan the latest plan-level run for a matching step."""
    pv = store.get_plan_version(plan_version_id)
    if pv is None:
        return None
    plan_run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])
    if plan_run_id is None:
        return None
    for prs in store.get_run_steps(plan_run_id):
        if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
            return prs
    return None


def _merge_full_plan_steps(
    store: ProjectStore,
    plan_version_id: str,
    rs_by_step: dict[str, RunStepRecord],
) -> None:
    """Merge full-plan run steps into *rs_by_step* for any step not
    already covered by the branch run."""
    pv = store.get_plan_version(plan_version_id)
    if pv is None:
        return
    full_run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=None)
    if full_run_id is None:
        full_run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])
    if full_run_id is not None:
        for prs in store.get_run_steps(full_run_id):
            if prs.step_id not in rs_by_step:
                rs_by_step[prs.step_id] = prs
