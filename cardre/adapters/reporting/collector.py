"""Port-native report collector."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.unit_of_work import UnitOfWork
from cardre.application.reporting.contracts import (
    EVIDENCE_KIND_BY_STEP,
    REQUIRED_STEPS_COLLECTOR,
    ReportMode,
    resolve_required_steps,
)
from cardre.application.reporting.schema import (
    ArtifactEntry,
    BranchInfo,
    DiagnosticEntry,
    Limitation,
    PathwayStep,
    ReportBundle,
)


@dataclass(frozen=True)
class CollectReportCommand:
    project_id: str
    run_id: str
    target_branch_id: str
    report_mode: ReportMode = "branch"


class ReportCollector:
    """Assemble immutable run evidence into a governance report bundle."""

    def __init__(self, evidence_reader: EvidenceReaderPort, artifact_reader: ArtifactReader) -> None:
        self._evidence_reader = evidence_reader
        self._artifact_reader = artifact_reader

    def collect(
        self,
        uow: UnitOfWork,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: ReportMode,
    ) -> ReportBundle:
        command = CollectReportCommand(project_id, run_id, target_branch_id, report_mode)
        bundle = ReportBundle(
            project_id=command.project_id,
            run_id=command.run_id,
            target_branch_id=command.target_branch_id,
            report_mode=command.report_mode,
            generated_at=datetime.now(UTC).isoformat(),
        )
        project = uow.projects.get(command.project_id)
        run = uow.runs.get(command.run_id)
        branch = uow.branches.get_branch(command.target_branch_id)
        if project is not None:
            bundle.summary.model_name = project.name
        if run is None:
            bundle.limitations = [Limitation(code="MISSING_RUN_MANIFEST", severity="blocker", message="Run not found.")]
            return bundle
        if branch is None:
            bundle.limitations = [Limitation(code="TARGET_BRANCH_NOT_FOUND", severity="blocker", message="Target branch not found.")]
            return bundle

        bundle.summary.target_branch_id = command.target_branch_id
        bundle.run_status.run_id = run.run_id
        bundle.run_status.status = str(run.status)
        bundle.run_status.started_at = run.started_at
        bundle.run_status.finished_at = run.finished_at
        bundle.run_status.diagnostics = [
            DiagnosticEntry(
                code=str(diagnostic.get("code", "UNKNOWN")),
                message=str(diagnostic.get("message", "")),
                severity=str(diagnostic.get("severity", "warning")),
                category=str(diagnostic.get("category", "")),
                created_at=str(diagnostic.get("created_at", "")),
            )
            for diagnostic in uow.runs.get_diagnostics(run.run_id)
        ]

        step_map = uow.branches.get_step_map(command.target_branch_id, run.plan_version_id)
        if not step_map and branch.get("head_plan_version_id"):
            step_map = uow.branches.get_step_map(command.target_branch_id, branch["head_plan_version_id"])
        resolved = resolve_required_steps(command.target_branch_id, REQUIRED_STEPS_COLLECTOR, step_map)
        plan_id = uow.plans.get_plan_id_for_version(run.plan_version_id)
        plan_steps = {step.step_id: step for step in uow.plans.get_version_steps(run.plan_version_id)}
        limitations: list[Limitation] = []
        requested_steps = {step.step_id: step for step in uow.run_steps.get_for_run(run.run_id)}
        report_steps = dict(requested_steps)
        for canonical_step_id, ref in resolved.items():
            run_step = requested_steps.get(ref.step_id)
            evidence = None
            if run_step is None:
                evidence = resolve_run_step_evidence(
                    uow, run.plan_version_id, ref.step_id,
                    branch_id=ref.resolved_branch_id, plan_id=plan_id,
                )
                run_step = evidence.run_step if evidence is not None else None
            if run_step is not None:
                report_steps[run_step.run_step_id] = run_step
                evidence_kind = EVIDENCE_KIND_BY_STEP.get(canonical_step_id)
                if evidence_kind is not None:
                    typed_evidence = self._evidence_reader.read_step_output_optional(
                        run_step.run_step_id, evidence_kind,
                    )
                    if typed_evidence is not None:
                        bundle.modelling_metadata[canonical_step_id] = self._to_json(typed_evidence)
            step = plan_steps.get(ref.step_id)
            bundle.pathway.steps.append(PathwayStep(
                canonical_step_id=canonical_step_id,
                step_id=ref.step_id,
                branch_id=ref.resolved_branch_id,
                step_type=step.node_type if step is not None else "",
                config_hash=step.params_hash if step is not None else "",
                status=run_step.status.value if run_step is not None else "missing",
                resolution=ref.resolution,
            ))
            if ref.resolution == "ancestor":
                limitations.append(Limitation(
                    code="INHERITED_BRANCH_EVIDENCE",
                    message=f"Step {canonical_step_id} is inherited from branch {ref.resolved_branch_id}.",
                ))

        bundle.branches.target_branch_id = command.target_branch_id
        bundle.branches.branches = [
            BranchInfo(
                branch_id=row["branch_id"],
                name=row.get("name", ""),
                parent_branch_id=row.get("base_branch_id"),
                is_target_branch=row["branch_id"] == command.target_branch_id,
                status=row.get("status", ""),
            )
            for row in uow.branches.list_branches(command.project_id, plan_id)
        ]
        champion = uow.champion.get_champion_assignment(plan_id) if plan_id else None
        if champion is not None:
            bundle.champion.assignment_id = champion.get("champion_assignment_id")
            bundle.champion.champion_branch_id = champion.get("champion_branch_id")
            bundle.champion.target_branch_is_champion = champion.get("champion_branch_id") == command.target_branch_id
            bundle.champion.champion_status = "assigned"

        seen_artifacts: set[str] = set()
        for run_step in report_steps.values():
            for _, artifact in uow.artifacts.artifacts_for_run_step(run_step.run_step_id):
                if artifact.artifact_id in seen_artifacts:
                    continue
                seen_artifacts.add(artifact.artifact_id)
                bundle.artifacts.append(ArtifactEntry(
                    artifact_id=artifact.artifact_id,
                    artifact_type=artifact.artifact_type,
                    role=artifact.role,
                    logical_hash=artifact.logical_hash,
                    physical_hash=artifact.physical_hash,
                    path=artifact.path,
                ))
                if not self._artifact_reader.resolve_path(artifact).exists():
                    limitations.append(Limitation(
                        code="ARTIFACT_NOT_FOUND",
                        message=f"Artifact {artifact.artifact_id} is not available in the artifact store.",
                    ))

        bundle.reproducibility.run_id = run.run_id
        bundle.limitations = limitations
        return bundle

    @staticmethod
    def _to_json(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return value


__all__ = ["CollectReportCommand", "ReportCollector"]
