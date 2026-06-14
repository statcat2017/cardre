"""Report readiness validation — determines whether a report can be generated.

Distinguishes champion mode (blocked without champion assignment) from
branch mode (warns but does not block without champion assignment).
"""

from __future__ import annotations

from typing import Any

from cardre.reporting.evidence_resolver import (
    check_oot_exists,
    get_champion_assignment,
    resolve_branch,
    resolve_plan_context,
    resolve_run,
    resolve_run_step,
    resolve_step_map,
    resolve_required_steps,
)
from cardre.reporting.limitation_codes import LimitationCode
from cardre.store import ProjectStore

REQUIRED_STEPS_CHAMPION = [
    "final-woe-iv",
    "logistic-regression",
    "score-scaling",
    "validation-metrics",
]

REQUIRED_STEPS_BRANCH = [
    "final-woe-iv",
    "logistic-regression",
    "score-scaling",
    "validation-metrics",
]

BLOCKER_CODES = LimitationCode.blocker_codes()

WARNING_CODES = LimitationCode.warning_codes()


class ReadinessBlocker:
    code: str
    message: str

    @staticmethod
    def _normalize(code: str) -> str:
        try:
            return LimitationCode(code)
        except ValueError:
            return code

    def __init__(self, code: str, message: str) -> None:
        self.code = self._normalize(code)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": str(self.code), "message": self.message}


class ReadinessWarning:
    code: str
    message: str

    @staticmethod
    def _normalize(code: str) -> str:
        try:
            return LimitationCode(code)
        except ValueError:
            return code

    def __init__(self, code: str, message: str) -> None:
        self.code = self._normalize(code)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": str(self.code), "message": self.message}


class ReportReadinessResult:
    ready: bool
    status: str
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]

    def __init__(
        self,
        blockers: list[ReadinessBlocker] | None = None,
        warnings: list[ReadinessWarning] | None = None,
    ) -> None:
        self.blockers = blockers or []
        self.warnings = warnings or []
        self.ready = len(self.blockers) == 0
        if self.ready:
            self.status = "ready_with_warnings" if self.warnings else "ready"
        else:
            self.status = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "blockers": [b.to_dict() for b in self.blockers],
            "warnings": [w.to_dict() for w in self.warnings],
        }


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
    branch = resolve_branch(store, target_branch_id)
    if branch is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_NOT_FOUND,
            f"Target branch {target_branch_id!r} not found.",
        ))
        return ReportReadinessResult(blockers=blockers)

    if branch.get("status") != "active":
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"Target branch {target_branch_id!r} has status {branch.get('status')!r}.",
        ))

    # Resolve run
    run = resolve_run(store, run_id)
    if run is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_RUN_MANIFEST,
            f"Run {run_id!r} not found.",
        ))
        return ReportReadinessResult(blockers=blockers)

    plan_version_id = run["plan_version_id"]
    plan_id, _ = resolve_plan_context(store, plan_version_id)

    # Check plan
    if plan_id is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_PATHWAY,
            f"No plan found for plan version {plan_version_id!r}.",
        ))

    # Check branch step map
    head_pv = branch.get("head_plan_version_id")
    step_map = resolve_step_map(store, target_branch_id, plan_version_id, head_pv)
    if not step_map:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"No branch step map found for branch {target_branch_id!r} in plan version {plan_version_id!r}.",
        ))

    # Check required canonical steps present in step map
    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    step_ids_in_map = {row["canonical_step_id"] for row in step_map}
    missing_steps = [s for s in required if s not in step_ids_in_map]
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

    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            continue

        rs = resolve_run_step(store, plan_version_id, ref.step_id, ref.resolved_branch_id, ref.resolution)
        if rs is None:
            blockers.append(ReadinessBlocker(
                LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
                f"No successful run step for {canonical_step_id} (step {ref.step_id}).",
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
                warnings.append(ReadinessWarning(
                    LimitationCode.LEGACY_WOE_SUMMARY_USED,
                    f"WOE/IV step {ref.step_id} has no cardre.woe_iv_evidence.v1 artifact. "
                    "Legacy summary parsing will be attempted.",
                ))

    # Champion mode checks
    if plan_id:
        if report_mode == "champion":
            champion = get_champion_assignment(store, plan_id, target_branch_id)
            if champion is None:
                blockers.append(ReadinessBlocker(
                    LimitationCode.CHAMPION_ASSIGNMENT_MISSING,
                    f"No active champion assignment for branch {target_branch_id!r} in champion report mode.",
                ))
        else:
            champ_check = get_champion_assignment(store, plan_id)
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

    # Check OOT dataset role
    if not check_oot_exists(store, run_id):
        warnings.append(ReadinessWarning(
            LimitationCode.NO_OOT_SAMPLE,
            "No OOT dataset role was present for this run.",
        ))

    return ReportReadinessResult(blockers=blockers, warnings=warnings)
