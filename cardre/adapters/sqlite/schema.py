"""Clean SQLite schema v1 for the Cardre hexagonal architecture.

Replaces cardre/store/schema.py v101. No migration chain — projects are
recreated (ADR-0003). Schema version row recorded but no migration runner
shipped until first real deployment.
"""

V3_STORE_SCHEMA_FAMILY = "cardre-v3"
V3_STORE_SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
    is_committed INTEGER NOT NULL DEFAULT 0 CHECK (is_committed IN (0,1)),
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
    branch_label TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    canonical_step_id TEXT NOT NULL DEFAULT '',
    branch_id TEXT,
    PRIMARY KEY (plan_version_id, step_id)
);

CREATE TABLE IF NOT EXISTS plan_step_edges (
    plan_version_id TEXT NOT NULL,
    parent_step_id TEXT NOT NULL,
    child_step_id TEXT NOT NULL,
    edge_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (plan_version_id, parent_step_id, child_step_id),
    FOREIGN KEY(plan_version_id, parent_step_id)
        REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE,
    FOREIGN KEY(plan_version_id, child_step_id)
        REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','cancelled','interrupted')),
    run_scope TEXT NOT NULL CHECK (run_scope IN ('full_plan','branch')),
    branch_id TEXT,
    force INTEGER NOT NULL DEFAULT 0,
    requested_by TEXT,
    request_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT,
    active_step_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_steps (
    run_step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    execution_fingerprint_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    role TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    physical_hash TEXT NOT NULL,
    logical_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(physical_hash)
);

CREATE TABLE IF NOT EXISTS artifact_lineage (
    lineage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    branch_id TEXT,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('input','output')),
    created_at TEXT NOT NULL,
    UNIQUE(run_step_id, artifact_id, direction)
);
"""

EVIDENCE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS evidence_edges (
    evidence_edge_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
    plan_version_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    parent_step_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    source_run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
    policy TEXT NOT NULL,
    source_label TEXT NOT NULL,
    is_reused INTEGER NOT NULL CHECK (is_reused IN (0,1)),
    is_stale INTEGER NOT NULL CHECK (is_stale IN (0,1)),
    stale_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_step_id, parent_step_id, source_run_step_id)
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    evidence_artifact_id TEXT PRIMARY KEY,
    evidence_edge_id TEXT NOT NULL REFERENCES evidence_edges(evidence_edge_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(evidence_edge_id, artifact_id)
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
    base_branch_id TEXT REFERENCES plan_branches(branch_id),
    base_plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id),
    head_plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id),
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
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id),
    canonical_step_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    source_branch_id TEXT REFERENCES plan_branches(branch_id),
    source_step_id TEXT,
    is_shared_upstream INTEGER NOT NULL DEFAULT 0,
    is_branch_owned INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(branch_id) REFERENCES plan_branches(branch_id)
);

CREATE TABLE IF NOT EXISTS branch_comparisons (
    comparison_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    baseline_branch_id TEXT NOT NULL,
    comparison_spec_json TEXT NOT NULL,
    latest_snapshot_id TEXT,
    latest_ready INTEGER,
    latest_readiness_json TEXT,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(baseline_branch_id) REFERENCES plan_branches(branch_id)
);

CREATE TABLE IF NOT EXISTS comparison_challenger_branches (
    comparison_id TEXT NOT NULL REFERENCES branch_comparisons(comparison_id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES plan_branches(branch_id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (comparison_id, branch_id)
);

CREATE TABLE IF NOT EXISTS branch_comparison_snapshots (
    comparison_snapshot_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    readiness_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id)
);

CREATE TABLE IF NOT EXISTS comparison_snapshot_plan_versions (
    comparison_snapshot_id TEXT NOT NULL REFERENCES branch_comparison_snapshots(comparison_snapshot_id) ON DELETE CASCADE,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id),
    branch_id TEXT REFERENCES plan_branches(branch_id),
    PRIMARY KEY (comparison_snapshot_id, plan_version_id)
);
"""

ANNOTATION_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS step_annotations (
    annotation_id TEXT PRIMARY KEY,
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(plan_version_id, step_id) REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS champion_assignments (
    champion_assignment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    plan_id TEXT NOT NULL REFERENCES plans(plan_id),
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    champion_branch_id TEXT NOT NULL,
    comparison_id TEXT NOT NULL,
    comparison_snapshot_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    selected_plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id),
    assigned_reason TEXT NOT NULL,
    assigned_by TEXT,
    assigned_at TEXT NOT NULL,
    superseded_at TEXT,
    superseded_by_assignment_id TEXT REFERENCES champion_assignments(champion_assignment_id),
    FOREIGN KEY(champion_branch_id) REFERENCES plan_branches(branch_id),
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id),
    FOREIGN KEY(comparison_snapshot_id) REFERENCES branch_comparison_snapshots(comparison_snapshot_id)
);
"""

REVIEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS diagnostics (
    diagnostic_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source TEXT,
    severity TEXT NOT NULL DEFAULT 'error',
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_binning_reviews (
    review_id TEXT PRIMARY KEY,
    plan_version_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected')),
    reviewer_notes TEXT NOT NULL DEFAULT '',
    affected_downstream_step_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(plan_version_id, step_id) REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE
);
"""

EXPORTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS exports (
    export_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    export_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_runs_plan_version_status
    ON runs(plan_version_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_cancel_requested
    ON runs(cancel_requested) WHERE cancel_requested = 1;
CREATE INDEX IF NOT EXISTS idx_run_steps_run_id
    ON run_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_run_steps_pv_step_status
    ON run_steps(plan_version_id, step_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_plans_project_created
    ON plans(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_plan_versions_plan_version
    ON plan_versions(plan_id, version_number);
CREATE INDEX IF NOT EXISTS idx_plan_step_edges_child
    ON plan_step_edges(plan_version_id, child_step_id);
CREATE INDEX IF NOT EXISTS idx_plan_step_edges_parent
    ON plan_step_edges(plan_version_id, parent_step_id);
CREATE INDEX IF NOT EXISTS idx_plan_branches_project_plan_status
    ON plan_branches(project_id, plan_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_branch_step_map_branch_pv
    ON branch_step_map(branch_id, plan_version_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type_role
    ON artifacts(artifact_type, role);
CREATE INDEX IF NOT EXISTS idx_artifacts_physical_hash
    ON artifacts(physical_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_logical_hash
    ON artifacts(logical_hash);
CREATE INDEX IF NOT EXISTS idx_lineage_artifact ON artifact_lineage(artifact_id);
CREATE INDEX IF NOT EXISTS idx_lineage_run_direction ON artifact_lineage(run_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_step_direction ON artifact_lineage(step_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_pv_step ON artifact_lineage(plan_version_id, step_id);
CREATE INDEX IF NOT EXISTS idx_lineage_run_step ON artifact_lineage(run_step_id, direction);
CREATE INDEX IF NOT EXISTS idx_lineage_branch_direction ON artifact_lineage(branch_id, direction);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_run_step
    ON evidence_edges(run_step_id);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_pv_step
    ON evidence_edges(plan_version_id, step_id);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_parent
    ON evidence_edges(plan_version_id, parent_step_id);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_run
    ON evidence_edges(run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_edges_source_step
    ON evidence_edges(source_run_step_id);
CREATE INDEX IF NOT EXISTS idx_evidence_artifacts_artifact
    ON evidence_artifacts(artifact_id);
CREATE INDEX IF NOT EXISTS idx_evidence_artifacts_edge_role
    ON evidence_artifacts(evidence_edge_id, role);
CREATE INDEX IF NOT EXISTS idx_diagnostics_run
    ON diagnostics(run_id);
CREATE INDEX IF NOT EXISTS idx_comparison_challenger_branches_comparison
    ON comparison_challenger_branches(comparison_id);
CREATE INDEX IF NOT EXISTS idx_comparison_snapshot_pv_snapshot
    ON comparison_snapshot_plan_versions(comparison_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_step_annotations_pv_step
    ON step_annotations(plan_version_id, step_id);
CREATE INDEX IF NOT EXISTS idx_manual_binning_reviews_pv_step
    ON manual_binning_reviews(plan_version_id, step_id);
CREATE INDEX IF NOT EXISTS idx_champion_assignments_plan_superseded
    ON champion_assignments(plan_id, superseded_at);
CREATE INDEX IF NOT EXISTS idx_exports_run
    ON exports(run_id);
"""

ALL_TABLES_SQL = (
    SCHEMA_SQL
    + EVIDENCE_TABLES_SQL
    + BRANCH_TABLES_SQL
    + ANNOTATION_TABLES_SQL
    + REVIEW_TABLES_SQL
    + EXPORTS_TABLE_SQL
    + INDEXES_SQL
)
