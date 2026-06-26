"""Evidence locator — compatibility shim over EvidenceResolver.

All public functions now delegate to ``cardre.evidence_resolver``.
This shim exists for backward compatibility during migration and will be
deleted once all call sites move to ``EvidenceResolver`` directly.
"""

from __future__ import annotations

from cardre.audit import ArtifactRef, RunStepRecord
from cardre.evidence_resolver import EvidenceResolver
from cardre.store import ProjectStore

STATUS_SUCCEEDED = "succeeded"


def latest_successful_run_id(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> str | None:
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
    resolver = EvidenceResolver(store)
    rs, source, _diags = resolver.resolve(
        plan_version_id, step_id, branch_id=branch_id,
        policy="branch_then_full_then_plan",
    )
    return rs


def latest_successful_run_step_across_plan(
    store: ProjectStore,
    plan_id: str,
    step_id: str,
    branch_id: str | None = None,
) -> RunStepRecord | None:
    resolver = EvidenceResolver(store)
    latest_pv_id = store.get_latest_plan_version_id(plan_id) if plan_id else None
    plan_version_id = latest_pv_id or ""
    rs, source, _diags = resolver.resolve(
        plan_version_id, step_id, branch_id=branch_id,
        plan_id=plan_id, policy="across_plan",
    )
    return rs


def collect_run_steps_for_plan_version(
    store: ProjectStore,
    plan_version_id: str,
    branch_id: str | None = None,
) -> dict[str, RunStepRecord]:
    run_id = latest_successful_run_id(store, plan_version_id, branch_id=branch_id)
    if run_id is None:
        return {}

    rs_by_step: dict[str, RunStepRecord] = {}
    for rs in store.get_run_steps(run_id):
        rs_by_step[rs.step_id] = rs

    if branch_id:
        _merge_full_plan_steps(store, plan_version_id, rs_by_step)

    return rs_by_step


def _merge_full_plan_steps(
    store: ProjectStore,
    plan_version_id: str,
    rs_by_step: dict[str, RunStepRecord],
) -> None:
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


def resolve_output_artifacts(
    store: ProjectStore,
    rs: RunStepRecord,
) -> list[ArtifactRef]:
    artifacts = []
    for aid in rs.output_artifact_ids:
        a = store.get_artifact(aid)
        if a is not None:
            artifacts.append(a)
    return artifacts
