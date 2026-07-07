"""Selected branch export service — audit pack export.

Phase 5: export_service.py owns packaging; reporting/ owns report
collection/rendering.  Uses v2 store and repository APIs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    pass

from cardre.domain.errors import CardreError
from cardre.services.report_service import ReportGenerationService
from cardre.store import ProjectStore
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository
from cardre.store.project_repo import ProjectRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository

ROW_LEVEL_ARTIFACT_TYPES = {"dataset", "tabular"}


def export_branch_audit_pack(
    store: ProjectStore,
    project_id: str,
    plan_id: str,
    branch_id: str,
    export_path: str | None = None,
    comparison_id: str | None = None,
    comparison_snapshot_id: str | None = None,
    include_row_level_data: bool = False,
    include_report: bool = False,
    report_mode: str = "branch",
) -> dict[str, Any]:
    """Export selected branch evidence as an audit pack.

    Includes:
      - Project and branch metadata
      - Branch creation reason and lineage
      - Branch step map and plan version steps
      - Run IDs, run step IDs, artifact references
      - Hashes, params, warnings, errors
      - Technical manifest
      - Comparison snapshot (if provided)
      - Champion assignment (if branch is champion)
      - Phase 5 governance report (if include_report=True)

    Excludes row-level dataset artifacts unless include_row_level_data is True.
    Uses branch-scoped evidence lookup.
    """
    branch_repo = BranchRepository(store)
    branch = branch_repo.get_branch(branch_id)
    if branch is None:
        raise CardreError(
            f"BRANCH_NOT_FOUND: {branch_id}",
            code="BRANCH_NOT_FOUND",
            context={"branch_id": branch_id},
            status_code=404,
        )

    project_repo = ProjectRepository(store)
    project = project_repo.get(project_id)
    if project is None:
        raise CardreError(
            f"PROJECT_NOT_FOUND: {project_id}",
            code="PROJECT_NOT_FOUND",
            context={"project_id": project_id},
            status_code=404,
        )

    export_dir = Path(export_path) if export_path else store.root / "exports" / f"audit_{branch_id}_{uuid.uuid4().hex[:8]}"
    export_id = str(uuid.uuid4())

    tmp_dir = export_dir.parent / f".{export_dir.name}.tmp.{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    diagnostics: list[dict[str, Any]] = []
    warnings_list: list[str] = []
    file_count = 0
    partial = False

    try:
        file_count, partial = _populate_export(
            store, tmp_dir, project_id, plan_id, branch_id,
            comparison_snapshot_id, include_row_level_data, include_report,
            report_mode, diagnostics, warnings_list, branch, project,
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

    return {
        "export_path": str(export_dir),
        "export_id": export_id,
        "file_count": file_count,
        "warnings": warnings_list,
        "diagnostics": diagnostics,
        "partial": partial,
    }


def _populate_export(
    store: ProjectStore,
    export_dir: Path,
    project_id: str,
    plan_id: str,
    branch_id: str,
    comparison_snapshot_id: str | None,
    include_row_level_data: bool,
    include_report: bool,
    report_mode: str,
    diagnostics: list[dict[str, Any]],
    warnings_list: list[str],
    branch: dict[str, Any],
    project: dict[str, Any],
) -> tuple[int, bool]:
    partial = False
    file_count = 0
    branch_repo = BranchRepository(store)
    plan_repo = PlanRepository(store)
    run_repo = RunRepository(store)
    run_step_repo = RunStepRepository(store)
    artifact_repo_obj = ArtifactRepository(store)

    # 1. Project metadata
    project_info = {
        "project_id": project_id,
        "name": project.get("name", ""),
        "created_at": project.get("created_at", ""),
        "cardre_version": project.get("cardre_version", ""),
    }
    _write_json(export_dir / "project.json", project_info)
    file_count += 1

    # 2. Branch metadata
    branch_info = dict(branch) if isinstance(branch, dict) else branch
    (export_dir / "branch.json").write_text(json.dumps(branch_info, indent=2))
    file_count += 1

    # 3. Branch step map
    head_pv_id = branch.get("head_plan_version_id", "")
    step_map = branch_repo.get_step_map(branch_id, head_pv_id) if head_pv_id else []
    (export_dir / "branch_step_map.json").write_text(json.dumps(step_map, indent=2))
    file_count += 1

    # 4. Plan version steps
    steps = plan_repo.get_version_steps(head_pv_id) if head_pv_id else []
    steps_data = [s.to_dict() if hasattr(s, 'to_dict') else dict(s) for s in steps]  # type: ignore[call-overload]  # StepSpec always has to_dict; dict(s) fallback unreachable
    (export_dir / "plan_steps.json").write_text(json.dumps(steps_data, indent=2))
    file_count += 1

    # 5. Run evidence
    run_id = run_repo.get_latest_successful_id(head_pv_id, branch_id=branch_id) if head_pv_id else None
    if run_id is None and head_pv_id:
        run_id = run_repo.get_latest_successful_id(head_pv_id, branch_id=None)
    runs_data: list[dict[str, Any]] = []
    run_steps_data: list[dict[str, Any]] = []

    if run_id:
        run = run_repo.get(run_id)
        if run:
            runs_data.append(dict(run) if isinstance(run, dict) else run)
            for rs in run_step_repo.get_for_run(run_id):
                run_steps_data.append(_run_step_to_dict_v2(store, rs))

    # Shared upstream run steps
    from cardre.evidence_locator import EvidenceLocator
    locator = EvidenceLocator(store)
    for row in step_map:
        if row.get("is_shared_upstream"):
            step_id = row.get("step_id", "")
            # Use the Locator (ADR-0005 §3) for the branch→full→plan fallback.
            plan_id_val = branch.get("plan_id", "")
            resolved = locator.resolve(
                head_pv_id, step_id,
                branch_id=None, plan_id=plan_id_val or None,
            )
            if resolved is not None:
                run_steps_data.append(_run_step_to_dict_v2(store, resolved.run_step))

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
        art = artifact_repo_obj.get(aid)
        if art:
            if not include_row_level_data and art.artifact_type in ROW_LEVEL_ARTIFACT_TYPES:
                continue
            artifacts_list.append({
                "artifact_id": art.artifact_id,
                "artifact_type": art.artifact_type,
                "role": art.role,
                "path": art.path,
                "physical_hash": art.physical_hash,
                "logical_hash": art.logical_hash,
                "media_type": art.media_type,
                "created_at": art.created_at,
            })
            src = store.root / art.path
            if src.exists():
                dst = export_dir / "artifacts" / f"{art.artifact_id}_{src.name}"
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
                art = artifact_repo_obj.get(aid)
                if art:
                    src = store.root / art.path
                    if src.exists():
                        dst = export_dir / "manifest" / src.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        file_count += 1

    # 8. Comparison snapshot
    if comparison_snapshot_id:
        snap = branch_repo.get_comparison_snapshot(comparison_snapshot_id)
        if snap:
            snap_dict = dict(snap) if isinstance(snap, dict) else snap
            (export_dir / "comparison_snapshot.json").write_text(json.dumps(snap_dict, indent=2))
            file_count += 1
            comp_art_id = snap_dict.get("comparison_artifact_id", "")
            if comp_art_id:
                art = artifact_repo_obj.get(comp_art_id)
                if art:
                    src = store.root / art.path
                    if src.exists():
                        dst = export_dir / "comparison" / src.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        file_count += 1

    # 9. Champion assignment — check if branch has champion metadata
    champion_info = _get_champion_info(store, branch, branch_repo)
    if champion_info:
        (export_dir / "champion_assignment.json").write_text(json.dumps(champion_info, indent=2))
        file_count += 1

    # 10. Governance report
    if include_report:
        latest_run_id = run_repo.get_latest_successful_id(head_pv_id, branch_id=branch_id) if head_pv_id else None
        if latest_run_id is None and head_pv_id:
            latest_run_id = run_repo.get_latest_successful_id(head_pv_id, branch_id=None)
        if latest_run_id:
            try:
                svc = ReportGenerationService(store)
                readiness = svc.check_readiness(
                    project_id=project_id,
                    run_id=latest_run_id,
                    target_branch_id=branch_id,
                    report_mode=report_mode,
                )
                if readiness.ready:
                    result = svc.generate_and_write(
                        project_id=project_id,
                        run_id=latest_run_id,
                        target_branch_id=branch_id,
                        report_mode=report_mode,
                        report_dir=export_dir / "report",
                    )
                    bundle_data = result["bundle_data"]
                    file_count += 2

                    report_art_dir = export_dir / "report_artifacts"
                    report_art_dir.mkdir(parents=True, exist_ok=True)
                    file_count += _copy_report_artifacts(store, bundle_data, report_art_dir, include_row_level_data, artifact_repo_obj)

                    diagnostics.append({
                        "code": "REPORT_GENERATED",
                        "message": f"Phase 5 report generated for branch {branch_id}.",
                    })
                else:
                    warnings_list.append(f"Report skipped: {[str(b.code) for b in readiness.blockers]}")
            except CardreError as exc:
                diagnostics.append({
                    "code": "REPORT_FAILED",
                    "message": f"Report generation failed for branch {branch_id}: {exc}",
                    "context": {"branch_id": branch_id, "run_id": latest_run_id},
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
    if not include_row_level_data:
        warnings_list.append("Row-level data excluded from export.")

    return file_count, partial


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _copy_report_artifacts(
    store: ProjectStore,
    bundle: dict[str, Any],
    report_art_dir: Path,
    include_row_level_data: bool,
    artifact_repo: ArtifactRepository,
) -> int:
    artifacts = bundle.get("artifacts", [])
    count = 0
    for entry in artifacts:
        art_id = entry.get("artifact_id", "")
        art = artifact_repo.get(art_id)
        if art is None:
            continue
        if not include_row_level_data and art.artifact_type in ROW_LEVEL_ARTIFACT_TYPES:
            continue
        src = store.root / art.path
        if not src.exists():
            continue
        dst = report_art_dir / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
    return count


def _get_champion_info(
    store: ProjectStore,
    branch: dict[str, Any],
    branch_repo: BranchRepository,
) -> dict[str, Any] | None:
    """Check for champion assignment metadata on the branch."""
    try:
        champ = branch_repo.get_champion(branch.get("branch_id", ""))  # type: ignore[attr-defined]  # get_champion may not exist on all repo implementations; fallback to metadata check
        return cast("dict[str, Any] | None", champ)
    except (AttributeError, NotImplementedError):
        pass
    # Fallback: check metadata
    meta = branch.get("metadata", {}) or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    if meta.get("is_champion"):
        return {"branch_id": branch.get("branch_id", ""), "is_champion": True, "metadata": meta}
    return None


def _run_step_to_dict_v2(store: ProjectStore, rs: Any) -> dict[str, Any]:
    """Convert a v2 RunStep to a dict with resolved artifact IDs."""
    input_ids: list[str] = []
    output_ids: list[str] = []
    try:
        rows = store.execute(
            "SELECT artifact_id, direction FROM artifact_lineage WHERE run_step_id = ?",
            (rs.run_step_id,),
        ).fetchall()
        for r in rows:
            if r["direction"] == "input":
                input_ids.append(r["artifact_id"])
            else:
                output_ids.append(r["artifact_id"])
    except Exception as exc:
        raise CardreError(
            f"Could not resolve run-step artifact lineage for {rs.run_step_id}",
            code="RUN_STEP_LINEAGE_UNREADABLE",
            context={"run_step_id": rs.run_step_id},
        ) from exc
    return {
        "run_step_id": rs.run_step_id,
        "run_id": rs.run_id,
        "step_id": rs.step_id,
        "plan_version_id": rs.plan_version_id,
        "status": rs.status.value if hasattr(rs.status, 'value') else rs.status,
        "started_at": rs.started_at,
        "finished_at": rs.finished_at,
        "input_artifact_ids": input_ids,
        "output_artifact_ids": output_ids,
        "execution_fingerprint": rs.execution_fingerprint,
        "warnings": rs.warnings,
        "errors": rs.errors,
    }
