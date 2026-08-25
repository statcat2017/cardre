"""Port-native readiness checks for reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.evidence.explain_staleness import step_is_stale
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.unit_of_work import UnitOfWork
from cardre.application.reporting.contracts import EVIDENCE_KIND_BY_STEP, REQUIRED_STEPS_COLLECTOR


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
    run_id: str = ""
    checked_at: str = ""

    @property
    def ready(self) -> bool:
        return not self.blockers


def check_report_readiness(
    uow: UnitOfWork,
    evidence_reader: EvidenceReaderPort,
    project_id: str,
    run_id: str,
) -> ReportReadinessResult:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []
    run = uow.runs.get(run_id)
    if run is None:
        blockers.append(ReadinessFinding("blocker", "MISSING_RUN_MANIFEST", "Run not found."))
        return ReportReadinessResult(blockers, warnings, run_id, datetime.now(UTC).isoformat())
    if str(run.status) != "succeeded":
        blockers.append(ReadinessFinding("blocker", "RUN_NOT_SUCCEEDED", "Run must have succeeded."))
        return ReportReadinessResult(blockers, warnings, run_id, datetime.now(UTC).isoformat())

    plan_id = uow.plans.get_plan_id_for_version(run.plan_version_id)
    plan_steps = uow.plans.get_version_steps(run.plan_version_id)
    specs = {step.step_id: step for step in plan_steps}
    requested_steps = {step.step_id: step for step in uow.run_steps.get_for_run(run.run_id)}
    for canonical_step_id in REQUIRED_STEPS_COLLECTOR:
        step = next((s for s in plan_steps if s.canonical_step_id == canonical_step_id), None)
        if step is None:
            blockers.append(ReadinessFinding("blocker", "MISSING_REQUIRED_CANONICAL_STEP", f"Missing {canonical_step_id}."))
            continue
        run_step = requested_steps.get(step.step_id)
        if run_step is None:
            result = resolve_run_step_evidence(
                uow, run.plan_version_id, step.step_id,
                plan_id=plan_id,
                fingerprint_match=specs.get(step.step_id),
            )
            run_step = result.run_step if result is not None and not step_is_stale(
                uow, step, plan_steps, run.plan_version_id, plan_id, result.run_step,
            ) else None
        if run_step is None:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_CANONICAL_STEP",
                f"No successful evidence for {canonical_step_id}.", step.step_id,
            ))
            continue
        outputs = uow.artifacts.output_artifacts_for_run_step(run_step.run_step_id)
        if not outputs:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_EVIDENCE",
                f"No output artifacts for {canonical_step_id}.", step.step_id,
            ))
        evidence_kind = EVIDENCE_KIND_BY_STEP.get(canonical_step_id)
        if evidence_kind is not None and evidence_reader.read_step_output_optional(
            run_step.run_step_id, evidence_kind,
        ) is None:
            blockers.append(ReadinessFinding(
                "blocker", "MISSING_REQUIRED_EVIDENCE",
                f"No {evidence_kind.value} evidence for {canonical_step_id}.", step.step_id,
            ))
    if not any(
        artifact.role == "oot"
        for run_step in uow.run_steps.get_for_run(run_id)
        for artifact in uow.artifacts.output_artifacts_for_run_step(run_step.run_step_id)
    ):
        warnings.append(ReadinessFinding("warning", "NO_OOT_SAMPLE", "No OOT dataset is available."))
    return ReportReadinessResult(blockers, warnings, run_id, datetime.now(UTC).isoformat())


__all__ = ["ReadinessFinding", "ReportReadinessResult", "check_report_readiness"]
