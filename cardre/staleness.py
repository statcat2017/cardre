"""Staleness computation — pure functions, no NodeRegistry dependency.

Extracted from PlanExecutor so callers can compute staleness without
instantiating a full executor + registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from cardre.audit import RunStepRecord, StepSpec
from cardre.evidence_locator import collect_run_steps_for_plan_version
from cardre.errors import GraphValidationError
from cardre.store import ProjectStore


@dataclass
class StalenessDetail:
    step_id: str
    is_stale: bool
    reason: str | None


def compute_staleness(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
    plan_id: str | None = None,
) -> dict[str, bool]:
    """Return {step_id: is_stale} for each step in the plan version.

    When branch_id is provided, looks for run evidence specific to
    that branch.  When branch_id is None, looks for full-plan
    (non-branch) runs only.
    """
    steps = store.get_plan_version_steps(plan_version_id)

    if plan_id is None:
        pv = store.get_plan_version(plan_version_id)
        if pv is not None:
            plan_id = pv.get("plan_id")

    rs_by_step = collect_run_steps_for_plan_version(store, plan_version_id, branch_id=branch_id)

    stale: dict[str, bool] = {}
    for spec in steps:
        is_stale = step_is_stale(spec, steps, rs_by_step, stale, store=store, plan_id=plan_id, branch_id=branch_id)
        stale[spec.step_id] = is_stale
    return stale


def step_is_stale(
    spec: StepSpec,
    all_steps: list[StepSpec],
    rs_by_step: dict[str, RunStepRecord],
    stale_cache: dict[str, bool],
    store: ProjectStore | None = None,
    plan_id: str | None = None,
    branch_id: str | None = None,
) -> bool:
    if spec.step_id in stale_cache:
        return stale_cache[spec.step_id]

    rs = rs_by_step.get(spec.step_id)
    if rs is None:
        if store is not None and plan_id is not None:
            fallback_rs = store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, spec.step_id, branch_id=branch_id,
            )
            if fallback_rs is not None:
                fp = fallback_rs.execution_fingerprint
                if (fp.get("params_hash", "") == spec.params_hash
                        and fp.get("node_type", "") == spec.node_type
                        and fp.get("node_version", "") == spec.node_version):
                    rs = fallback_rs
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
        if step_is_stale(_find_spec(pid, all_steps), all_steps, rs_by_step, stale_cache, store=store, plan_id=plan_id, branch_id=branch_id):
            stale_cache[spec.step_id] = True
            return True

        parent_rs = rs_by_step.get(pid)
        if parent_rs is None:
            if store is not None and plan_id is not None:
                fallback_parent = store.get_latest_successful_run_step_for_step_across_plan(
                    plan_id, pid, branch_id=branch_id,
                )
                if fallback_parent is not None:
                    fp_parent = fallback_parent.execution_fingerprint
                    if (fp_parent.get("params_hash", "") == _find_spec(pid, all_steps).params_hash
                            and fp_parent.get("node_type", "") == _find_spec(pid, all_steps).node_type
                            and fp_parent.get("node_version", "") == _find_spec(pid, all_steps).node_version):
                        parent_rs = fallback_parent
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
    raise GraphValidationError(
        f"Missing parent step {step_id!r} referenced by staleness walk",
        context={"missing_step_id": step_id, "known_step_ids": [s.step_id for s in steps]},
    )


def _staleness_reason(
    spec: StepSpec,
    steps: list[StepSpec],
    rs_by_step: dict[str, RunStepRecord],
    stale_results: dict[str, bool],
) -> str | None:
    rs = rs_by_step.get(spec.step_id)
    if rs is None:
        return "never_run"

    fp = rs.execution_fingerprint

    if fp.get("params_hash", "") != spec.params_hash:
        return "params_changed"

    if fp.get("node_type", "") != spec.node_type or fp.get("node_version", "") != spec.node_version:
        return "node_version_changed"

    parent_output_by_step: dict[str, list[str]] = fp.get(
        "parent_output_logical_hashes_by_step", {}
    )

    for pid in spec.parent_step_ids:
        stored_parent_outputs = parent_output_by_step.get(pid, [])
        parent_rs = rs_by_step.get(pid)
        if parent_rs is not None:
            current_parent_outputs = parent_rs.execution_fingerprint.get(
                "output_artifact_logical_hashes", []
            )
            if stored_parent_outputs != current_parent_outputs:
                return "upstream_artifact_changed"

        if stale_results.get(pid, True):
            return "upstream_stale"

    return None


def staleness_detail(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> list[StalenessDetail]:
    steps = store.get_plan_version_steps(plan_version_id)

    rs_by_step = collect_run_steps_for_plan_version(store, plan_version_id, branch_id=branch_id)
    if not rs_by_step:
        return [StalenessDetail(step_id=s.step_id, is_stale=True, reason="never_run") for s in steps]

    stale_results = compute_staleness(store, plan_version_id, branch_id=branch_id)
    results: list[StalenessDetail] = []
    for spec in steps:
        is_stale = stale_results[spec.step_id]
        reason = _staleness_reason(spec, steps, rs_by_step, stale_results) if is_stale else None
        results.append(StalenessDetail(step_id=spec.step_id, is_stale=is_stale, reason=reason))
    return results
