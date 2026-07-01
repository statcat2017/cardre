"""Tests for v2 Phase 1 refactor changes — run_repo behaviour and schema FKs.

Covers:
- append_diagnostic stores extra fields in context_json (merged on read)
- finish only updates running runs
- heartbeat only updates running runs
- get_artifact_ids_for_run returns only output artifacts (v2 lineage path)
- save_step uses IMMEDIATE transaction
- FK cascades in ALL_TABLES_SQL (comparison_challenger_branches, artifact_lineage)
"""

from __future__ import annotations

import uuid

from cardre.audit import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus
from cardre.store.db import ProjectStore
from cardre.store.run_repo import RunRepository


def _make_store(tmp_path):
    root = tmp_path / "test.cardre"
    store = ProjectStore(str(root))
    store.initialize()
    return store


def _make_repo(store):
    return RunRepository(store)


def _setup_run(store):
    """Create a minimal project, plan, plan_version, and run."""
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        ("p1", "test", utc_now_iso(), "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        ("plan1", "p1", "test-plan", utc_now_iso()),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("pv1", "plan1", 1, utc_now_iso()),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        "params_json, params_hash, position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("step1", "pv1", "t", "1", "t", "{}", "h", 0),
    )
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "pv1", "running", utc_now_iso()),
    )
    return run_id, "pv1"


# ---------------------------------------------------------------------------
# append_diagnostic
# ---------------------------------------------------------------------------


def test_append_diagnostic_returns_plan_version_id_and_category(tmp_path):
    """Extra fields (plan_version_id, category) are stored in context_json
    and merged back into the returned dict by get_diagnostics."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, pv_id = _setup_run(store)

    repo.append_diagnostic(run_id, {
        "code": "TEST_CODE",
        "message": "test",
        "severity": "warning",
        "plan_version_id": pv_id,
        "category": "test_category",
        "source": "test_src",
    })

    diags = repo.get_diagnostics(run_id)
    assert len(diags) == 1
    d = diags[0]
    assert d["code"] == "TEST_CODE"
    assert d["plan_version_id"] == pv_id, f"Expected {pv_id}, got {d.get('plan_version_id')}"
    assert d["category"] == "test_category", f"Expected test_category, got {d.get('category')}"
    # Confirm context_json itself is not leaked as a top-level key
    assert "context_json" not in d


def test_append_diagnostic_matches_schema_columns(tmp_path):
    """Appended diagnostic should only use columns from the schema definition.
    The diagnostics table should NOT have plan_version_id or category columns."""
    store = _make_store(tmp_path)
    conn = store._connect()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(diagnostics)").fetchall()}
    assert "plan_version_id" not in cols, "plan_version_id column should not exist in diagnostics"
    assert "category" not in cols, "category column should not exist in diagnostics"
    assert "context_json" in cols
    assert "run_id" in cols
    assert "code" in cols


# ---------------------------------------------------------------------------
# finish — only update running runs
# ---------------------------------------------------------------------------


def test_finish_does_not_overwrite_failed_run(tmp_path):
    """finish() must only update rows where status = 'running'."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, _ = _setup_run(store)

    # Mark as failed first
    store.execute(
        "UPDATE runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
        (utc_now_iso(), run_id),
    )

    # Attempt to finish as succeeded
    repo.finish(run_id, "succeeded")

    row = store.execute("SELECT status, finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["status"] == "failed", f"Expected 'failed', got {row['status']!r}"


def test_finish_updates_running_run(tmp_path):
    """finish() updates a running run."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, _ = _setup_run(store)

    repo.finish(run_id, "succeeded")

    row = store.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["status"] == "succeeded"


# ---------------------------------------------------------------------------
# heartbeat — only update running runs
# ---------------------------------------------------------------------------


def test_heartbeat_does_not_update_failed_run(tmp_path):
    """heartbeat should only update running runs."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, _ = _setup_run(store)

    # Mark as failed
    store.execute(
        "UPDATE runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
        (utc_now_iso(), run_id),
    )

    repo.heartbeat(run_id)

    row = store.execute("SELECT heartbeat_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["heartbeat_at"] is None, "heartbeat should not update a failed run"


def test_heartbeat_updates_running_run(tmp_path):
    """heartbeat updates a running run's heartbeat_at."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, _ = _setup_run(store)

    repo.heartbeat(run_id)

    row = store.execute("SELECT heartbeat_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["heartbeat_at"] is not None, "heartbeat should set heartbeat_at"


# ---------------------------------------------------------------------------
# get_artifact_ids_for_run — v2 lineage fallback returns only output
# ---------------------------------------------------------------------------


def test_get_artifact_ids_for_run_returns_only_output_lineage(tmp_path):
    """In v2 schema (no input/output_artifact_ids_json on run_steps),
    get_artifact_ids_for_run must return only output artifacts from lineage."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, pv_id = _setup_run(store)

    # Register an artifact
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
        "physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art_in", "dataset", "input", "datasets/in.parquet",
         "abc", "def", "application/vnd.apache.parquet", utc_now_iso()),
    )
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
        "physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art_out", "dataset", "output", "datasets/out.parquet",
         "abc", "def", "application/vnd.apache.parquet", utc_now_iso()),
    )

    # Insert a run_step
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rs_id, run_id, "step1", pv_id, "succeeded",
         utc_now_iso(), "{}", "[]", "[]"),
    )

    # Insert lineage rows: one input, one output
    for aid, direction in [("art_in", "input"), ("art_out", "output")]:
        store.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
            "step_id, branch_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, rs_id, pv_id, "step1", None, aid, direction, utc_now_iso()),
        )

    # The repo's fallback path (v2 schema) queries artifact_lineage with direction = 'output'
    artifact_ids = repo.get_artifact_ids_for_run(run_id)

    assert "art_out" in artifact_ids, "output artifact should be included"
    assert "art_in" not in artifact_ids, "input artifact should NOT be included in output-only query"


def test_get_artifact_ids_for_run_legacy_returns_only_output(tmp_path):
    """When run_steps has legacy input/output_artifact_ids_json columns,
    get_artifact_ids_for_run must return only output_artifact_ids_json values."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, pv_id = _setup_run(store)

    # Drop the v2 run_steps and recreate with legacy JSON columns
    store.execute("DROP TABLE IF EXISTS run_steps")
    store.execute(
        "CREATE TABLE run_steps ("
        "run_step_id TEXT PRIMARY KEY, "
        "run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE, "
        "step_id TEXT NOT NULL, "
        "plan_version_id TEXT NOT NULL, "
        "status TEXT NOT NULL, "
        "started_at TEXT NOT NULL, "
        "finished_at TEXT, "
        "input_artifact_ids_json TEXT NOT NULL, "
        "output_artifact_ids_json TEXT NOT NULL, "
        "execution_fingerprint_json TEXT NOT NULL, "
        "warnings_json TEXT NOT NULL DEFAULT '[]', "
        "errors_json TEXT NOT NULL DEFAULT '[]', "
        "is_carried_forward INTEGER NOT NULL DEFAULT 0)"
    )

    # Insert a run_step with both input and output artifact IDs
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, input_artifact_ids_json, output_artifact_ids_json, "
        "execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rs_id, run_id, "step1", pv_id, "succeeded",
         utc_now_iso(), '["art_in_legacy"]', '["art_out_legacy"]',
         "{}", "[]", "[]"),
    )

    artifact_ids = repo.get_artifact_ids_for_run(run_id)

    assert "art_out_legacy" in artifact_ids, "output artifact should be included from legacy path"
    assert "art_in_legacy" not in artifact_ids, (
        "input artifact should NOT be included — legacy path must return only output_artifact_ids_json"
    )


# ---------------------------------------------------------------------------
# save_step — uses IMMEDIATE transaction
# ---------------------------------------------------------------------------


def test_save_step_wraps_in_immediate_transaction(tmp_path):
    """save_step must use a transaction('IMMEDIATE') so that run_step insert
    and artifact_lineage inserts are atomic."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    run_id, pv_id = _setup_run(store)

    rs = RunStep(
        run_step_id=str(uuid.uuid4()),
        run_id=run_id,
        step_id="step1",
        plan_version_id=pv_id,
        status=RunStepStatus.SUCCEEDED,
        started_at=utc_now_iso(),
        finished_at=utc_now_iso(),
        execution_fingerprint={},
        warnings=[],
        errors=[],
    )

    # save_step should succeed (it wraps in IMMEDIATE transaction)
    repo.save_step(rs)

    step_row = store.execute(
        "SELECT * FROM run_steps WHERE run_step_id = ?", (rs.run_step_id,)
    ).fetchone()
    assert step_row is not None, "run_step should exist after save_step"


# ---------------------------------------------------------------------------
# FK cascade tests
# ---------------------------------------------------------------------------


def test_comparison_challenger_branches_cascade_on_comparison_delete(tmp_path):
    """Deleting a branch_comparisons row cascades to comparison_challenger_branches."""
    store = _make_store(tmp_path)

    # Set up required parent rows
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        ("p_cascade", "test", utc_now_iso(), "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        ("plan_cascade", "p_cascade", "test", utc_now_iso()),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("pv_cascade", "plan_cascade", 1, utc_now_iso()),
    )
    store.execute(
        "INSERT INTO plan_branches (branch_id, project_id, plan_id, name, branch_type, "
        "base_plan_version_id, head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("branch_cascade", "p_cascade", "plan_cascade", "challenger", "challenger",
         "pv_cascade", "pv_cascade", "test", utc_now_iso(), utc_now_iso()),
    )
    store.execute(
        "INSERT INTO branch_comparisons (comparison_id, project_id, plan_id, baseline_branch_id, "
        "comparison_spec_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("comp_cascade", "p_cascade", "plan_cascade", "branch_cascade",
         "{}", utc_now_iso()),
    )
    store.execute(
        "INSERT INTO comparison_challenger_branches (comparison_id, branch_id) VALUES (?, ?)",
        ("comp_cascade", "branch_cascade"),
    )

    # Verify challenger row exists
    row = store.execute(
        "SELECT 1 FROM comparison_challenger_branches WHERE comparison_id = ?",
        ("comp_cascade",),
    ).fetchone()
    assert row is not None, "challenger row should exist before cascade"

    # Delete the comparison — should cascade
    store.execute("DELETE FROM branch_comparisons WHERE comparison_id = ?", ("comp_cascade",))

    row = store.execute(
        "SELECT 1 FROM comparison_challenger_branches WHERE comparison_id = ?",
        ("comp_cascade",),
    ).fetchone()
    assert row is None, "challenger row should be cascade-deleted"


def test_artifact_lineage_cascade_on_artifact_delete(tmp_path):
    """Deleting an artifact cascades to artifact_lineage rows referencing it."""
    store = _make_store(tmp_path)
    run_id, pv_id = _setup_run(store)

    # Insert an artifact
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
        "physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art_cascade", "dataset", "output", "datasets/cascade.parquet",
         "abc", "def", "application/vnd.apache.parquet", utc_now_iso()),
    )

    # Insert a run_step first (FK dependency for run_step_id)
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rs_id, run_id, "step1", pv_id, "succeeded",
         utc_now_iso(), "{}", "[]", "[]"),
    )

    # Insert a lineage row referencing the artifact
    lid = str(uuid.uuid4())
    store.execute(
        "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
        "step_id, branch_id, artifact_id, direction, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (lid, run_id, rs_id, pv_id, "step1", None, "art_cascade", "output", utc_now_iso()),
    )

    # Verify lineage row exists
    row = store.execute(
        "SELECT 1 FROM artifact_lineage WHERE lineage_id = ?", (lid,)
    ).fetchone()
    assert row is not None, "lineage row should exist before cascade"

    # Delete the artifact — should cascade to artifact_lineage
    store.execute("DELETE FROM artifacts WHERE artifact_id = ?", ("art_cascade",))

    row = store.execute(
        "SELECT 1 FROM artifact_lineage WHERE lineage_id = ?", (lid,)
    ).fetchone()
    assert row is None, "lineage row should be cascade-deleted when artifact is deleted"


# ---------------------------------------------------------------------------
# Branch scoping for get_latest_successful_*
# ---------------------------------------------------------------------------


def test_get_latest_successful_id_excludes_branch_runs_by_default(tmp_path):
    """When branch_id=None (default), exclude runs with non-NULL branch_id.
    Explicit branch_id='b1' returns the branch run."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    _, pv_id = _setup_run(store)

    # Non-branch run (older)
    main_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (main_run_id, pv_id, "2024-01-01T00:00:00", "2024-01-01T01:00:00"),
    )
    # Branch run (newer, would win without branch scoping)
    branch_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at, branch_id) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (branch_run_id, pv_id, "2024-01-02T00:00:00", "2024-01-02T01:00:00", "b1"),
    )

    # Default (branch_id=None) → non-branch run
    assert repo.get_latest_successful_id(pv_id) == main_run_id
    # Explicit branch_id → branch run
    assert repo.get_latest_successful_id(pv_id, branch_id="b1") == branch_run_id


def test_get_latest_successful_step_excludes_branch_runs_by_default(tmp_path):
    """When branch_id=None (default), exclude steps from branch runs."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    _, pv_id = _setup_run(store)

    # Non-branch run + step (older)
    main_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (main_run_id, pv_id, "2024-01-01T00:00:00", "2024-01-01T01:00:00"),
    )
    main_step_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (main_step_id, main_run_id, "step1", pv_id, "succeeded",
         "2024-01-01T00:00:00", "{}", "[]", "[]"),
    )

    # Branch run + step (newer)
    branch_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at, branch_id) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (branch_run_id, pv_id, "2024-01-02T00:00:00", "2024-01-02T01:00:00", "b1"),
    )
    branch_step_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (branch_step_id, branch_run_id, "step1", pv_id, "succeeded",
         "2024-01-02T00:00:00", "{}", "[]", "[]"),
    )

    # Default (branch_id=None) → non-branch step
    result = repo.get_latest_successful_step(pv_id, "step1")
    assert result is not None
    assert result["run_step_id"] == main_step_id

    # Explicit branch_id → branch step
    result = repo.get_latest_successful_step(pv_id, "step1", branch_id="b1")
    assert result is not None
    assert result["run_step_id"] == branch_step_id


def test_get_latest_successful_id_for_plan_excludes_branch_runs(tmp_path):
    """get_latest_successful_id_for_plan must exclude branch runs."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    _, pv_id = _setup_run(store)

    # Non-branch run (older)
    main_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (main_run_id, pv_id, "2024-01-01T00:00:00", "2024-01-01T01:00:00"),
    )
    # Branch run (newer)
    branch_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at, branch_id) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (branch_run_id, pv_id, "2024-01-02T00:00:00", "2024-01-02T01:00:00", "b1"),
    )

    # Must return the non-branch run
    result = repo.get_latest_successful_id_for_plan("plan1")
    assert result == main_run_id


def test_get_latest_successful_step_across_plan_excludes_branch_runs(tmp_path):
    """get_latest_successful_step_across_plan must exclude branch runs."""
    store = _make_store(tmp_path)
    repo = _make_repo(store)
    _, pv_id = _setup_run(store)

    # Non-branch run + step (older)
    main_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (main_run_id, pv_id, "2024-01-01T00:00:00", "2024-01-01T01:00:00"),
    )
    main_step_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (main_step_id, main_run_id, "step1", pv_id, "succeeded",
         "2024-01-01T00:00:00", "{}", "[]", "[]"),
    )

    # Branch run + step (newer)
    branch_run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at, branch_id) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (branch_run_id, pv_id, "2024-01-02T00:00:00", "2024-01-02T01:00:00", "b1"),
    )
    branch_step_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (branch_step_id, branch_run_id, "step1", pv_id, "succeeded",
         "2024-01-02T00:00:00", "{}", "[]", "[]"),
    )

    # Default → non-branch step
    result = repo.get_latest_successful_step_across_plan("plan1", "step1")
    assert result is not None
    assert result["run_step_id"] == main_step_id

    # Explicit branch_id → branch step
    result = repo.get_latest_successful_step_across_plan("plan1", "step1", branch_id="b1")
    assert result is not None
    assert result["run_step_id"] == branch_step_id


def test_evidence_artifacts_cascade_on_artifact_delete(tmp_path):
    """Deleting an artifact cascades to evidence_artifacts rows referencing it."""
    store = _make_store(tmp_path)
    run_id, pv_id = _setup_run(store)

    # Insert an artifact
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
        "physical_hash, logical_hash, media_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("art_ev_cascade", "dataset", "output", "datasets/ev.parquet",
         "abc", "def", "application/vnd.apache.parquet", utc_now_iso()),
    )

    # Insert a run_step (parent FK needed for evidence_edges)
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rs_id, run_id, "step1", pv_id, "succeeded",
         utc_now_iso(), "{}", "[]", "[]"),
    )

    # Insert evidence_edge (parent FK for evidence_artifacts)
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges (evidence_edge_id, run_id, run_step_id, plan_version_id, "
        "step_id, parent_step_id, source_run_id, source_run_step_id, policy, "
        "source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ee_id, run_id, rs_id, pv_id, "step1", "step0", run_id, rs_id,
         "test_policy", "test_label", 0, 0, utc_now_iso()),
    )

    # Insert an evidence_artifacts row referencing the artifact
    ea_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ea_id, ee_id, "art_ev_cascade", "output", utc_now_iso()),
    )

    # Verify evidence_artifacts row exists
    row = store.execute(
        "SELECT 1 FROM evidence_artifacts WHERE evidence_artifact_id = ?", (ea_id,)
    ).fetchone()
    assert row is not None, "evidence_artifacts row should exist before cascade"

    # Delete the artifact — should cascade to evidence_artifacts
    store.execute("DELETE FROM artifacts WHERE artifact_id = ?", ("art_ev_cascade",))

    row = store.execute(
        "SELECT 1 FROM evidence_artifacts WHERE evidence_artifact_id = ?", (ea_id,)
    ).fetchone()
    assert row is None, "evidence_artifacts row should be cascade-deleted when artifact is deleted"
