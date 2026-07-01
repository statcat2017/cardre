"""SQL schema and migration statements for the Cardre project store."""

# Current app schema identity — bump when making incompatible changes.
# Stored in store_meta table; old apps will reject older or newer stores.
STORE_SCHEMA_FAMILY = "cardre.project_store.v2"
STORE_SCHEMA_VERSION = 5

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cardre_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plan_versions (
    plan_version_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(plan_id, version_number)
);

CREATE TABLE IF NOT EXISTS plan_steps (
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    node_type TEXT NOT NULL,
    node_version TEXT NOT NULL,
    category TEXT NOT NULL,
    params_json TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    parent_step_ids_json TEXT NOT NULL,
    branch_label TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    canonical_step_id TEXT NOT NULL DEFAULT '',
    branch_id TEXT,
    PRIMARY KEY (plan_version_id, step_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_steps (
    run_step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_artifact_ids_json TEXT NOT NULL,
    output_artifact_ids_json TEXT NOT NULL,
    execution_fingerprint_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    is_carried_forward INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    role TEXT NOT NULL,
    path TEXT NOT NULL,
    physical_hash TEXT NOT NULL,
    logical_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

"""

BRANCH_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS plan_branches (
    branch_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    branch_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    base_branch_id TEXT,
    base_plan_version_id TEXT NOT NULL,
    head_plan_version_id TEXT NOT NULL,
    branch_point_step_id TEXT,
    branch_point_canonical_step_id TEXT,
    segment_filter_spec_json TEXT,
    created_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(project_id),
    FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
);
CREATE TABLE IF NOT EXISTS branch_step_map (
    branch_step_map_id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    canonical_step_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    source_branch_id TEXT,
    source_step_id TEXT,
    is_shared_upstream INTEGER NOT NULL DEFAULT 0,
    is_branch_owned INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(branch_id) REFERENCES plan_branches(branch_id)
);
CREATE TABLE IF NOT EXISTS branch_comparisons (
    comparison_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    baseline_branch_id TEXT NOT NULL,
    challenger_branch_ids_json TEXT NOT NULL,
    comparison_spec_json TEXT NOT NULL,
    latest_snapshot_id TEXT,
    latest_ready INTEGER,
    latest_readiness_json TEXT,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(baseline_branch_id) REFERENCES plan_branches(branch_id)
);
CREATE TABLE IF NOT EXISTS branch_comparison_snapshots (
    comparison_snapshot_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    source_plan_version_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id)
);
CREATE TABLE IF NOT EXISTS step_annotations (
    annotation_id TEXT PRIMARY KEY,
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS champion_assignments (
    champion_assignment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    champion_branch_id TEXT NOT NULL,
    comparison_id TEXT NOT NULL,
    comparison_snapshot_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL,
    selected_plan_version_id TEXT NOT NULL,
    assigned_reason TEXT NOT NULL,
    assigned_by TEXT,
    assigned_at TEXT NOT NULL,
    superseded_at TEXT,
    superseded_by_assignment_id TEXT,
    FOREIGN KEY(champion_branch_id) REFERENCES plan_branches(branch_id),
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id),
    FOREIGN KEY(comparison_snapshot_id) REFERENCES branch_comparison_snapshots(comparison_snapshot_id)
);
"""

LINEAGE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS artifact_lineage (
    lineage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    run_step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    branch_id TEXT,
    artifact_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_step_id, artifact_id, direction)
);
"""

MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Performance indexes for common query patterns.
# Applied by run_migrations() — safe to re-run (IF NOT EXISTS).
INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_runs_plan_version_branch_status
    ON runs(plan_version_id, branch_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_steps_run_started
    ON run_steps(run_id, started_at, run_step_id);
CREATE INDEX IF NOT EXISTS idx_run_steps_pv_step_status
    ON run_steps(plan_version_id, step_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_plans_project_created
    ON plans(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_plan_branches_project_plan_status
    ON plan_branches(project_id, plan_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_branch_step_map_branch_pv
    ON branch_step_map(branch_id, plan_version_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type_role
    ON artifacts(artifact_type, role);
CREATE INDEX IF NOT EXISTS idx_run_steps_run_id
    ON run_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_lineage_artifact ON artifact_lineage(artifact_id);
CREATE INDEX IF NOT EXISTS idx_lineage_run_direction ON artifact_lineage(run_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_step_direction ON artifact_lineage(step_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_pv_step ON artifact_lineage(plan_version_id, step_id);
CREATE INDEX IF NOT EXISTS idx_lineage_run_step ON artifact_lineage(run_step_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_branch_direction ON artifact_lineage(branch_id, direction);
"""
