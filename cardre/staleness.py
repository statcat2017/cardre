"""Staleness computation — pure functions, no NodeRegistry dependency.

Extracted from PlanExecutor so callers can compute staleness without
instantiating a full executor + registry.
"""

from __future__ import annotations

from typing import Any

from cardre.audit import RunStepRecord, StepSpec
from cardre.store import ProjectStore


def compute_staleness(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> dict[str, bool]:
    """Return {step_id: is_stale} for each step in the plan version.

    When branch_id is provided, looks for run evidence specific to
    that branch.  When branch_id is None, looks for full-plan
    (non-branch) runs only.
    """
    steps = store.get_plan_version_steps(plan_version_id)
    run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=branch_id)

    if run_id is None and branch_id:
        pv = store.get_plan_version(plan_version_id)
        if pv is not None:
            run_id = store.get_any_successful_run_id_for_plan(pv["plan_id"])

    if run_id is None:
        pv = store.get_plan_version(plan_version_id)
        if pv is not None:
            run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])

        if run_id is None:
            return {s.step_id: True for s in steps}

    run_steps = store.get_run_steps(run_id)
    rs_by_step = {rs.step_id: rs for rs in run_steps}

    if branch_id:
        pv = store.get_plan_version(plan_version_id)
        if pv is not None:
            full_run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=None)
            if full_run_id is None:
                full_run_id = store.get_latest_successful_run_id_for_plan(pv["plan_id"])
            if full_run_id is not None and full_run_id != run_id:
                for prs in store.get_run_steps(full_run_id):
                    if prs.step_id not in rs_by_step:
                        rs_by_step[prs.step_id] = prs

    stale: dict[str, bool] = {}
    for spec in steps:
        is_stale = _step_is_stale(store, spec, steps, rs_by_step, stale)
        stale[spec.step_id] = is_stale
    return stale


def _step_is_stale(
    store: ProjectStore,
    spec: StepSpec,
    all_steps: list[StepSpec],
    rs_by_step: dict[str, RunStepRecord],
    stale_cache: dict[str, bool],
) -> bool:
    if spec.step_id in stale_cache:
        return stale_cache[spec.step_id]

    rs = rs_by_step.get(spec.step_id)
    if rs is None:
        stale_cache[spec.step_id] = True
        return True

    fp = rs.execution_fingerprint

    if fp.get("params_hash", "") != spec.params_hash:
        stale_cache[spec.step_id] = True
        return True

    if fp.get("node_type", "") != spec.node_type or fp.get("node_version", "") != spec.node_version:
        stale_cache[spec.step_id] = True
        return True

    parent_output_by_step: dict[str, list[str]] = fp.get(
        "parent_output_logical_hashes_by_step", {}
    )

    for pid in spec.parent_step_ids:
        if _step_is_stale(store, _find_spec(pid, all_steps), all_steps, rs_by_step, stale_cache):
            stale_cache[spec.step_id] = True
            return True

        parent_rs = rs_by_step.get(pid)
        if parent_rs is None:
            stale_cache[spec.step_id] = True
            return True

        stored_parent_outputs = parent_output_by_step.get(pid, [])
        current_parent_outputs = parent_rs.execution_fingerprint.get(
            "output_artifact_logical_hashes", []
        )
        if stored_parent_outputs != current_parent_outputs:
            stale_cache[spec.step_id] = True
            return True

    stale_cache[spec.step_id] = False
    return False


def _find_spec(step_id: str, steps: list[StepSpec]) -> StepSpec:
    for s in steps:
        if s.step_id == step_id:
            return s
    raise KeyError(step_id)
