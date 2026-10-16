"""Read a registered HTML report through project and run scoped identity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.errors import CardreError, ErrorCode


@dataclass(frozen=True)
class ReportHtml:
    report_id: str
    run_id: str
    file_name: str
    content: bytes


class ReadReportHtml:
    """Read only a registered report belonging to the requested project/run."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        artifact_reader_factory: Callable[[str], ArtifactReader],
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader_factory = artifact_reader_factory

    def __call__(self, project_id: str, run_id: str, report_id: str) -> ReportHtml:
        with self._uow_factory.read_only(project_id) as uow:
            if uow.runs.get(run_id) is None:
                raise CardreError(
                    f"Run {run_id!r} not found.",
                    code=ErrorCode.RUN_NOT_FOUND,
                    context={"run_id": run_id},
                )
            report = next(
                (
                    item
                    for item in uow.reports.list_for_run(run_id)
                    if item.report_id == report_id and item.report_type == "report"
                ),
                None,
            )
            if report is None:
                raise _report_not_found(report_id, run_id)
            stored_path = Path(report.path)

        # Report paths come from project persistence, never from the request.
        # Resolve symlinks and enforce project containment before reading.
        if stored_path.is_absolute():
            raise _report_not_found(report_id, run_id)
        root = Path(self._artifact_reader_factory(project_id).root).resolve()
        try:
            path = (root / stored_path).resolve(strict=True)
            path.relative_to(root)
            if not path.is_file():
                raise _report_not_found(report_id, run_id)
            content = path.read_bytes()
        except (OSError, RuntimeError, ValueError):
            raise _report_not_found(report_id, run_id) from None

        return ReportHtml(
            report_id=report_id,
            run_id=run_id,
            file_name="model-development-report.html",
            content=content,
        )


def _report_not_found(report_id: str, run_id: str) -> CardreError:
    return CardreError(
        f"HTML report {report_id!r} was not found for run {run_id!r}.",
        code=ErrorCode.ARTIFACT_NOT_FOUND,
        context={"report_id": report_id, "run_id": run_id},
    )
