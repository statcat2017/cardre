"""Report and export query use cases — project-scoped, run-correct reads.

These thin query use cases own the UoW lifecycle (open + close) and return
plain records the API mapper converts. Routes never touch the filesystem or
``uow._conn``.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cardre.application.ports.manifest_publisher import ManifestPublisherFactoryPort
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
    artifact_id: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    partial: bool | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringExportFormat:
    export_type: str
    file_name: str
    media_type: str


SCORING_EXPORT_FORMATS = {
    "scorecard_table": ScoringExportFormat("scorecard_csv", "scorecard.csv", "text/csv"),
    "scoring_export_python": ScoringExportFormat("python_scorer", "scorecard.py", "text/x-python"),
    "scoring_export_sql": ScoringExportFormat("sql_scorer", "scorecard.sql", "application/sql"),
}


class ListReports:
    """List reports for a project (optionally restricted to one run).

    Database-registered reports (from ``GenerateReport``) are combined with a
    synthesized entry for every published canonical run manifest, so finalized
    runs remain discoverable through the report listings (pre-rewrite
    behaviour listed ``manifests/runs/`` files directly).
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        manifest_publisher_factory: ManifestPublisherFactoryPort,
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
        # so discovery scans the filesystem (baseline listed manifests/runs/ dirs).
        if self._manifest_publisher_factory is not None:
            manifests = self._manifest_publisher_factory(project_id).list_manifests()
            manifest_run_ids = [m["run_id"] for m in manifests]
            finished_at_by_run = self._finished_at_for_runs(project_id, manifest_run_ids)
            for m in manifests:
                if run_id is not None and m["run_id"] != run_id:
                    continue
                items.append(ReportItem(
                    report_id=f"manifest-{m['run_id']}",
                    run_id=m["run_id"],
                    report_type="manifest",
                    path=m["path"],
                    created_at=finished_at_by_run.get(m["run_id"], ""),
                ))
        return items

    def _finished_at_for_runs(
        self, project_id: str, run_ids: list[str],
    ) -> dict[str, str]:
        """Map run_id -> finished_at for manifest discovery.

        Manifests are published at finalization, so ``finished_at`` is the
        semantically correct creation timestamp. Runs that no longer resolve
        keep an empty string rather than fabricating a timestamp.
        """
        result: dict[str, str] = {}
        if not run_ids:
            return result
        with self._uow_factory.read_only(project_id) as uow:
            for run_id in run_ids:
                run = uow.runs.get(run_id)
                if run is not None and run.finished_at:
                    result[run_id] = run.finished_at
        return result


class ListExports:
    """List exports for a project, optionally filtered by run_id."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        project_root_factory: Callable[[str], Path] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._project_root_factory = project_root_factory

    def __call__(self, project_id: str, run_id: str | None = None) -> list[ExportItem]:
        with self._uow_factory.read_only(project_id) as uow:
            rows = uow.exports.list_for_project(project_id, run_id=run_id)
            scoring_exports: list[ExportItem] = []
            if run_id is not None:
                run = uow.runs.get(run_id)
                if run is not None and run.status == "succeeded":
                    for artifact_id in uow.artifacts.output_artifact_ids_for_run(run_id):
                        artifact = uow.artifacts.get(artifact_id)
                        if artifact is None:
                            continue
                        export_format = SCORING_EXPORT_FORMATS.get(artifact.artifact_type)
                        if export_format is None:
                            continue
                        scoring_exports.append(ExportItem(
                            export_id=artifact.artifact_id,
                            run_id=run_id,
                            export_type=export_format.export_type,
                            path=export_format.file_name,
                            created_at=artifact.created_at,
                            size_bytes=0,
                            artifact_id=artifact.artifact_id,
                            file_name=export_format.file_name,
                            media_type=export_format.media_type,
                        ))
        registered = []
        for export in rows:
            file_name = Path(export.path).name
            if export.export_type == "audit_pack":
                partial, warnings = self._audit_pack_status(project_id, export)
                registered.append(ExportItem(
                    export_id=export.export_id,
                    run_id=export.run_id,
                    export_type=export.export_type,
                    path=file_name,
                    created_at=export.created_at,
                    size_bytes=export.size_bytes,
                    file_name=file_name,
                    media_type="application/zip",
                    partial=partial,
                    warnings=warnings,
                ))
            else:
                registered.append(ExportItem(
                    export_id=export.export_id,
                    run_id=export.run_id,
                    export_type=export.export_type,
                    path=export.path,
                    created_at=export.created_at,
                    size_bytes=export.size_bytes,
                    file_name=file_name,
                ))
        return registered + scoring_exports

    def _audit_pack_status(self, project_id: str, export: Any) -> tuple[bool, list[str]]:
        unavailable = ["Audit pack status is unavailable; treat this archive as partial."]
        if self._project_root_factory is None:
            return True, unavailable
        root = Path(self._project_root_factory(project_id)).resolve()
        path = Path(export.path)
        if not path.is_absolute():
            path = root / path
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            exports_root = (root / "exports").resolve()
            exports_root.relative_to(root)
            relative_to_exports = resolved.relative_to(exports_root)
            if not relative_to_exports.parts:
                return True, unavailable
            if resolved.is_dir():
                metadata_path = resolved / "audit_pack.json"
                if metadata_path.is_symlink():
                    return True, unavailable
                metadata_path = metadata_path.resolve(strict=True)
                metadata_path.relative_to(resolved)
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            else:
                with zipfile.ZipFile(resolved) as archive:
                    metadata = json.loads(archive.read("audit_pack.json").decode("utf-8"))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return True, unavailable
        if not isinstance(metadata, dict):
            return True, unavailable
        if (
            metadata.get("schema_version") != "cardre.audit_pack.v1"
            or metadata.get("project_id") != project_id
            or metadata.get("run_id") != export.run_id
            or metadata.get("export_id") != export.export_id
        ):
            return True, unavailable
        warnings = metadata.get("warnings")
        if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            return True, unavailable
        return bool(metadata.get("partial", True)), warnings


class GetRunManifest:
    """Retrieve the canonical run manifest for a run.

    The manifest is a canonical artifact published to the filesystem by
    ``FinalizeRun`` (not a DB row), so discovery goes through the manifest
    publisher adapter rather than the reports/exports tables.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        manifest_publisher_factory: ManifestPublisherFactoryPort,
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
            )
        manifest = self._manifest_publisher_factory(project_id).read(run_id)
        if manifest is None:
            raise CardreError(
                f"No manifest published for run {run_id!r}",
                code=ErrorCode.CANONICAL_MANIFEST_MISSING,
                context={"run_id": run_id},
            )
        return manifest
