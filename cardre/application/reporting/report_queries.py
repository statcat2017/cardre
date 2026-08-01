"""Report and export query use cases — project-scoped, run-correct reads.

These thin query use cases own the UoW lifecycle (open + close) and return
plain records the API mapper converts. Routes never touch the filesystem or
``uow._conn``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cardre.application.ports.unit_of_work import UnitOfWorkFactory


@dataclass(frozen=True)
class ReportItem:
    report_id: str
    run_id: str | None
    report_type: str
    path: str
    created_at: str


@dataclass(frozen=True)
class ExportItem:
    export_id: str
    run_id: str
    export_type: str
    path: str
    created_at: str
    size_bytes: int


class ListReports:
    """List reports for a project (optionally restricted to one run).

    Database-registered reports (from ``GenerateReport``) are combined with a
    synthesized entry for every published canonical run manifest, so finalized
    runs remain discoverable through the report listings (pre-rewrite
    behaviour listed ``manifest-*`` directories directly).
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        manifest_publisher_factory: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._manifest_publisher_factory = manifest_publisher_factory

    def __call__(self, project_id: str, run_id: str | None = None) -> list[ReportItem]:
        with self._uow_factory.read_only(project_id) as uow:
            if run_id is not None:
                if uow.runs.get(run_id) is None:
                    from cardre.domain.errors import CardreError, ErrorCode
                    raise CardreError(
                        f"Run {run_id!r} not found",
                        code=ErrorCode.RUN_NOT_FOUND,
                        context={"run_id": run_id},
                        status_code=404,
                    )
                rows = uow.reports.list_for_run(run_id)
            else:
                rows = uow.reports.list_for_project(project_id)

        items = [
            ReportItem(
                report_id=r.report_id, run_id=r.run_id, report_type=r.report_type,
                path=r.path, created_at=r.created_at,
            )
            for r in rows
        ]

        # Synthesize an entry per canonical manifest. Manifests are not DB rows,
        # so discovery scans the filesystem (baseline listed manifest-* dirs).
        if self._manifest_publisher_factory is not None:
            manifests = self._manifest_publisher_factory(project_id).list_manifests()
            for m in manifests:
                if run_id is not None and m["run_id"] != run_id:
                    continue
                items.append(ReportItem(
                    report_id=f"manifest-{m['run_id']}",
                    run_id=m["run_id"],
                    report_type="manifest",
                    path=m["path"],
                    created_at="",
                ))
        return items


class ListExports:
    """List exports for a project, optionally filtered by run_id."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def __call__(self, project_id: str, run_id: str | None = None) -> list[ExportItem]:
        with self._uow_factory.read_only(project_id) as uow:
            rows = uow.exports.list_for_project(project_id, run_id=run_id)
        return [
            ExportItem(
                export_id=e.export_id, run_id=e.run_id, export_type=e.export_type,
                path=e.path, created_at=e.created_at, size_bytes=e.size_bytes,
            )
            for e in rows
        ]


class GetRunManifest:
    """Retrieve the canonical run manifest for a run.

    The manifest is a canonical artifact published to the filesystem by
    ``FinalizeRun`` (not a DB row), so discovery goes through the manifest
    publisher adapter rather than the reports/exports tables.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        manifest_publisher_factory: Any,
    ) -> None:
        self._uow_factory = uow_factory
        self._manifest_publisher_factory = manifest_publisher_factory

    def __call__(self, project_id: str, run_id: str) -> dict[str, Any]:
        from cardre.domain.errors import CardreError, ErrorCode

        with self._uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
        if run is None:
            raise CardreError(
                f"Run {run_id!r} not found",
                code=ErrorCode.RUN_NOT_FOUND,
                context={"run_id": run_id},
                status_code=404,
            )
        manifest = self._manifest_publisher_factory(project_id).read(run_id)
        if manifest is None:
            raise CardreError(
                f"No manifest published for run {run_id!r}",
                code="CANONICAL_MANIFEST_MISSING",
                context={"run_id": run_id},
                status_code=404,
            )
        return manifest
