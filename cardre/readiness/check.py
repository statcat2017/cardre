"""Report readiness validation — determines whether a report can be generated.

Distinguishes champion mode (blocked without champion assignment) from
branch mode (warns but does not block without champion assignment).
"""

from __future__ import annotations

from datetime import UTC, datetime

from cardre.branch_step_resolver import resolve_required_steps
from cardre.readiness.dto import ReadinessFinding, ReportReadinessResult
from cardre.readiness.limitation_codes import LimitationCode
from cardre.readiness.step_requirements import (
    check_champion_readiness,
    check_manual_binning_readiness,
    check_oot_readiness,
    check_per_step_evidence,
)
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
)
from cardre.reporting.types import ReportMode
from cardre.store import ProjectStore
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_repo import RunRepository

BLOCKER_CODES = LimitationCode.blocker_codes()

WARNING_CODES = LimitationCode.warning_codes()


def check_report_readiness(
    store: ProjectStore,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: ReportMode = "branch",
) -> ReportReadinessResult:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []

    branch = BranchRepository(store).get_branch(target_branch_id)
    if branch is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_NOT_FOUND,
            message=f"Target branch {target_branch_id!r} not found.",
        ))
        return _early_result(blockers, target_branch_id, run_id, report_mode)

    if branch.get("status") != "active":
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_INCOMPLETE,
            message=f"Target branch {target_branch_id!r} has status {branch.get('status')!r}.",
        ))

    run = RunRepository(store).get(run_id)
    if run is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_RUN_MANIFEST,
            message=f"Run {run_id!r} not found.",
        ))
        return _early_result(blockers, target_branch_id, run_id, report_mode)

    if run.get("status") != "succeeded":
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.RUN_NOT_SUCCEEDED,
            message=f"Run {run_id!r} has status {run.get('status', 'unknown')!r}, expected 'succeeded'.",
        ))

    plan_version_id = run["plan_version_id"]
    plan_id = PlanRepository(store).get_plan_id_for_version(plan_version_id)

    if plan_id is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_PATHWAY,
            message=f"No plan found for plan version {plan_version_id!r}.",
        ))

    head_pv = branch.get("head_plan_version_id")
    step_map = BranchRepository(store).get_step_map(target_branch_id, plan_version_id)
    if not step_map and head_pv:
        step_map = BranchRepository(store).get_step_map(target_branch_id, head_pv)
    if not step_map:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_INCOMPLETE,
            message=f"No branch step map found for branch {target_branch_id!r} in plan version {plan_version_id!r}.",
        ))

    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    step_ids_in_map = {row["canonical_step_id"] for row in step_map}
    missing_steps = [s for s in required if s not in step_ids_in_map]
    if missing_steps:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
            message=f"Required canonical steps not found in branch step map: {missing_steps}",
        ))

    resolved = resolve_required_steps(
        branch_id=target_branch_id,
        canonical_step_ids=required,
        branch_step_map=step_map,
    )

    check_per_step_evidence(store, required, resolved, plan_version_id, report_mode, blockers)
    check_champion_readiness(store, plan_id, target_branch_id, report_mode, blockers, warnings)
    check_manual_binning_readiness(store, plan_id, target_branch_id, plan_version_id, step_map, blockers, warnings)
    check_oot_readiness(store, run_id, report_mode, blockers, warnings)

    return ReportReadinessResult(
        blockers=blockers,
        warnings=warnings,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(UTC).isoformat(),
    )


def _early_result(
    blockers: list[ReadinessFinding], target_branch_id: str, run_id: str, report_mode: ReportMode,
) -> ReportReadinessResult:
    return ReportReadinessResult(
        blockers=blockers,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "ReportReadinessResult",
    "check_report_readiness",
]
