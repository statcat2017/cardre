"""Export a branch's immutable evidence as an atomic audit pack."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from cardre.application.reporting.contracts import ReportMode
from cardre.application.reporting.generate_report import GenerateReport, GenerateReportCommand
from cardre.domain.errors import CardreError

ROW_LEVEL_ARTIFACT_TYPES = {"dataset", "tabular"}


@dataclass(frozen=True)
class ExportAuditPackCommand:
    project_id: str
    plan_id: str
    branch_id: str
    project_root: str | Path | None = None
    export_path: str | Path | None = None
    comparison_snapshot_id: str | None = None
    include_row_level_data: bool = False
    include_report: bool = False
    report_mode: ReportMode = "branch"


@dataclass(frozen=True)
class ExportAuditPackResult:
    export_path: str
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
        tmp_dir = export_dir.parent / f".{export_dir.name}.tmp.{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=False)
        diagnostics: list[dict[str, Any]] = []
        warnings: list[str] = []
        try:
            with self._uow_factory.read_only(command.project_id) as uow:
                reader = self._artifact_reader_factory(command.project_id)
                file_count, partial = self._populate(uow, reader, tmp_dir, command, diagnostics)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        if partial:
            warnings.append("Export is partial: one or more referenced artifacts or reports were unavailable.")
        if not command.include_row_level_data:
            warnings.append("Row-level data excluded from export.")
        self._write_checksums(tmp_dir)
        file_count += 1
        self._replace_atomically(tmp_dir, export_dir)
        return ExportAuditPackResult(
            export_path=str(export_dir),
            export_id=str(uuid.uuid4()),
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
        branch = uow.branches.get_branch(command.branch_id)
        plan = uow.plans.get_plan(command.plan_id)
        if project is None:
            raise self._not_found("PROJECT_NOT_FOUND", command.project_id)
        if plan is None or plan.project_id != command.project_id:
            raise self._not_found("PLAN_NOT_FOUND", command.plan_id)
        if branch is None:
            raise self._not_found("BRANCH_NOT_FOUND", command.branch_id)
        if branch.get("project_id") != command.project_id or branch.get("plan_id") != command.plan_id:
            raise CardreError("Branch does not belong to the requested project and plan.", code="BRANCH_SCOPE_MISMATCH", context={})

        head_plan_version_id = str(branch.get("head_plan_version_id") or "")
        step_map = uow.branches.get_step_map(command.branch_id, head_plan_version_id) if head_plan_version_id else []
        version_steps = uow.plans.get_version_steps(head_plan_version_id) if head_plan_version_id else []
        run_id = uow.runs.get_latest_successful_id(head_plan_version_id, command.branch_id) if head_plan_version_id else None
        if run_id is None and head_plan_version_id:
            run_id = uow.runs.get_latest_successful_id(head_plan_version_id)

        self._write_json(export_dir / "project.json", project.to_dict())
        self._write_json(export_dir / "branch.json", branch)
        self._write_json(export_dir / "branch_step_map.json", step_map)
        self._write_json(export_dir / "plan_steps.json", [step.to_dict() for step in version_steps])
        file_count = 4
        run_steps: dict[str, dict[str, Any]] = {}
        runs: dict[str, dict[str, Any]] = {}
        evidence: list[dict[str, Any]] = []
        artifact_ids: set[str] = set()

        def add_run_step(run_step: Any, source: str) -> None:
            if run_step.run_step_id in run_steps:
                return
            run = uow.runs.get(run_step.run_id)
            if run is not None:
                runs[run.run_id] = self._run_to_dict(run)
            lineage = uow.artifacts.artifacts_for_run_step(run_step.run_step_id)
            input_ids = [artifact.artifact_id for direction, artifact in lineage if direction == "input"]
            output_ids = [artifact.artifact_id for direction, artifact in lineage if direction == "output"]
            edges = uow.evidence.get_edges_for_run_step(run_step.run_step_id)
            evidence_artifact_ids: list[str] = []
            for edge in edges:
                edge_artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                evidence_artifact_ids.extend(item.artifact_id for item in edge_artifacts)
                evidence.append({
                    "run_step_id": run_step.run_step_id,
                    "source": source,
                    "edge": asdict(edge),
                    "artifacts": [asdict(item) for item in edge_artifacts],
                })
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

        if run_id is not None:
            for run_step in uow.run_steps.get_for_run(run_id):
                add_run_step(run_step, "branch_run")
        for row in step_map:
            if not bool(row.get("is_shared_upstream")):
                continue
            source_branch_id = row.get("source_branch_id")
            source_branch = uow.branches.get_branch(str(source_branch_id)) if source_branch_id else None
            source_plan_version_id = str(source_branch.get("head_plan_version_id")) if source_branch else head_plan_version_id
            source_step_id = str(row.get("source_step_id") or row.get("step_id") or "")
            resolved = resolve_run_step_evidence(
                uow,
                source_plan_version_id,
                source_step_id,
                branch_id=str(source_branch_id) if source_branch_id else None,
                plan_id=command.plan_id,
            )
            if resolved is None:
                diagnostics.append({"code": "SHARED_EVIDENCE_NOT_FOUND", "step_id": source_step_id})
                continue
            add_run_step(resolved.run_step, "shared_upstream")

        self._write_json(export_dir / "runs.json", list(runs.values()))
        self._write_json(export_dir / "run_steps.json", list(run_steps.values()))
        self._write_json(export_dir / "evidence.json", evidence)
        file_count += 3

        snapshot = None
        if command.comparison_snapshot_id:
            snapshot = uow.comparisons.get_comparison_snapshot(command.comparison_snapshot_id)
            if snapshot is not None and snapshot.get("comparison_artifact_id"):
                artifact_ids.add(str(snapshot["comparison_artifact_id"]))
        champion = uow.champion.get_champion_assignment(command.plan_id, command.branch_id)
        if champion is not None and champion.get("comparison_artifact_id"):
            artifact_ids.add(str(champion["comparison_artifact_id"]))

        artifacts: list[dict[str, Any]] = []
        partial = False
        for artifact_id in sorted(artifact_ids):
            artifact = uow.artifacts.get(artifact_id)
            if artifact is None:
                diagnostics.append({"code": "ARTIFACT_NOT_FOUND", "artifact_id": artifact_id})
                partial = True
                continue
            if not command.include_row_level_data and artifact.artifact_type in ROW_LEVEL_ARTIFACT_TYPES:
                continue
            artifacts.append(artifact.to_dict())
            try:
                destination = export_dir / "artifacts" / f"{artifact.artifact_id}_{artifact.physical_hash}"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(reader.read_bytes(artifact))
                file_count += 1
            except OSError as exc:
                diagnostics.append({"code": "ARTIFACT_UNREADABLE", "artifact_id": artifact_id, "message": str(exc)})
                partial = True
        self._write_json(export_dir / "artifacts.json", artifacts)
        file_count += 1

        if snapshot is not None:
            self._write_json(export_dir / "comparison_snapshot.json", snapshot)
            file_count += 1
        if champion is not None:
            self._write_json(export_dir / "champion_assignment.json", champion)
            file_count += 1
        if command.include_report and run_id is not None:
            result = self._generate_report(GenerateReportCommand(
                project_id=command.project_id,
                run_id=run_id,
                target_branch_id=command.branch_id,
                report_mode=command.report_mode,
                output_dir=export_dir / "report",
            ))
            file_count += 2
            diagnostics.append({"code": "REPORT_GENERATED", "path": result.html_path})
        return file_count, partial

    def _resolve_export_dir(self, command: ExportAuditPackCommand) -> Path:
        if command.export_path is not None:
            return Path(command.export_path)
        root = Path(command.project_root) if command.project_root is not None else self._export_root_factory(command.project_id)
        return root / "exports" / f"audit_{command.branch_id}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _run_to_dict(run: Any) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "plan_version_id": run.plan_version_id,
            "branch_id": run.branch_id,
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
    def _replace_atomically(tmp_dir: Path, export_dir: Path) -> None:
        backup = None
        if export_dir.exists():
            backup = export_dir.parent / f".{export_dir.name}.backup.{uuid.uuid4().hex[:8]}"
            shutil.move(str(export_dir), str(backup))
        try:
            shutil.move(str(tmp_dir), str(export_dir))
        except BaseException:
            if backup is not None:
                shutil.move(str(backup), str(export_dir))
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)

    @staticmethod
    def _not_found(code: str, resource_id: str) -> CardreError:
        return CardreError(f"{code.replace('_', ' ').title()}: {resource_id}", code=code, context={})
