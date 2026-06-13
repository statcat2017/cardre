"""Selected branch export service — audit pack export."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from cardre.audit import utc_now_iso
from cardre.store import ProjectStore


def export_branch_audit_pack(
    store: ProjectStore,
    project_id: str,
    plan_id: str,
    branch_id: str,
    export_path: str | None = None,
    comparison_id: str | None = None,
    comparison_snapshot_id: str | None = None,
    include_row_level_data: bool = False,
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

    Excludes row-level data by default.
    """
    branch = store.get_branch(branch_id)
    if branch is None:
        raise ValueError(f"BRANCH_NOT_FOUND: {branch_id}")

    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"PROJECT_NOT_FOUND: {project_id}")

    export_dir = Path(export_path) if export_path else store.root / "exports" / f"audit_{branch_id}_{uuid.uuid4().hex[:8]}"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_id = str(uuid.uuid4())

    diagnostics: list[dict[str, str]] = []
    warnings: list[str] = []
    file_count = 0

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

    # 5. Run evidence
    run_id = store.get_latest_successful_run_id(branch["head_plan_version_id"])
    runs_data: list[dict] = []
    run_steps_data: list[dict] = []
    if run_id:
        run = store.get_run(run_id)
        if run:
            runs_data.append(dict(run))
            for rs in store.get_run_steps(run_id):
                run_steps_data.append({
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
                })

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
        art = store.get_artifact(aid)
        if art:
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
            # Copy artifact files
            src = store.artifact_path(art)
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
                    src = store.artifact_path(art)
                    if src.exists():
                        dst = export_dir / "manifest" / src.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        file_count += 1

    # 8. Comparison snapshot
    if comparison_snapshot_id:
        snap = store._connect().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (comparison_snapshot_id,),
        ).fetchone()
        if snap:
            snap_data = dict(snap)
            (export_dir / "comparison_snapshot.json").write_text(json.dumps(snap_data, indent=2))
            file_count += 1
            art = store.get_artifact(snap["comparison_artifact_id"])
            if art:
                src = store.artifact_path(art)
                if src.exists():
                    dst = export_dir / "comparison" / src.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    file_count += 1

    # 9. Champion assignment
    champ = store._connect().execute(
        "SELECT * FROM champion_assignments "
        "WHERE champion_branch_id = ? AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
        (branch_id,),
    ).fetchone()
    if champ:
        (export_dir / "champion_assignment.json").write_text(json.dumps(dict(champ), indent=2))
        file_count += 1

    if not include_row_level_data:
        warnings.append("Row-level data excluded from export.")

    return {
        "export_path": str(export_dir),
        "export_id": export_id,
        "file_count": file_count,
        "warnings": warnings,
        "diagnostics": diagnostics,
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
