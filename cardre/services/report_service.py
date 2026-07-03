"""Report generation service — consolidates the read-check-generate-write pipeline.

Both the sidecar routes and the export service need to:
  1. Resolve the latest run ID for a branch (with fallback)
  2. Check report readiness
  3. Generate the report bundle
  4. Write bundle.json and report.html to a directory

This service owns that sequence so that neither caller duplicates it.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from cardre.domain.errors import CardreError, Diagnostic
from cardre.readiness import check_report_readiness
from cardre.readiness.dto import ReadinessBlocker, ReportReadinessResult
from cardre.reporting.collector import generate_report_bundle
from cardre.reporting.renderer_html import write_html_report
from cardre.store import ProjectStore


class ReportGenerationError(CardreError):
    """Raised when report generation is blocked by readiness checks."""
    code = "REPORT_BLOCKED"
    status_code = 400

    def __init__(self, message: str, blockers: list[ReadinessBlocker]) -> None:
        self.blockers = blockers
        blocker_dicts = [b.to_dict() for b in blockers]
        super().__init__(
            message,
            code=self.code,
            context={"blockers": blocker_dicts},
            diagnostics=[
                Diagnostic(
                    code=str(b.code),
                    message=b.message,
                    source="report_readiness",
                    context={"step_id": b.step_id} if b.step_id else {},
                )
                for b in blockers
            ],
        )


class ReportGenerationService:
    """Owns the report generation pipeline: resolve, check, collect, render, write."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    def check_readiness(
        self,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: str = "branch",
    ) -> ReportReadinessResult:
        return check_report_readiness(
            store=self.store,
            project_id=project_id,
            run_id=run_id,
            target_branch_id=target_branch_id,
            report_mode=report_mode,
        )

    def generate_and_write(
        self,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: str = "branch",
        report_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Full pipeline: check readiness, generate bundle, write files.

        Args:
            project_id: The project ID.
            run_id: The run ID.
            target_branch_id: The branch to report on.
            report_mode: "branch" or "champion".
            report_dir: Directory to write report files into. Created if None.

        Returns:
            Dict with keys:
              - readiness: ReportReadinessResult
              - bundle: ReportBundle
              - bundle_path: Path to report_bundle.json (relative to report_dir)
              - html_path: Path to report.html (relative to report_dir)
              - report_dir: Path to the report directory

        Raises:
            ReportGenerationError if readiness is blocked.
        """
        readiness = self.check_readiness(
            project_id=project_id,
            run_id=run_id,
            target_branch_id=target_branch_id,
            report_mode=report_mode,
        )

        if not readiness.ready:
            raise ReportGenerationError(
                "Report generation blocked by readiness checks.",
                blockers=readiness.blockers,
            )

        bundle = generate_report_bundle(
            store=self.store,
            project_id=project_id,
            run_id=run_id,
            target_branch_id=target_branch_id,
            report_mode=report_mode,
        )

        # Write files
        if report_dir is None:
            report_dir = self.store.root / "exports" / "report"
        report_dir.mkdir(parents=True, exist_ok=True)

        bundle_data = bundle.model_dump(mode="json", by_alias=False)

        bundle_path = report_dir / "report_bundle.json"
        bundle_path.write_text(json.dumps(bundle_data, indent=2, sort_keys=True))

        html_path = report_dir / "report.html"
        write_html_report(html_path, bundle_data)

        return {
            "readiness": readiness,
            "bundle": bundle,
            "bundle_data": bundle_data,
            "bundle_path": str(bundle_path),
            "html_path": str(html_path),
            "report_dir": str(report_dir),
        }

    def generate_report(
        self,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: str = "branch",
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Convenience wrapper for generate_and_write that returns paths relative to store root."""
        if output_dir is None:
            report_id = uuid.uuid4().hex[:8]
            output_dir = self.store.root / "exports" / f"report_{report_id}"

        result = self.generate_and_write(
            project_id=project_id,
            run_id=run_id,
            target_branch_id=target_branch_id,
            report_mode=report_mode,
            report_dir=output_dir / "report",
        )

        def _rel_or_raise(path_str: str, label: str) -> str:
            try:
                return str(Path(path_str).relative_to(self.store.root))
            except ValueError:
                raise CardreError(
                    f"Report {label} path is outside the project directory.",
                    code="REPORT_PATH_OUTSIDE_PROJECT",
                    context={"path": path_str, "project_root": str(self.store.root)},
                ) from None

        bundle_rel = _rel_or_raise(result["bundle_path"], "bundle")
        html_rel = _rel_or_raise(result["html_path"], "HTML")
        export_rel = _rel_or_raise(result["report_dir"], "export")

        return {
            "readiness": result["readiness"],
            "bundle": result["bundle"],
            "bundle_data": result["bundle_data"],
            "bundle_path": bundle_rel,
            "html_path": html_rel,
            "export_path": export_rel,
            "report_dir": str(output_dir),
        }
