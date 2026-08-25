"""Report collection port."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cardre.application.ports.unit_of_work import UnitOfWork
    from cardre.application.reporting.schema import ReportBundle


@runtime_checkable
class ReportCollectorPort(Protocol):
    def collect(
        self,
        uow: UnitOfWork,
        project_id: str,
        run_id: str,
    ) -> ReportBundle: ...


__all__ = ["ReportCollectorPort"]
