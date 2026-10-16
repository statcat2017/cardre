"""Export a plan's immutable evidence as an atomic audit pack."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from cardre.application.reporting.generate_report import GenerateReport, GenerateReportCommand
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, ErrorCode

ROW_LEVEL_ARTIFACT_TYPES = {"dataset", "tabular", "scored_dataset"}


@dataclass(frozen=True)
class ExportAuditPackCommand:
    project_id: str
    run_id: str
    plan_id: str | None = None
    project_root: str | Path | None = None
    export_path: str | Path | None = None
    include_row_level_data: bool = False
    include_report: bool = False


@dataclass(frozen=True)
class ExportAuditPackResult:
    export_path: str
    archive_path: str
    export_id: str
    file_count: int
    warnings: list[str]
    diagnostics: list[dict[str, Any]]
    partial: bool


class ExportAuditPack:
    """Create an audit pack from UoW metadata and immutable artifacts only."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        artifact_reader_factory: Callable[[str], ArtifactReader],
        export_root_factory: Callable[[str], Path],
        generate_report: GenerateReport,
    ) -> None:
        self._uow_factory = uow_factory
        self._artifact_reader_factory = artifact_reader_factory
        self._export_root_factory = export_root_factory
        self._generate_report = generate_report

    def __call__(self, command: ExportAuditPackCommand) -> ExportAuditPackResult:
        export_dir = self._resolve_export_dir(command)
        archive_path = Path(f"{export_dir}.zip")
        tmp_dir = export_dir.parent / f".{export_dir.name}.tmp.{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=False)
        diagnostics: list[dict[str, Any]] = []
        warnings: list[str] = []
        run_id = command.run_id
        try:
            with self._uow_factory.read_only(command.project_id) as uow:
                reader = self._artifact_reader_factory(command.project_id)
                _, partial = self._populate(uow, reader, tmp_dir, command, diagnostics)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        if partial:
            warnings.append("Export is partial: one or more referenced artifacts or reports were unavailable.")
        if not command.include_row_level_data:
            warnings.append("Row-level data excluded from export.")
        export_id = str(uuid.uuid4())
        self._write_json(
            tmp_dir / "audit_pack.json",
            {
                "schema_version": "cardre.audit_pack.v1",
                "export_id": export_id,
                "project_id": command.project_id,
                "run_id": command.run_id,
                "plan_id": (
                    json.loads((tmp_dir / "plan_version.json").read_text(encoding="utf-8")).get("plan_id")
                    if (tmp_dir / "plan_version.json").exists()
                    else command.plan_id
                ),
                "partial": partial,
                "warnings": warnings,
                "diagnostics": diagnostics,
                "row_level_data_included": command.include_row_level_data,
            },
        )
        self._write_checksums(tmp_dir)
        file_count = sum(1 for path in tmp_dir.rglob("*") if path.is_file())
        self._replace_atomically(tmp_dir, export_dir)
        try:
            self._write_archive(export_dir, archive_path)
        except BaseException:
            shutil.rmtree(export_dir, ignore_errors=True)
            raise
        try:
            with self._uow_factory.for_project(command.project_id) as uow:
                uow.exports.register(
                    export_id=export_id,
                    run_id=run_id,
                    export_type="audit_pack",
                    path=str(archive_path),
                    created_at=utc_now_iso(),
                    size_bytes=archive_path.stat().st_size,
                )
                uow.commit()
        except BaseException:
            shutil.rmtree(export_dir, ignore_errors=True)
            archive_path.unlink(missing_ok=True)
            raise
        return ExportAuditPackResult(
            export_path=str(export_dir),
            archive_path=str(archive_path),
            export_id=export_id,
            file_count=file_count,
            warnings=warnings,
            diagnostics=diagnostics,
            partial=partial,
        )

    def _populate(
        self,
        uow: UnitOfWork,
        reader: ArtifactReader,
        export_dir: Path,
        command: ExportAuditPackCommand,
        diagnostics: list[dict[str, Any]],
    ) -> tuple[int, bool]:
        project = uow.projects.get(command.project_id)
        if project is None:
            raise self._not_found(ErrorCode.PROJECT_NOT_FOUND, command.project_id)
        run = uow.runs.get(command.run_id)
        if run is None:
            raise self._not_found(ErrorCode.RUN_NOT_FOUND, command.run_id)
        if str(run.status) != "succeeded":
            raise CardreError(
                "Audit-pack exports require a successful run.",
                code=ErrorCode.EXPORT_RUN_NOT_FOUND,
                context={"run_id": command.run_id, "plan_id": command.plan_id},
            )

        plan_version_id = run.plan_version_id
        run_plan_id = uow.plans.get_plan_id_for_version(plan_version_id)
        plan_id = command.plan_id or run_plan_id
        plan = uow.plans.get_plan(plan_id) if plan_id else None
        if (
            plan is None
            or plan.project_id != command.project_id
            or plan_id != run_plan_id
        ):
            raise self._not_found(ErrorCode.PLAN_NOT_FOUND, plan_id or "")
        plan_version = uow.plans.get_version(plan_version_id)
        version_steps = uow.plans.get_version_steps(plan_version_id)

        self._write_json(export_dir / "project.json", project.to_dict())
        self._write_json(export_dir / "plan.json", plan.to_dict())
        partial = False
        file_count = 4
        if plan_version is not None:
            self._write_json(export_dir / "plan_version.json", plan_version.to_dict())
            file_count += 1
        else:
            diagnostics.append({"code": "PLAN_VERSION_NOT_FOUND", "plan_version_id": plan_version_id})
            partial = True
        self._write_json(export_dir / "run.json", self._run_to_dict(run))
        self._write_json(export_dir / "plan_steps.json", [step.to_dict() for step in version_steps])
        run_steps: dict[str, dict[str, Any]] = {}
        runs: dict[str, dict[str, Any]] = {}
        evidence: list[dict[str, Any]] = []
        evidence_edges: list[dict[str, Any]] = []
        evidence_artifacts: list[dict[str, Any]] = []
        artifact_ids: set[str] = set()

        def add_run_step(run_step: Any, source: str) -> None:
            if run_step.run_step_id in run_steps:
                return
            r = uow.runs.get(run_step.run_id)
            if r is not None:
                runs[r.run_id] = self._run_to_dict(r)
            lineage = uow.artifacts.artifacts_for_run_step(run_step.run_step_id)
            input_ids = [artifact.artifact_id for direction, artifact in lineage if direction == "input"]
            output_ids = [artifact.artifact_id for direction, artifact in lineage if direction == "output"]
            edges = uow.evidence.get_edges_for_run_step(run_step.run_step_id)
            evidence_artifact_ids: list[str] = []
            for edge in edges:
                if edge.is_stale:
                    continue
                edge_artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                evidence_artifact_ids.extend(item.artifact_id for item in edge_artifacts)
                evidence.append({
                    "run_step_id": run_step.run_step_id,
                    "source": source,
                    "edge": asdict(edge),
                    "artifacts": [asdict(item) for item in edge_artifacts],
                })
                evidence_edges.append(asdict(edge))
                evidence_artifacts.extend(asdict(item) for item in edge_artifacts)
                source_run_step = uow.run_steps.get(edge.source_run_step_id)
                if source_run_step is not None:
                    add_run_step(source_run_step, edge.source_label or "evidence")
            artifact_ids.update(input_ids)
            artifact_ids.update(output_ids)
            artifact_ids.update(evidence_artifact_ids)
            run_steps[run_step.run_step_id] = {
                "run_step_id": run_step.run_step_id,
                "run_id": run_step.run_id,
                "step_id": run_step.step_id,
                "plan_version_id": run_step.plan_version_id,
                "status": run_step.status.value,
                "started_at": run_step.started_at,
                "finished_at": run_step.finished_at,
                "execution_fingerprint": run_step.execution_fingerprint,
                "warnings": run_step.warnings,
                "errors": run_step.errors,
                "input_artifact_ids": input_ids,
                "output_artifact_ids": output_ids,
                "source": source,
            }

        for run_step in uow.run_steps.get_for_run(command.run_id):
            add_run_step(run_step, "run")

        self._write_json(export_dir / "runs.json", list(runs.values()))
        self._write_json(export_dir / "run_steps.json", list(run_steps.values()))
        self._write_json(export_dir / "evidence.json", evidence)
        self._write_json(export_dir / "evidence_edges.json", evidence_edges)
        self._write_json(export_dir / "evidence_artifacts.json", evidence_artifacts)
        file_count += 5

        root = getattr(reader, "root", None)
        if root is None:
            diagnostics.append({"code": "CANONICAL_MANIFEST_MISSING", "run_id": command.run_id})
            partial = True
        else:
            project_root = Path(root).resolve()
            manifest_path = project_root / "manifests" / "runs" / f"{command.run_id}.json"
            try:
                manifest_path = manifest_path.resolve(strict=True)
                manifest_path.relative_to(project_root)
                (export_dir / "canonical_manifest.json").write_bytes(manifest_path.read_bytes())
                file_count += 1
            except (OSError, RuntimeError, ValueError):
                diagnostics.append({"code": "CANONICAL_MANIFEST_MISSING", "run_id": command.run_id})
                partial = True

        artifacts: list[dict[str, Any]] = []
        for artifact_id in sorted(artifact_ids):
            artifact = uow.artifacts.get(artifact_id)
            if artifact is None:
                diagnostics.append({"code": "ARTIFACT_NOT_FOUND", "artifact_id": artifact_id})
                partial = True
                continue
            artifact_data = artifact.to_dict()
            if not command.include_row_level_data and artifact.artifact_type in ROW_LEVEL_ARTIFACT_TYPES:
                artifact_data["content_included"] = False
                artifact_data["content_path"] = None
                artifact_data["content_status"] = "excluded"
                artifacts.append(artifact_data)
                continue

            content_key = hashlib.sha256(
                f"{artifact.artifact_id}\0{artifact.physical_hash}".encode()
            ).hexdigest()
            content_path = f"artifacts/{content_key}"
            try:
                destination = export_dir / content_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(reader.read_bytes(artifact))
            except OSError as exc:
                diagnostics.append({"code": "ARTIFACT_UNREADABLE", "artifact_id": artifact_id, "message": str(exc)})
                partial = True
                artifact_data["content_included"] = False
                artifact_data["content_path"] = None
                artifact_data["content_status"] = "unavailable"
            else:
                file_count += 1
                artifact_data["content_included"] = True
                artifact_data["content_path"] = content_path
                artifact_data["content_status"] = "included"
            artifacts.append(artifact_data)
        self._write_json(export_dir / "artifacts.json", artifacts)
        file_count += 1

        if command.include_report:
            result = self._generate_report(GenerateReportCommand(
                project_id=command.project_id,
                run_id=command.run_id,
                output_dir=export_dir / "report",
            ))
            file_count += 2
            diagnostics.append({"code": "REPORT_GENERATED", "path": result.html_path})
        return file_count, partial

    def _resolve_export_dir(self, command: ExportAuditPackCommand) -> Path:
        if command.export_path is not None:
            return Path(command.export_path)
        root = Path(command.project_root) if command.project_root is not None else self._export_root_factory(command.project_id)
        return root / "exports" / f"audit_{command.run_id}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _run_to_dict(run: Any) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "plan_version_id": run.plan_version_id,
            "status": str(run.status),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")

    @staticmethod
    def _write_checksums(export_dir: Path) -> None:
        checksums = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(export_dir)}"
            for path in sorted(export_dir.rglob("*"))
            if path.is_file()
        ]
        (export_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    @staticmethod
    def _write_archive(export_dir: Path, archive_path: Path) -> None:
        if archive_path.exists() or archive_path.is_symlink():
            raise FileExistsError(f"Audit pack archive already exists: {archive_path.name}")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_archive = archive_path.parent / f".{archive_path.name}.tmp.{uuid.uuid4().hex[:8]}"
        try:
            with zipfile.ZipFile(
                temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as archive:
                for path in sorted(export_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(export_dir).as_posix())
            temporary_archive.replace(archive_path)
        except BaseException:
            temporary_archive.unlink(missing_ok=True)
            raise

    @staticmethod
    def _replace_atomically(tmp_dir: Path, export_dir: Path) -> None:
        if export_dir.exists() or export_dir.is_symlink():
            raise FileExistsError(f"Audit pack directory already exists: {export_dir.name}")
        tmp_dir.rename(export_dir)

    @staticmethod
    def _not_found(code: ErrorCode, resource_id: str) -> CardreError:
        return CardreError(f"{code.replace('_', ' ').title()}: {resource_id}", code=code, context={})
