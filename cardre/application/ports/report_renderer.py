"""Report renderer port — renders a ReportBundle into an output file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cardre.application.reporting.schema import ReportBundle


@runtime_checkable
class ReportRendererPort(Protocol):
    def render(self, bundle: ReportBundle, output_dir: Path) -> Path: ...
