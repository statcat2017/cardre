"""Report and export query use cases — project-scoped, run-correct reads.

These thin query use cases own the UoW lifecycle (open + close) and return
plain records the API mapper converts. Routes never touch the filesystem or
``uow._conn``.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    """List reports for a project (optionally restricted to one run)."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

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
        return [
            ReportItem(
                report_id=r.report_id, run_id=r.run_id, report_type=r.report_type,
                path=r.path, created_at=r.created_at,
            )
            for r in rows
        ]


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
