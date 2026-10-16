"""Generate a report through read-only ports."""

from __future__ import annotations

import uuid
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
from cardre.application.reporting.readiness import check_report_readiness
from cardre.application.reporting.schema import Limitation, ReportBundle
from cardre.domain.errors import CardreError, ErrorCode


@dataclass(frozen=True)
class GenerateReportCommand:
    project_id: str
    run_id: str
    output_dir: str | Path | None = None


@dataclass(frozen=True)
class GenerateReportResult:
    report_id: str | None
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
        artifact_reader = self._artifact_reader_factory(command.project_id)
        generated_report_id = str(uuid.uuid4())
        if command.output_dir is not None:
            output_dir = Path(command.output_dir)
            if hasattr(artifact_reader, "root"):
                project_root = Path(artifact_reader.root).resolve()
                try:
                    output_dir.resolve().relative_to(project_root)
                except ValueError:
                    pass
                else:
                    output_dir = output_dir / generated_report_id
        else:
            # Keep generated reports beneath the project and give every run
            # of this use case an immutable version directory.
            output_dir = (
                Path(artifact_reader.root)
                / "reports"
                / command.run_id
                / generated_report_id
            )
        with self._uow_factory.read_only(command.project_id) as uow:
            evidence_reader = self._evidence_reader_factory(artifact_reader, uow.artifacts, uow.run_steps)
            collector = self._collector_factory(evidence_reader, artifact_reader)
            readiness = check_report_readiness(
                uow, evidence_reader, command.project_id, command.run_id,
            )
            if not readiness.ready:
                raise CardreError(
                    "Report generation is blocked by readiness checks.",
                    code=ErrorCode.REPORT_BLOCKED,
                    context={
                        "run_id": command.run_id,
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
        report_id = None
        if hasattr(artifact_reader, "root"):
            from cardre.domain.diagnostics import utc_now_iso
            root = Path(artifact_reader.root).resolve()
            try:
                html_rel = Path(html_path).resolve().relative_to(root)
            except ValueError:
                # Audit packs can be written to a user-selected external
                # destination. Such copies are not project reports and must
                # not be registered as retrievable project-scoped reports.
                pass
            else:
                report_id = generated_report_id
                with self._uow_factory.for_project(command.project_id) as uow:
                    uow.reports.register(
                        report_id=report_id, run_id=command.run_id,
                        report_type="report", path=str(html_rel), created_at=utc_now_iso(),
                        scope="run",
                    )
                    uow.commit()
        return GenerateReportResult(
            report_id=report_id,
            html_path=str(html_path),
            bundle_path=str(bundle_path),
            report_dir=str(output_dir),
            bundle=bundle,
        )
