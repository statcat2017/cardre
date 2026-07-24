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
from cardre.application.runs.execute_run import ExecuteRun
from cardre.application.runs.finalize_run import FinalizeRun
from cardre.application.runs.submit_run import SubmitRun
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings


@dataclass
class Container:
    settings: Settings
    project_registry: Any = None
    project_provisioner: Any = None
    uow_factory: Any = None
    node_catalogue: Any = None
    create_project: Any = None
    list_projects: Any = None
    get_project: Any = None
    generate_report: Any = None
    export_audit_pack: Any = None
    submit_run: Any = None
    execute_run: Any = None
    finalize_run: Any = None
    manifest_publisher_factory: Any = None
    submit_run_factory: Any = None
    execute_run_factory: Any = None


def build_container(settings: Settings) -> Container:
    registry = JsonProjectRegistry(settings.registry_path)
    provisioner = SqliteProjectProvisioner()
    uow_factory = SqliteUnitOfWorkFactory(registry)
    node_catalogue = build_default_catalogue(settings)

    def project_root(project_id: str) -> Path:
        root = registry.resolve_root(project_id)
        if root is None:
            from cardre.domain.errors import CardreError
            raise CardreError(f"Project {project_id!r} not found", code="PROJECT_NOT_FOUND", context={})
        return root

    def artifact_reader_factory(project_id: str) -> ArtifactReader:
        return FsArtifactStore(project_root(project_id))

    def artifact_store_factory(project_id: str) -> FsArtifactStore:
        return FsArtifactStore(project_root(project_id))

    def evidence_reader_factory(
        reader: ArtifactReader,
        artifacts: ArtifactRepoPort,
        run_steps: RunStepRepoPort,
    ) -> EvidenceReaderPort:
        return EvidenceReader(reader, artifacts, run_steps)

    def step_evidence_reader_factory(project_id: str) -> EvidenceReader:
        """Create an EvidenceReader backed by a read-only UoW.

        The UoW is attached as ``_evidence_uow`` on the reader so the
        StepRunner can close it after each step.
        """
        uow = uow_factory.for_root_readonly(project_root(project_id))
        reader = EvidenceReader(
            artifact_reader_factory(project_id),
            uow.artifacts,
            uow.run_steps,
        )
        reader._evidence_uow = uow  # type: ignore[attr-defined]
        return reader

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

    from cardre.application.execution.step_runner import StepRunner

    def step_runner_factory(project_id: str) -> StepRunner:
        return StepRunner(
            node_catalogue,
            lambda: artifact_store_factory(project_id),
            lambda: step_evidence_reader_factory(project_id),
        )

    def execute_run_factory(project_id: str) -> ExecuteRun:
        return ExecuteRun(
            lambda: uow_factory.for_project(project_id),
            node_catalogue,
            step_runner_factory(project_id),
            finalize_run_factory(project_id),
            lambda: artifact_store_factory(project_id),
        )

    from cardre.adapters.dispatch.sync_dispatcher import SyncRunDispatcher

    def submit_run_factory(project_id: str) -> SubmitRun:
        exec_run = execute_run_factory(project_id)
        dispatcher = SyncRunDispatcher(
            lambda cmd: exec_run(cmd),
        )
        return SubmitRun(
            lambda: uow_factory.for_project(project_id),
            dispatcher,
            exec_run,
            finalize_run_factory(project_id),
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
        node_catalogue=node_catalogue,
        create_project=CreateProject(provisioner, registry, uow_factory),
        list_projects=ListProjects(registry, uow_factory),
        get_project=GetProject(registry, uow_factory),
        generate_report=generate_report,
        export_audit_pack=export_audit_pack,
        finalize_run=finalize_run_factory,
        manifest_publisher_factory=manifest_publisher_factory,
        submit_run_factory=submit_run_factory,
        execute_run_factory=execute_run_factory,
    )
