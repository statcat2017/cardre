"""ExportAuditPack — atomic export of branch evidence as an audit pack.

Ports ``cardre.services.export_service.export_branch_audit_pack`` to
use ports instead of ProjectStore.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.report_renderer import ReportRendererPort
from cardre.reporting.types import ReportMode

ROW_LEVEL_ARTIFACT_TYPES = {"dataset", "tabular"}


@dataclass
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


@dataclass
class ExportAuditPackResult:
    export_path: str
    export_id: str
    file_count: int
    warnings: list[str]
    diagnostics: list[dict[str, Any]]
    partial: bool


class ExportAuditPack:
    """Export selected branch evidence as an audit pack.

    Mirrors the logic of ``cardre.services.export_service.export_branch_audit_pack``
    but accepts ports instead of ProjectStore.
    """

    def __init__(
        self,
        store_factory: Callable[[], Any],
        renderer: ReportRendererPort,
    ) -> None:
        self._store_factory = store_factory
        self._renderer = renderer

    def __call__(self, command: ExportAuditPackCommand) -> ExportAuditPackResult:
        project_root = Path(command.project_root) if command.project_root else Path.cwd()

        branch = self._get_branch(command.branch_id)
        if branch is None:
            raise self._not_found("BRANCH_NOT_FOUND", f"Branch {command.branch_id!r} not found.")

        project = self._get_project(command.project_id)
        if project is None:
            raise self._not_found("PROJECT_NOT_FOUND", f"Project {command.project_id!r} not found.")

        export_dir = self._resolve_export_dir(project_root, command)
        export_id = str(uuid.uuid4())

        tmp_dir = export_dir.parent / f".{export_dir.name}.tmp.{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        diagnostics: list[dict[str, Any]] = []
        warnings_list: list[str] = []
        file_count = 0
        partial = False

        try:
            file_count, partial = self._populate_export(
                project_root, tmp_dir, command, branch, project,
                diagnostics, warnings_list,
            )
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        backup_dir = None
        if export_dir.exists():
            backup_dir = export_dir.parent / f".{export_dir.name}.backup.{uuid.uuid4().hex[:8]}"
            shutil.move(str(export_dir), str(backup_dir))
        try:
            shutil.move(str(tmp_dir), str(export_dir))
        except BaseException:
            if backup_dir is not None:
                shutil.rmtree(export_dir, ignore_errors=True)
                shutil.move(str(backup_dir), str(export_dir))
            raise
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)

        return ExportAuditPackResult(
            export_path=str(export_dir),
            export_id=export_id,
            file_count=file_count,
            warnings=warnings_list,
            diagnostics=diagnostics,
            partial=partial,
        )

    def _populate_export(
        self,
        project_root: Path,
        export_dir: Path,
        command: ExportAuditPackCommand,
        branch: Any,
        project: Any,
        diagnostics: list[dict[str, Any]],
        warnings_list: list[str],
    ) -> tuple[int, bool]:
        partial = False
        file_count = 0

        branch_dict = self._as_dict(branch)
        project_dict = self._as_dict(project)

        head_pv_id = branch_dict.get("head_plan_version_id", "")

        # 1. Project metadata
        project_info = {
            "project_id": command.project_id,
            "name": project_dict.get("name", ""),
            "created_at": project_dict.get("created_at", ""),
        }
        self._write_json(export_dir / "project.json", project_info)
        file_count += 1

        # 2. Branch metadata
        (export_dir / "branch.json").write_text(json.dumps(branch_dict, indent=2))
        file_count += 1

        # 3. Branch step map
        step_map = self._get_step_map(command.branch_id, head_pv_id)
        (export_dir / "branch_step_map.json").write_text(json.dumps(step_map, indent=2))
        file_count += 1

        # 4. Plan version steps
        steps = self._get_version_steps(head_pv_id)
        steps_data = [s.to_dict() if hasattr(s, 'to_dict') else self._as_dict(s) for s in steps]
        (export_dir / "plan_steps.json").write_text(json.dumps(steps_data, indent=2))
        file_count += 1

        # 5. Run evidence
        run_id = self._get_latest_run(head_pv_id, command.branch_id)
        runs_data: list[dict[str, Any]] = []
        run_steps_data: list[dict[str, Any]] = []

        if run_id:
            run = self._get_run(run_id)
            if run:
                runs_data.append(self._as_dict(run))
                for rs in self._get_run_steps(run_id):
                    run_steps_data.append(self._run_step_to_dict(project_root, rs))

        # Shared upstream run steps
        for row in step_map:
            if row.get("is_shared_upstream"):
                step_id = row.get("step_id", "")
                plan_id_val = branch_dict.get("plan_id", "")
                resolved = self._resolve_evidence(
                    head_pv_id, step_id, plan_id=plan_id_val or None,
                )
                if resolved is not None:
                    rs = getattr(resolved, "run_step", None) or resolved
                    run_steps_data.append(self._run_step_to_dict(project_root, rs))

        (export_dir / "runs.json").write_text(json.dumps(runs_data, indent=2))
        file_count += 1
        (export_dir / "run_steps.json").write_text(json.dumps(run_steps_data, indent=2))
        file_count += 1

        # 6. Artifact references
        artifact_ids: set[str] = set()
        for rs_data in run_steps_data:
            artifact_ids.update(rs_data.get("input_artifact_ids", []))
            artifact_ids.update(rs_data.get("output_artifact_ids", []))
        artifacts_list = []
        for aid in sorted(artifact_ids):
            art = self._get_artifact(aid)
            if art:
                if not command.include_row_level_data and getattr(art, "artifact_type", "") in ROW_LEVEL_ARTIFACT_TYPES:
                    continue
                art_dict = self._as_dict(art)
                artifacts_list.append({
                    "artifact_id": getattr(art, "artifact_id", aid),
                    "artifact_type": getattr(art, "artifact_type", ""),
                    "role": getattr(art, "role", ""),
                    "path": getattr(art, "path", ""),
                    "physical_hash": getattr(art, "physical_hash", ""),
                    "logical_hash": getattr(art, "logical_hash", ""),
                    "media_type": getattr(art, "media_type", ""),
                    "created_at": getattr(art, "created_at", ""),
                })
                art_path = getattr(art, "path", None) or art_dict.get("path", "")
                src = project_root / art_path
                if src.exists():
                    dst = export_dir / "artifacts" / f"{aid}_{src.name}"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    file_count += 1
            else:
                diagnostics.append({"code": "ARTIFACT_NOT_FOUND", "message": f"Artifact {aid} referenced but not found"})

        (export_dir / "artifacts.json").write_text(json.dumps(artifacts_list, indent=2))
        file_count += 1

        # 7. Technical manifest
        for rs_data in run_steps_data:
            fp = rs_data.get("execution_fingerprint", {})
            if fp.get("node_type") == "cardre.technical_manifest_export":
                for aid in rs_data.get("output_artifact_ids", []):
                    art = self._get_artifact(aid)
                    if art:
                        art_path = getattr(art, "path", None) or getattr(art, "get", lambda k: None)("path") or ""
                        src = project_root / str(art_path)
                        if src.exists():
                            dst = export_dir / "manifest" / src.name
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            file_count += 1

        # 8. Comparison snapshot
        if command.comparison_snapshot_id:
            snap = self._get_comparison_snapshot(command.comparison_snapshot_id)
            if snap:
                snap_dict = self._as_dict(snap)
                (export_dir / "comparison_snapshot.json").write_text(json.dumps(snap_dict, indent=2))
                file_count += 1
                comp_art_id = snap_dict.get("comparison_artifact_id", "")
                if comp_art_id:
                    art = self._get_artifact(comp_art_id)
                    if art:
                        art_path = getattr(art, "path", None) or getattr(art, "get", lambda k: None)("path") or ""
                        src = project_root / str(art_path)
                        if src.exists():
                            dst = export_dir / "comparison" / src.name
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            file_count += 1

        # 9. Champion assignment
        champion_info = self._get_champion_info(branch_dict, command.branch_id)
        if champion_info:
            (export_dir / "champion_assignment.json").write_text(json.dumps(champion_info, indent=2))
            file_count += 1

        # 10. Governance report
        if command.include_report:
            latest_run_id = self._get_latest_run(head_pv_id, command.branch_id)
            if latest_run_id:
                try:
                    result = self._generate_report(
                        project_root, command, latest_run_id, export_dir,
                    )
                    if result:
                        file_count += result.get("file_count", 2)
                        diagnostics.append({
                            "code": "REPORT_GENERATED",
                            "message": f"Phase 5 report generated for branch {command.branch_id}.",
                        })
                except Exception as exc:
                    diagnostics.append({
                        "code": "REPORT_FAILED",
                        "message": f"Report generation failed for branch {command.branch_id}: {exc}",
                        "context": {"branch_id": command.branch_id, "run_id": latest_run_id},
                    })
                    partial = True

        # 11. Checksums
        checksums: list[str] = []
        for fpath in sorted(export_dir.rglob("*"), key=lambda p: str(p.relative_to(export_dir))):
            if fpath.is_file():
                rel = str(fpath.relative_to(export_dir))
                digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
                checksums.append(f"{digest}  {rel}")
        (export_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n")
        file_count += 1

        if partial:
            warnings_list.append("Export is partial: one or more branch reports failed to generate.")
        if not command.include_row_level_data:
            warnings_list.append("Row-level data excluded from export.")

        return file_count, partial

    def _generate_report(
        self, project_root: Path, command: ExportAuditPackCommand,
        run_id: str, export_dir: Path,
    ) -> dict[str, Any]:
        from cardre.application.reporting.generate_report import (
            GenerateReport,
            GenerateReportCommand,
        )

        use_case = GenerateReport(
            store_factory=self._store_factory,
            renderer=self._renderer,
        )
        result = use_case(GenerateReportCommand(
            project_id=command.project_id,
            run_id=run_id,
            target_branch_id=command.branch_id,
            report_mode=command.report_mode,
            project_root=project_root,
            output_dir=export_dir / "report",
        ))

        return {"file_count": 1, "result": result}

    def _copy_report_artifacts(
        self, project_root: Path, bundle: dict[str, Any],
        report_art_dir: Path, include_row_level_data: bool,
    ) -> int:
        artifacts = bundle.get("artifacts", [])
        count = 0
        for entry in artifacts:
            art_id = entry.get("artifact_id", "")
            art = self._get_artifact(art_id)
            if art is None:
                continue
            if not include_row_level_data and getattr(art, "artifact_type", "") in ROW_LEVEL_ARTIFACT_TYPES:
                continue
            art_path = getattr(art, "path", None) or getattr(art, "get", lambda k: None)("path") or ""
            src = project_root / str(art_path)
            if not src.exists():
                continue
            dst = report_art_dir / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
        return count

    def _get_champion_info(self, branch_dict: dict[str, Any], branch_id: str) -> dict[str, Any] | None:
        meta = branch_dict.get("metadata", {}) or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        if meta.get("is_champion"):
            return {"branch_id": branch_id, "is_champion": True, "metadata": meta}
        return None

    def _store(self) -> Any:
        return self._store_factory()

    def _get_branch(self, branch_id: str) -> Any:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self._store()).get(branch_id)

    def _get_project(self, project_id: str) -> Any:
        from cardre.store.project_repo import ProjectRepository
        return ProjectRepository(self._store()).get(project_id)

    def _get_step_map(self, branch_id: str, head_pv_id: str) -> list[dict[str, Any]]:
        if not head_pv_id:
            return []
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self._store()).get_step_map(branch_id, head_pv_id)

    def _get_version_steps(self, head_pv_id: str) -> list[Any]:
        if not head_pv_id:
            return []
        from cardre.store.plan_repo import PlanRepository
        return PlanRepository(self._store()).get_version_steps(head_pv_id)

    def _get_latest_run(self, plan_version_id: str, branch_id: str) -> str | None:
        from cardre.store.run_repo import RunRepository
        repo = RunRepository(self._store())
        run_id = repo.get_latest_successful_id(plan_version_id, branch_id=branch_id)
        if run_id is None:
            run_id = repo.get_latest_successful_id(plan_version_id, branch_id=None)
        return run_id

    def _get_run(self, run_id: str) -> Any:
        from cardre.store.run_repo import RunRepository
        return RunRepository(self._store()).get(run_id)

    def _get_run_steps(self, run_id: str) -> list[Any]:
        from cardre.store.run_step_repo import RunStepRepository
        return RunStepRepository(self._store()).get_for_run(run_id)

    def _get_artifact(self, artifact_id: str) -> Any:
        from cardre.store.artifact_repo import ArtifactRepository
        return ArtifactRepository(self._store()).get(artifact_id)

    def _resolve_evidence(self, plan_version_id: str, step_id: str, plan_id: str | None = None) -> Any:
        return None  # Simplified: old EvidenceLocator path is out of scope

    def _get_comparison_snapshot(self, snapshot_id: str) -> Any:
        from cardre.store.comparison_repo import ComparisonRepository
        try:
            return ComparisonRepository(self._store()).get_comparison_snapshot(snapshot_id)
        except Exception:
            return None

    def _run_step_to_dict(self, project_root: Path, rs: Any) -> dict[str, Any]:
        from cardre.store.artifact_repo import ArtifactRepository
        store = self._store()
        repo = ArtifactRepository(store)
        input_ids: list[str] = []
        output_ids: list[str] = []
        for entry in repo.lineage_artifact_ids_for_run_step(
            getattr(rs, "run_step_id", ""),
        ):
            direction = entry.get("direction", "")
            if direction == "input":
                input_ids.append(entry.get("artifact_id", ""))
            else:
                output_ids.append(entry.get("artifact_id", ""))
        return {
            "run_step_id": getattr(rs, "run_step_id", ""),
            "run_id": getattr(rs, "run_id", ""),
            "step_id": getattr(rs, "step_id", ""),
            "plan_version_id": getattr(rs, "plan_version_id", ""),
            "status": getattr(rs, "status", ""),
            "started_at": getattr(rs, "started_at", ""),
            "finished_at": getattr(rs, "finished_at", ""),
            "input_artifact_ids": input_ids,
            "output_artifact_ids": output_ids,
            "execution_fingerprint": getattr(rs, "execution_fingerprint", {}),
            "warnings": getattr(rs, "warnings", []),
            "errors": getattr(rs, "errors", []),
        }

    def _resolve_export_dir(self, project_root: Path, command: ExportAuditPackCommand) -> Path:
        if command.export_path:
            return Path(command.export_path)
        branch_id = command.branch_id
        return project_root / "exports" / f"audit_{branch_id}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True))

    @staticmethod
    def _as_dict(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return {}

    @staticmethod
    def _not_found(code: str, message: str) -> Exception:
        from cardre.domain.errors import CardreError
        return CardreError(message, code=code, context={}, status_code=404)
