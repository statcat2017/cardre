"""Generate a governance report through read-only ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.report_collector import ReportCollectorPort
from cardre.application.ports.report_renderer import ReportRendererPort
from cardre.application.ports.unit_of_work import (
    ArtifactRepoPort,
    RunStepRepoPort,
    UnitOfWorkFactory,
)
from cardre.application.reporting.contracts import ReportMode
from cardre.application.reporting.readiness import check_report_readiness
from cardre.application.reporting.schema import Limitation, ReportBundle
from cardre.domain.errors import CardreError, ErrorCode


@dataclass(frozen=True)
class GenerateReportCommand:
    project_id: str
    run_id: str
    target_branch_id: str
    report_mode: ReportMode = "branch"
    output_dir: str | Path | None = None


@dataclass(frozen=True)
class GenerateReportResult:
    html_path: str
    bundle_path: str
    report_dir: str
    bundle: ReportBundle


class GenerateReport:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        artifact_reader_factory: Callable[[str], ArtifactReader],
        evidence_reader_factory: Callable[[ArtifactReader, ArtifactRepoPort, RunStepRepoPort], EvidenceReaderPort],
        collector_factory: Callable[[EvidenceReaderPort, ArtifactReader], ReportCollectorPort],
        renderer: ReportRendererPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader_factory = artifact_reader_factory
        self._evidence_reader_factory = evidence_reader_factory
        self._collector_factory = collector_factory
        self._renderer = renderer

    def __call__(self, command: GenerateReportCommand) -> GenerateReportResult:
        # Default output location is project-scoped: the project root carries a
        # ``reports/<run_id>/`` directory. The artifact reader's root is the
        # canonical project root, so reports stay beneath the project.
        if command.output_dir is not None:
            output_dir = Path(command.output_dir)
        else:
            artifact_reader = self._artifact_reader_factory(command.project_id)
            output_dir = Path(artifact_reader.root) / "reports" / command.run_id
        artifact_reader = self._artifact_reader_factory(command.project_id)
        with self._uow_factory.read_only(command.project_id) as uow:
            evidence_reader = self._evidence_reader_factory(artifact_reader, uow.artifacts, uow.run_steps)
            collector = self._collector_factory(evidence_reader, artifact_reader)
            readiness = check_report_readiness(
                uow, evidence_reader, command.project_id, command.run_id,
                command.target_branch_id, command.report_mode,
            )
            if not readiness.ready:
                raise CardreError(
                    "Report generation is blocked by readiness checks.",
                    code=ErrorCode.REPORT_BLOCKED,
                    context={
                        "run_id": command.run_id,
                        "branch_id": command.target_branch_id,
                        "blockers": [
                            {"code": finding.code, "message": finding.message}
                            for finding in readiness.blockers
                        ],
                    },
                )
            bundle = collector.collect(
                uow,
                command.project_id,
                command.run_id,
                command.target_branch_id,
                command.report_mode,
            )
            blockers = [
                limitation for limitation in bundle.limitations
                if limitation.severity == "blocker"
            ]
            if blockers:
                raise CardreError(
                    "Report generation is blocked by collected evidence.",
                    code=ErrorCode.REPORT_BLOCKED,
                    context={
                        "run_id": command.run_id,
                        "branch_id": command.target_branch_id,
                        "blockers": [
                            {"code": limitation.code, "message": limitation.message}
                            for limitation in blockers
                        ],
                    },
                )
            bundle.limitations.extend(
                Limitation(
                    severity=finding.severity,
                    code=finding.code,
                    message=finding.message,
                )
                for finding in readiness.warnings
            )
        html_path = self._renderer.render(bundle, output_dir)
        bundle_path = output_dir / "report_bundle.json"
        bundle_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        # Register the report in the project persistence layer so the report
        # query use case can discover it project- and run-scoped. Only register
        # when the artifact reader exposes a project root (production wiring);
        # pure-port test doubles may not support write access.
        if hasattr(artifact_reader, "root"):
            import uuid

            from cardre.domain.diagnostics import utc_now_iso
            report_id = str(uuid.uuid4())
            root = Path(artifact_reader.root)
            html_rel = str(html_path.relative_to(root)) if str(html_path).startswith(str(root)) else str(html_path)
            with self._uow_factory.for_project(command.project_id) as uow:
                uow.reports.register(
                    report_id=report_id, run_id=command.run_id,
                    report_type="report", path=html_rel, created_at=utc_now_iso(),
                    scope="run",
                )
                uow.commit()
        return GenerateReportResult(
            html_path=str(html_path),
            bundle_path=str(bundle_path),
            report_dir=str(output_dir),
            bundle=bundle,
        )
