"""Report readiness validation — determines whether a report can be generated.

Distinguishes champion mode (blocked without champion assignment) from
branch mode (warns but does not block without champion assignment).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cardre.readiness.dto import ReadinessBlocker, ReadinessWarning, ReportReadinessResult
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
    canonical_alias_candidates,
)
from cardre.step_id import resolve_run_step, resolve_required_steps, resolve_step_for_branch
from cardre.store import ProjectStore


def _check_oot_exists(store: ProjectStore, run_id: str) -> bool:
    for rs in store.get_run_steps(run_id):
        for aid in rs.output_artifact_ids:
            art = store.get_artifact(aid)
            if art and art.role == "oot":
                return True
    return False


BLOCKER_CODES = LimitationCode.blocker_codes()

WARNING_CODES = LimitationCode.warning_codes()


def check_report_readiness(
    store: ProjectStore,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: str = "branch",
) -> ReportReadinessResult:
    """Validate whether a report can be generated for the given branch and mode."""
    blockers: list[ReadinessBlocker] = []
    warnings: list[ReadinessWarning] = []

    # Resolve target branch
    branch = store.get_branch(target_branch_id)
    if branch is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_NOT_FOUND,
            f"Target branch {target_branch_id!r} not found.",
        ))
        return ReportReadinessResult(
            blockers=blockers,
            target_branch_id=target_branch_id,
            run_id=run_id,
            report_mode=report_mode,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    if branch.get("status") != "active":
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"Target branch {target_branch_id!r} has status {branch.get('status')!r}.",
        ))

    # Resolve run
    run = store.get_run(run_id)
    if run is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_RUN_MANIFEST,
            f"Run {run_id!r} not found.",
        ))
        return ReportReadinessResult(
            blockers=blockers,
            target_branch_id=target_branch_id,
            run_id=run_id,
            report_mode=report_mode,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    plan_version_id = run["plan_version_id"]
    plan_id = store.get_plan_id_for_version(plan_version_id)

    # Check plan
    if plan_id is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_PATHWAY,
            f"No plan found for plan version {plan_version_id!r}.",
        ))

    # Check branch step map
    head_pv = branch.get("head_plan_version_id")
    step_map = store.get_branch_step_map(target_branch_id, plan_version_id)
    if not step_map and head_pv:
        step_map = store.get_branch_step_map(target_branch_id, head_pv)
    if not step_map:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"No branch step map found for branch {target_branch_id!r} in plan version {plan_version_id!r}.",
        ))

    # Check required canonical steps present in step map
    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    step_ids_in_map = {row["canonical_step_id"] for row in step_map}

    resolved_step_ids_in_map: set[str] = set()
    for sid in step_ids_in_map:
        resolved_step_ids_in_map.update(canonical_alias_candidates(sid))

    missing_steps = [s for s in required if s not in resolved_step_ids_in_map]
    if missing_steps:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
            f"Required canonical steps not found in branch step map: {missing_steps}",
        ))

    # Per-step: resolve and check run evidence
    resolved = resolve_required_steps(
        branch_id=target_branch_id,
        canonical_step_ids=required,
        branch_step_map=step_map,
    )

    # Lazy legacy resolution: if a required step was not found, check all
    # equivalent current/legacy canonical IDs in the step map.
    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            for candidate in canonical_alias_candidates(canonical_step_id):
                candidate_ref = resolved.get(candidate)
                if candidate_ref is not None:
                    resolved[canonical_step_id] = candidate_ref
                    break

    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            continue

        rs = resolve_run_step(store, plan_version_id, ref.step_id, ref.resolved_branch_id, ref.resolution, run_id)
        if rs is None:
            blockers.append(ReadinessBlocker(
                LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
                f"No successful run step for {canonical_step_id} (step {ref.step_id}).",
                step_id=ref.step_id,
            ))
            continue

        # For WOE/IV, check evidence v1
        if canonical_step_id in ("final-woe-iv", "initial-woe-iv"):
            has_v1 = False
            for aid in rs.output_artifact_ids:
                art = store.get_artifact(aid)
                if art and art.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1":
                    has_v1 = True
                    break
            if not has_v1:
                blockers.append(ReadinessBlocker(
                    LimitationCode.MISSING_WOE_IV_EVIDENCE_V1,
                    f"WOE/IV step {ref.step_id} has no cardre.woe_iv_evidence.v1 artifact. "
                    "Phase 5 requires the controlled evidence artifact.",
                    step_id=ref.step_id,
                ))

    # Champion mode checks
    if plan_id:
        if report_mode == "champion":
            champion = store.get_champion_assignment(plan_id, target_branch_id)
            if champion is None:
                blockers.append(ReadinessBlocker(
                    LimitationCode.CHAMPION_ASSIGNMENT_MISSING,
                    f"No active champion assignment for branch {target_branch_id!r} in champion report mode.",
                ))
        else:
            champ_check = store.get_champion_assignment(plan_id)
            if champ_check is None:
                warnings.append(ReadinessWarning(
                    LimitationCode.NO_CHAMPION_ASSIGNMENT,
                    "No champion branch has been assigned for this plan.",
                ))
            elif champ_check["champion_branch_id"] != target_branch_id:
                warnings.append(ReadinessWarning(
                    LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                    f"Target branch {target_branch_id!r} is not the champion.",
                ))

    # Check manual-binning review status (branch-scoped via step map)
    if plan_id:
        mb_ref = resolve_step_for_branch(
            branch_id=target_branch_id,
            canonical_step_id="manual-binning",
            branch_step_map=step_map,
        )
        if mb_ref is None:
            warnings.append(ReadinessWarning(
                LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
                "No manual-binning step found on this branch.",
            ))
        else:
            mb_step = None
            for s in store.get_plan_version_steps(plan_version_id):
                if s.step_id == mb_ref.step_id:
                    mb_step = s
                    break
            if mb_step is not None:
                params = mb_step.params
                if not params.get("reviewed", False) and not params.get("accept_automated", False):
                    blockers.append(ReadinessBlocker(
                        LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
                        "Manual binning has not been reviewed on this branch. "
                        "Mark review complete or accept automated bins before generating the report.",
                        step_id=mb_ref.step_id,
                    ))

    # Check OOT dataset role
    if not _check_oot_exists(store, run_id):
        warnings.append(ReadinessWarning(
            LimitationCode.NO_OOT_SAMPLE,
            "No OOT dataset role was present for this run.",
        ))

    return ReportReadinessResult(
        blockers=blockers,
        warnings=warnings,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
