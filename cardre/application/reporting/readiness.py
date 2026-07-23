"""Port-native readiness checks for governance reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.unit_of_work import UnitOfWork
from cardre.application.reporting.contracts import (
    EVIDENCE_KIND_BY_STEP,
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
    ReportMode,
    resolve_required_steps,
)


@dataclass(frozen=True)
class ReadinessFinding:
    severity: str
    code: str
    message: str
    step_id: str | None = None


@dataclass(frozen=True)
class ReportReadinessResult:
    blockers: list[ReadinessFinding] = field(default_factory=list)
    warnings: list[ReadinessFinding] = field(default_factory=list)
    target_branch_id: str = ""
    run_id: str = ""
    report_mode: ReportMode = "branch"
    checked_at: str = ""

    @property
    def ready(self) -> bool:
        return not self.blockers


def check_report_readiness(
    uow: UnitOfWork,
    evidence_reader: EvidenceReaderPort,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: ReportMode = "branch",
) -> ReportReadinessResult:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []
    branch = uow.branches.get_branch(target_branch_id)
    run = uow.runs.get(run_id)
    if branch is None:
        blockers.append(ReadinessFinding("blocker", "TARGET_BRANCH_NOT_FOUND", "Target branch not found."))
    if run is None:
        blockers.append(ReadinessFinding("blocker", "MISSING_RUN_MANIFEST", "Run not found."))
    if blockers:
        return ReportReadinessResult(blockers, warnings, target_branch_id, run_id, report_mode, datetime.now(UTC).isoformat())
    assert branch is not None and run is not None
    if branch.get("status") != "active":
        blockers.append(ReadinessFinding("blocker", "TARGET_BRANCH_INCOMPLETE", "Target branch is not active."))
    if str(run.status) != "succeeded":
        blockers.append(ReadinessFinding("blocker", "RUN_NOT_SUCCEEDED", "Run must have succeeded."))
    if branch.get("project_id") != project_id:
        blockers.append(ReadinessFinding("blocker", "TARGET_BRANCH_INCOMPLETE", "Branch belongs to another project."))
    step_map = uow.branches.get_step_map(target_branch_id, run.plan_version_id)
    if not step_map and branch.get("head_plan_version_id"):
        step_map = uow.branches.get_step_map(target_branch_id, branch["head_plan_version_id"])
    if not step_map:
        blockers.append(ReadinessFinding("blocker", "TARGET_BRANCH_INCOMPLETE", "Target branch has no step map."))
    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    resolved = resolve_required_steps(target_branch_id, required, step_map)
    plan_id = uow.plans.get_plan_id_for_version(run.plan_version_id)
    requested_steps = {step.step_id: step for step in uow.run_steps.get_for_run(run.run_id)}
    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            blockers.append(ReadinessFinding("blocker", "MISSING_REQUIRED_CANONICAL_STEP", f"Missing {canonical_step_id}."))
            continue
        run_step = requested_steps.get(ref.step_id)
        if run_step is None:
            result = resolve_run_step_evidence(
                uow, run.plan_version_id, ref.step_id,
                branch_id=ref.resolved_branch_id, plan_id=plan_id,
            )
            run_step = result.run_step if result is not None else None
        if run_step is None:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_CANONICAL_STEP",
                f"No successful evidence for {canonical_step_id}.", ref.step_id,
            ))
            continue
        outputs = uow.artifacts.output_artifacts_for_run_step(run_step.run_step_id)
        if not outputs:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_EVIDENCE",
                f"No output artifacts for {canonical_step_id}.", ref.step_id,
            ))
        evidence_kind = EVIDENCE_KIND_BY_STEP.get(canonical_step_id)
        if evidence_kind is not None and evidence_reader.read_step_output_optional(
            run_step.run_step_id, evidence_kind,
        ) is None:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_EVIDENCE",
                f"No {evidence_kind.value} evidence for {canonical_step_id}.", ref.step_id,
            ))
    if report_mode == "champion" and (plan_id is None or uow.champion.get_champion_assignment(plan_id, target_branch_id) is None):
        blockers.append(ReadinessFinding("blocker", "CHAMPION_ASSIGNMENT_MISSING", "No champion assignment for this branch."))
    if report_mode == "branch" and plan_id is not None:
        champion = uow.champion.get_champion_assignment(plan_id)
        if champion is None:
            warnings.append(ReadinessFinding("warning", "NO_CHAMPION_ASSIGNMENT", "No champion branch has been assigned."))
        elif champion.get("champion_branch_id") != target_branch_id:
            warnings.append(ReadinessFinding("warning", "TARGET_BRANCH_NOT_CHAMPION", "Target branch is not the champion."))
    if report_mode == "champion" and not any(
        artifact.role == "oot"
        for run_step in uow.run_steps.get_for_run(run_id)
        for artifact in uow.artifacts.output_artifacts_for_run_step(run_step.run_step_id)
    ):
        blockers.append(ReadinessFinding("blocker", "NO_OOT_SAMPLE_CHAMPION", "Champion reports require an OOT dataset."))
    if report_mode == "branch" and not any(
        artifact.role == "oot"
        for run_step in uow.run_steps.get_for_run(run_id)
        for artifact in uow.artifacts.output_artifacts_for_run_step(run_step.run_step_id)
    ):
        warnings.append(ReadinessFinding("warning", "NO_OOT_SAMPLE", "No OOT dataset is available."))
    return ReportReadinessResult(blockers, warnings, target_branch_id, run_id, report_mode, datetime.now(UTC).isoformat())


__all__ = ["ReadinessFinding", "ReportReadinessResult", "check_report_readiness"]
