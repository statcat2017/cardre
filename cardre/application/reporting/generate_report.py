"""GenerateReport — collector → renderer pipeline using ProjectStore."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.report_renderer import ReportRendererPort


@dataclass
class GenerateReportCommand:
    project_id: str
    run_id: str
    target_branch_id: str
    report_mode: str = "branch"
    project_root: str | Path | None = None
    output_dir: str | Path | None = None


@dataclass
class GenerateReportResult:
    html_path: str
    report_dir: str


class GenerateReport:
    def __init__(
        self,
        store_factory: Callable[[], Any],
        renderer: ReportRendererPort,
    ) -> None:
        self._store_factory = store_factory
        self._renderer = renderer

    def __call__(self, command: GenerateReportCommand) -> GenerateReportResult:
        store = self._store_factory()
        output_dir = Path(command.output_dir or "/tmp")

        from cardre.reporting.collector import generate_report_bundle

        bundle = generate_report_bundle(
            store=store,
            project_id=command.project_id,
            run_id=command.run_id,
            target_branch_id=command.target_branch_id,
            report_mode=command.report_mode,
        )

        html_path = self._renderer.render(
            bundle.model_dump(mode="json"),
            output_dir,
        )

        return GenerateReportResult(
            html_path=str(html_path),
            report_dir=str(output_dir),
        )
