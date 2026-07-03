"""Tests for the export_service — audit pack export.

Port from v1: validates that export_branch_audit_pack can produce
an audit bundle against the v2 store schema.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.services.export_service import export_branch_audit_pack
from cardre.store.db import ProjectStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


@pytest.fixture
def project_with_branch(store):
    """Create a project, plan, plan version, and branch with a completed run."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()

    # Project
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Export Test Project", now, "0.2.0"),
    )

    # Plan
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Export Test Plan", now),
    )

    # Plan version
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )

    # Branch
    branch_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, description, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, "
        " branch_point_step_id, branch_point_canonical_step_id, segment_filter_spec_json, "
        " created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'test-branch', NULL, 'feature', 'active', "
        " ?, ?, NULL, NULL, NULL, 'test reason', ?, ?)",
        (branch_id, project_id, plan_id, pv_id, pv_id, now, now),
    )

    # Step
    step_id = "import-data"
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, position, canonical_step_id) "
        "VALUES (?, ?, 'cardre.import_dataset', '1', 'transform', '{}', 'hash', 0, ?)",
        (step_id, pv_id, step_id),
    )

    # Run (with branch_id so scoped lookups find it)
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, branch_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, branch_id, now, now, now),
    )

    # Run step
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
        (rs_id, run_id, step_id, pv_id, now, now),
    )

    # Artifact
    art_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (art_id, "json", "output", f"artifacts/{art_id[:16]}-test.json", "phys123", "log456", "application/json", now),
    )

    # Artifact lineage
    store.execute(
        "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, rs_id, pv_id, step_id, art_id, now),
    )

    return store, project_id, plan_id, branch_id, pv_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_branch_audit_pack_minimal(project_with_branch):
    """Minimal export with branch metadata but no comparison or report."""
    store, project_id, plan_id, branch_id, pv_id = project_with_branch

    result = export_branch_audit_pack(
        store=store,
        project_id=project_id,
        plan_id=plan_id,
        branch_id=branch_id,
        include_report=False,
    )

    assert result["export_path"] is not None
    assert result["file_count"] > 0
    assert "warnings" in result
    assert "diagnostics" in result

    # Verify the export directory exists and has files
    export_dir = Path(result["export_path"])
    assert export_dir.exists()
    assert export_dir.is_dir()

    # Check expected files
    expected_files = {"project.json", "branch.json", "branch_step_map.json",
                      "plan_steps.json", "runs.json", "run_steps.json",
                      "artifacts.json", "checksums.sha256"}
    actual_files = {f.name for f in export_dir.iterdir() if f.is_file()}
    for ef in expected_files:
        assert ef in actual_files, f"Expected file {ef} missing from export"

    # Check project metadata
    project_data = json.loads((export_dir / "project.json").read_text())
    assert project_data["project_id"] == project_id
    assert project_data["name"] == "Export Test Project"

    # Check branch metadata
    branch_data = json.loads((export_dir / "branch.json").read_text())
    assert branch_data["branch_id"] == branch_id

    # Check artifacts
    artifacts_data = json.loads((export_dir / "artifacts.json").read_text())
    assert len(artifacts_data) > 0


def test_export_branch_audit_pack_branch_not_found(store):
    """Export raises error for nonexistent branch."""
    with pytest.raises(ValueError, match="BRANCH_NOT_FOUND"):
        export_branch_audit_pack(
            store=store,
            project_id="nonexistent",
            plan_id="nonexistent",
            branch_id="nonexistent",
        )


def test_export_with_comparison_snapshot(project_with_branch):
    """Export with comparison_snapshot_id."""
    store, project_id, plan_id, branch_id, pv_id = project_with_branch
    now = utc_now_iso()

    # Create a comparison + snapshot
    comparison_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO branch_comparisons (comparison_id, project_id, plan_id, baseline_branch_id, comparison_spec_json, created_at) "
        "VALUES (?, ?, ?, ?, '{}', ?)",
        (comparison_id, project_id, plan_id, branch_id, now),
    )

    # Create a comparison artifact
    comp_art_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (comp_art_id, "comparison", "comparison", f"artifacts/{comp_art_id[:16]}-comparison.json",
         "cmp123", "cmp456", "application/json", now),
    )

    snapshot_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO branch_comparison_snapshots "
        "(comparison_snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id, readiness_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, '{}', ?)",
        (snapshot_id, comparison_id, project_id, plan_id, comp_art_id, now),
    )

    result = export_branch_audit_pack(
        store=store,
        project_id=project_id,
        plan_id=plan_id,
        branch_id=branch_id,
        comparison_snapshot_id=snapshot_id,
        include_report=False,
    )

    assert result["export_path"] is not None
    assert result["file_count"] > 0

    export_dir = Path(result["export_path"])
    assert (export_dir / "comparison_snapshot.json").exists()
    snap_data = json.loads((export_dir / "comparison_snapshot.json").read_text())
    assert snap_data["comparison_snapshot_id"] == snapshot_id


def test_export_checksums(project_with_branch):
    """Export should produce a valid checksums file."""
    store, project_id, plan_id, branch_id, pv_id = project_with_branch

    result = export_branch_audit_pack(
        store=store,
        project_id=project_id,
        plan_id=plan_id,
        branch_id=branch_id,
        include_report=False,
    )

    export_dir = Path(result["export_path"])
    checksums_file = export_dir / "checksums.sha256"
    assert checksums_file.exists()

    content = checksums_file.read_text().strip()
    assert len(content) > 0
    lines = content.split("\n")
    for line in lines:
        # Each line: hash  filename
        parts = line.split("  ")
        assert len(parts) == 2, f"Invalid checksum line: {line}"
        assert len(parts[0]) == 64, f"Expected SHA256 hex, got {len(parts[0])} chars"
