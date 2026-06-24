"""Selected branch export service — audit pack export.

Phase 5: extended to include governance report generation.
export_service.py owns packaging; reporting/ owns report collection/rendering.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from cardre.audit import utc_now_iso
from cardre.services.report_generation_service import ReportGenerationService
from cardre.store import ProjectStore

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
    branch = store.get_branch(branch_id)
    if branch is None:
        raise ValueError(f"BRANCH_NOT_FOUND: {branch_id}")

    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"PROJECT_NOT_FOUND: {project_id}")

    export_dir = Path(export_path) if export_path else store.root / "exports" / f"audit_{branch_id}_{uuid.uuid4().hex[:8]}"
    export_id = str(uuid.uuid4())

    # Write to a temp directory so a partial export never leaves a visible pack.
    # On success the temp dir is renamed atomically; on failure it is removed.
    tmp_dir = export_dir.parent / f".{export_dir.name}.tmp.{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    diagnostics: list[dict[str, str]] = []
    warnings: list[str] = []
    file_count = 0

    try:
        file_count = _populate_export(
            store, tmp_dir, project_id, plan_id, branch_id,
            comparison_snapshot_id, include_row_level_data, include_report,
            report_mode, diagnostics, warnings,
        )
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Atomic rename: finalise the export
    if export_dir.exists():
        shutil.rmtree(export_dir)
    shutil.move(str(tmp_dir), str(export_dir))

    return {
        "export_path": str(export_dir),
        "export_id": export_id,
        "file_count": file_count,
        "warnings": warnings,
        "diagnostics": diagnostics,
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
    diagnostics: list[dict[str, str]],
    warnings: list[str],
) -> int:
    """Write all export files into *export_dir*.

    Separated from the outer function so the caller can wrap it in a
    temp-directory + atomic-rename pattern.
    """
    file_count = 0
    branch = store.get_branch(branch_id)
    project = store.get_project(project_id)

    # 1. Project metadata
    project_info = {
        "project_id": project_id,
        "name": project["name"],
        "created_at": project["created_at"],
        "cardre_version": project["cardre_version"],
    }
    _write_json(export_dir / "project.json", project_info)
    file_count += 1

    # 2. Branch metadata
    branch_info = dict(branch)
    (export_dir / "branch.json").write_text(json.dumps(branch_info, indent=2))
    file_count += 1

    # 3. Branch step map
    step_map = store.get_branch_step_map(branch_id, branch["head_plan_version_id"])
    (export_dir / "branch_step_map.json").write_text(json.dumps(step_map, indent=2))
    file_count += 1

    # 4. Plan version steps
    steps = store.get_plan_version_steps(branch["head_plan_version_id"])
    steps_data = [s.to_dict() for s in steps]
    (export_dir / "plan_steps.json").write_text(json.dumps(steps_data, indent=2))
    file_count += 1

    # 5. Run evidence — branch-scoped lookup + shared-upstream lineage
    run_id = store.get_latest_successful_run_id(
        branch["head_plan_version_id"], branch_id=branch_id,
    )
    runs_data: list[dict] = []
    run_steps_data: list[dict] = []

    # Branch-owned run steps
    if run_id:
        run = store.get_run(run_id)
        if run:
            runs_data.append(dict(run))
            for rs in store.get_run_steps(run_id):
                run_steps_data.append(_run_step_to_dict(rs))

    # Shared upstream run-step evidence consumed by the branch
    step_map = store.get_branch_step_map(branch_id, branch["head_plan_version_id"])
    for row in step_map:
        if row["is_shared_upstream"]:
            step_id = row["step_id"]
            upstream_rs = store.get_latest_successful_run_step_for_step(
                branch["head_plan_version_id"], step_id, branch_id=None,
            )
            if upstream_rs is None:
                plan_run_id = store.get_latest_successful_run_id_for_plan(
                    branch["plan_id"],
                )
                if plan_run_id:
                    for prs in store.get_run_steps(plan_run_id):
                        if prs.step_id == step_id and prs.status == "succeeded":
                            upstream_rs = prs
                            break
            if upstream_rs is not None:
                run_steps_data.append(_run_step_to_dict(upstream_rs))

    (export_dir / "runs.json").write_text(json.dumps(runs_data, indent=2))
    file_count += 1
    (export_dir / "run_steps.json").write_text(json.dumps(run_steps_data, indent=2))
    file_count += 1

    # 6. Artifact references — filter row-level data unless explicitly requested
    artifact_ids: set[str] = set()
    for rs_data in run_steps_data:
        artifact_ids.update(rs_data.get("input_artifact_ids", []))
        artifact_ids.update(rs_data.get("output_artifact_ids", []))
    artifacts_list = []
    for aid in sorted(artifact_ids):
        art = store.get_artifact(aid)
        if art:
            # Skip row-level dataset artifacts unless explicitly requested
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
            # Copy non-row-level artifact files
            src = store.artifact_path(art)  # cardre-allow-artifact-read: artifact-byte-download
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
                art = store.get_artifact(aid)
                if art:
                    src = store.artifact_path(art)  # cardre-allow-artifact-read: artifact-byte-download
                    if src.exists():
                        dst = export_dir / "manifest" / src.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        file_count += 1

    # 8. Comparison snapshot
    if comparison_snapshot_id:
        snap = store.get_comparison_snapshot(comparison_snapshot_id)
        if snap:
            (export_dir / "comparison_snapshot.json").write_text(json.dumps(snap, indent=2))
            file_count += 1
            art = store.get_artifact(snap["comparison_artifact_id"])
            if art:
                src = store.artifact_path(art)  # cardre-allow-artifact-read: artifact-byte-download
                if src.exists():
                    dst = export_dir / "comparison" / src.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    file_count += 1

    # 9. Champion assignment
    champ = store.get_champion_assignment_by_branch(branch_id)
    if champ:
        (export_dir / "champion_assignment.json").write_text(json.dumps(champ, indent=2))
        file_count += 1

    # 10. Phase 5 governance report
    if include_report:
        latest_run_id = store.get_latest_successful_run_id(
            branch["head_plan_version_id"], branch_id=branch_id,
        )
        if latest_run_id is None:
            latest_run_id = store.get_latest_successful_run_id(
                branch["head_plan_version_id"], branch_id=None,
            )
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
                    file_count += 2  # bundle.json + report.html

                    # Supporting report artifacts
                    report_art_dir = export_dir / "report_artifacts"
                    report_art_dir.mkdir(parents=True, exist_ok=True)
                    file_count += _copy_report_artifacts(store, bundle_data, report_art_dir)

                    diagnostics.append({
                        "code": "REPORT_GENERATED",
                        "message": f"Phase 5 report generated for branch {branch_id}.",
                    })
                else:
                    warnings.append(f"Report skipped: {[b.code for b in readiness.blockers]}")
            except Exception as exc:
                diagnostics.append({
                    "code": "REPORT_FAILED",
                    "message": f"Report generation failed: {exc}",
                })

    # 11. Checksums for all exported files
    checksums: list[str] = []
    for fpath in sorted(export_dir.rglob("*"), key=lambda p: str(p.relative_to(export_dir))):
        if fpath.is_file():
            rel = str(fpath.relative_to(export_dir))
            digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
            checksums.append(f"{digest}  {rel}")
    (export_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n")
    file_count += 1

    if not include_row_level_data:
        warnings.append("Row-level data excluded from export.")

    return file_count


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _copy_report_artifacts(
    store: ProjectStore,
    bundle: dict,
    report_art_dir: Path,
) -> int:
    """Copy supporting artifacts referenced in the report bundle."""
    artifacts = bundle.get("artifacts", [])
    count = 0
    from cardre.audit import ArtifactRef
    for entry in artifacts:
        art_id = entry.get("artifact_id", "")
        art = store.get_artifact(art_id)
        if art is None:
            continue
        src = store.artifact_path(art)  # cardre-allow-artifact-read: artifact-byte-download
        if not src.exists():
            continue
        rel = Path(art.path)
        dst = report_art_dir / rel.parent.name / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
    return count


def _run_step_to_dict(rs) -> dict:
    from cardre.audit import RunStepRecord
    return {
        "run_step_id": rs.run_step_id,
        "run_id": rs.run_id,
        "step_id": rs.step_id,
        "plan_version_id": rs.plan_version_id,
        "status": rs.status,
        "started_at": rs.started_at,
        "finished_at": rs.finished_at,
        "input_artifact_ids": rs.input_artifact_ids,
        "output_artifact_ids": rs.output_artifact_ids,
        "execution_fingerprint": rs.execution_fingerprint,
        "warnings": rs.warnings,
        "errors": rs.errors,
    }
