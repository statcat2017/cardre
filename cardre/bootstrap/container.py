"""Composition root — wires adapters to ports and builds use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
from cardre.adapters.rendering.html_report import HtmlReportRenderer
from cardre.adapters.reporting.collector import ReportCollector
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.report_collector import ReportCollectorPort
from cardre.application.ports.unit_of_work import ArtifactRepoPort, RunStepRepoPort
from cardre.application.projects.create_project import CreateProject
from cardre.application.projects.get_project import GetProject
from cardre.application.projects.list_projects import ListProjects
from cardre.application.reporting.export_audit_pack import ExportAuditPack
from cardre.application.reporting.generate_report import GenerateReport
from cardre.application.runs.finalize_run import FinalizeRun
from cardre.bootstrap.settings import Settings


@dataclass
class Container:
    settings: Settings
    project_registry: Any = None
    project_provisioner: Any = None
    uow_factory: Any = None
    create_project: Any = None
    list_projects: Any = None
    get_project: Any = None
    generate_report: Any = None
    export_audit_pack: Any = None
    finalize_run: Any = None
    manifest_publisher_factory: Any = None


def build_container(settings: Settings) -> Container:
    registry = JsonProjectRegistry(settings.registry_path)
    provisioner = SqliteProjectProvisioner()
    uow_factory = SqliteUnitOfWorkFactory(registry)

    def project_root(project_id: str) -> Path:
        root = registry.resolve_root(project_id)
        if root is None:
            from cardre.domain.errors import CardreError
            raise CardreError(f"Project {project_id!r} not found", code="PROJECT_NOT_FOUND", context={})
        return root

    def artifact_reader_factory(project_id: str) -> ArtifactReader:
        return FsArtifactStore(project_root(project_id))

    def evidence_reader_factory(
        reader: ArtifactReader,
        artifacts: ArtifactRepoPort,
        run_steps: RunStepRepoPort,
    ) -> EvidenceReaderPort:
        return EvidenceReader(reader, artifacts, run_steps)

    def collector_factory(
        reader: EvidenceReaderPort,
        artifact_reader: ArtifactReader,
    ) -> ReportCollectorPort:
        return ReportCollector(reader, artifact_reader)

    def manifest_publisher_factory(project_id: str) -> FsManifestPublisher:
        return FsManifestPublisher(project_root(project_id))

    def finalize_run_factory(project_id: str) -> FinalizeRun:
        return FinalizeRun(
            lambda: uow_factory.for_project(project_id),
            manifest_publisher_factory(project_id),
        )

    renderer = HtmlReportRenderer()
    generate_report = GenerateReport(
        uow_factory,
        artifact_reader_factory,
        evidence_reader_factory,
        collector_factory,
        renderer,
    )
    export_audit_pack = ExportAuditPack(
        uow_factory,
        artifact_reader_factory,
        project_root,
        generate_report,
    )

    return Container(
        settings=settings,
        project_registry=registry,
        project_provisioner=provisioner,
        uow_factory=uow_factory,
        create_project=CreateProject(provisioner, registry, uow_factory),
        list_projects=ListProjects(registry, uow_factory),
        get_project=GetProject(registry, uow_factory),
        generate_report=generate_report,
        export_audit_pack=export_audit_pack,
        finalize_run=finalize_run_factory,
        manifest_publisher_factory=manifest_publisher_factory,
    )
