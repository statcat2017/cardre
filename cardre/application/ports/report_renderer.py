"""Report renderer port — renders a ReportBundle into an output file."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ReportRendererPort(Protocol):
    def render(self, bundle: dict[str, Any], output_dir: Path) -> Path: ...
