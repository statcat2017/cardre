"""Tests for the reporting layer — evidence_contract, readiness, collector, renderer.

Port from v1: validates that report generation, readiness checks, and
HTML rendering work against the v2 store schema.
"""

from __future__ import annotations

import json
import uuid

from cardre._evidence.schemas import (
    SCHEMA_EXCLUSION_SUMMARY,
    SCHEMA_EXPLAINABILITY_REPORT,
)
from cardre.domain.diagnostics import utc_now_iso
from cardre.readiness import check_report_readiness
from cardre.readiness.dto import ReportReadinessResult
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.collector import generate_report_bundle
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
)
from cardre.reporting.renderer_html import render_report_bundle_to_html
from cardre.services.report_service import ReportGenerationService

# ---------------------------------------------------------------------------
# Evidence contract tests
# ---------------------------------------------------------------------------

def test_evidence_contract_required_steps():
    """Required steps lists should be non-empty and well-formed."""
    assert len(REQUIRED_STEPS_BRANCH) >= 3
    assert len(REQUIRED_STEPS_CHAMPION) >= 3
    assert all(isinstance(s, str) for s in REQUIRED_STEPS_BRANCH)
    assert all(isinstance(s, str) for s in REQUIRED_STEPS_CHAMPION)


# ---------------------------------------------------------------------------
# Readiness check tests
# ---------------------------------------------------------------------------

def test_check_report_readiness_blocked_no_run(store, monkeypatch):
    """Readiness should be blocked when no run exists."""
    # Create minimal project + branch
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base"),
    )
    branch_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, description, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, "
        " branch_point_step_id, branch_point_canonical_step_id, segment_filter_spec_json, "
        " created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'test-branch', NULL, 'feature', 'active', "
        " ?, ?, NULL, NULL, NULL, 'test', ?, ?)",
        (branch_id, project_id, plan_id, pv_id, pv_id, now, now),
    )

    # Without a run, readiness should be blocked
    result = check_report_readiness(
        store=store,
        project_id=project_id,
        run_id="nonexistent-run",
        target_branch_id=branch_id,
        report_mode="branch",
    )
    assert not result.ready
    assert len(result.blockers) > 0


def test_report_readiness_result():
    """ReportReadinessResult works correctly."""
    from cardre.readiness.dto import ReadinessFinding

    result = ReportReadinessResult(
        blockers=[
            ReadinessFinding(severity="blocker", code="TARGET_BRANCH_NOT_FOUND", message="Branch not found"),
        ],
        target_branch_id="test-branch",
        run_id="test-run",
    )
    assert not result.ready
    assert result.status == "blocked"
    assert len(result.blockers) == 1
    assert result.blockers[0].code == "TARGET_BRANCH_NOT_FOUND"

    d = result.model_dump(exclude_none=True)
    assert d["status"] == "blocked"
    assert d["blockers"][0]["code"] == "TARGET_BRANCH_NOT_FOUND"


def test_champion_readiness_green_requires_oot_and_implementation_exports(store):
    """Champion mode is ready only when OOT scoring and export artifacts exist."""
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    now = utc_now_iso()

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Champion", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (plan_version_id, plan_id, now, "Base"),
    )
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, branch_type, status, base_plan_version_id, "
        " head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'champion', 'feature', 'active', ?, ?, 'test', ?, ?)",
        (branch_id, project_id, plan_id, plan_version_id, plan_version_id, now, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, plan_version_id, now, now, now),
    )

    artifact_dir = store.root / "artifacts"
    artifact_dir.mkdir(exist_ok=True)

    def add_step(step_id: str, position: int, params: dict[str, object] | None = None) -> str:
        run_step_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'validate', ?, ?, ?, ?)",
            (step_id, plan_version_id, json.dumps(params or {}), f"hash-{step_id}", position, step_id),
        )
        store.execute(
            "INSERT INTO branch_step_map "
            "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
            " is_branch_owned, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (str(uuid.uuid4()), branch_id, plan_version_id, step_id, step_id, now),
        )
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}')",
            (run_step_id, run_id, step_id, plan_version_id, now, now),
        )
        return run_step_id

    def add_artifact(
        run_step_id: str,
        step_id: str,
        *,
        role: str,
        artifact_type: str = "report",
        schema_version: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> str:
        artifact_id = str(uuid.uuid4())
        path = artifact_dir / f"{artifact_id}.json"
        path.write_text(json.dumps(payload or {"ok": True}), encoding="utf-8")
        metadata = {"schema_version": schema_version} if schema_version else {}
        store.execute(
            "INSERT INTO artifacts "
            "(artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, 'application/json', ?, ?)",
            (
                artifact_id,
                artifact_type,
                role,
                str(path.relative_to(store.root)),
                f"ph-{artifact_id}",
                f"lh-{artifact_id}",
                now,
                json.dumps(metadata),
            ),
        )
        store.execute(
            "INSERT INTO artifact_lineage "
            "(lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
            (str(uuid.uuid4()), run_id, run_step_id, plan_version_id, step_id, artifact_id, now),
        )
        return artifact_id

    step_ids = list(dict.fromkeys([*REQUIRED_STEPS_CHAMPION, "manual-binning"]))
    run_steps = {
        step_id: add_step(
            step_id,
            i,
            {"accept_automated": True} if step_id == "manual-binning" else None,
        )
        for i, step_id in enumerate(step_ids)
    }

    add_artifact(
        run_steps["final-woe-iv"],
        "final-woe-iv",
        role="report",
        schema_version="cardre.woe_iv_evidence.v1",
        payload={
            "schema_version": "cardre.woe_iv_evidence.v1",
            "variables": [{
                "variable_name": "age_years",
                "iv": 0.1,
                "bins": [
                    {"bin_id": "low", "label": "low", "woe": -0.5},
                    {"bin_id": "high", "label": "high", "woe": 0.5},
                ],
            }],
        },
    )
    add_artifact(run_steps["model-fit"], "model-fit", role="model", schema_version="cardre.model_artifact.v1")
    add_artifact(run_steps["score-scaling"], "score-scaling", role="scorecard", schema_version="cardre.score_scaling.v1")
    add_artifact(run_steps["freeze-scorecard-bundle"], "freeze-scorecard-bundle", role="scorecard")
    add_artifact(run_steps["validation-metrics"], "validation-metrics", role="report", schema_version="cardre.validation_metrics.v1")
    add_artifact(run_steps["cutoff-analysis"], "cutoff-analysis", role="report", schema_version="cardre.cutoff_analysis.v1")
    add_artifact(run_steps["scorecard-table-export"], "scorecard-table-export", role="report", schema_version="cardre.scorecard_table.v1")
    add_artifact(run_steps["scoring-export-python"], "scoring-export-python", role="report", schema_version="cardre.scoring_export_python.v1")
    add_artifact(run_steps["scoring-export-sql"], "scoring-export-sql", role="report", schema_version="cardre.scoring_export_sql.v1")
    for role in ("train", "test", "oot"):
        add_artifact(run_steps["apply-model"], "apply-model", role=role, artifact_type="dataset")

    comparison_id = str(uuid.uuid4())
    comparison_artifact_id = add_artifact(run_steps["manual-binning"], "manual-binning", role="report", artifact_type="comparison")
    snapshot_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO branch_comparisons "
        "(comparison_id, project_id, plan_id, baseline_branch_id, comparison_spec_json, "
        " latest_snapshot_id, latest_ready, latest_readiness_json, created_at, created_reason) "
        "VALUES (?, ?, ?, ?, '{}', ?, 1, '{}', ?, 'test')",
        (comparison_id, project_id, plan_id, branch_id, snapshot_id, now),
    )
    store.execute(
        "INSERT INTO branch_comparison_snapshots "
        "(comparison_snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id, readiness_json, created_at, created_reason) "
        "VALUES (?, ?, ?, ?, ?, '{}', ?, 'test')",
        (snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id, now),
    )
    store.execute(
        "INSERT INTO champion_assignments "
        "(champion_assignment_id, project_id, plan_id, scope_type, scope_key, champion_branch_id, "
        " comparison_id, comparison_snapshot_id, comparison_artifact_id, selected_plan_version_id, "
        " assigned_reason, assigned_by, assigned_at) "
        "VALUES (?, ?, ?, 'plan', ?, ?, ?, ?, ?, ?, 'test', 'test', ?)",
        (
            str(uuid.uuid4()), project_id, plan_id, plan_id, branch_id,
            comparison_id, snapshot_id, comparison_artifact_id, plan_version_id, now,
        ),
    )

    result = check_report_readiness(store, project_id, run_id, branch_id, report_mode="champion")

    assert result.ready, [(b.code, b.message) for b in result.blockers]

    store.execute(
        "DELETE FROM artifact_lineage WHERE run_step_id = ? AND artifact_id IN "
        "(SELECT artifact_id FROM artifacts WHERE role = 'oot')",
        (run_steps["apply-model"],),
    )
    result_without_scored_oot = check_report_readiness(
        store, project_id, run_id, branch_id, report_mode="champion",
    )
    assert any(
        blocker.code == LimitationCode.MISSING_SCORE_APPLICATION
        for blocker in result_without_scored_oot.blockers
    )


def test_report_bundle_collects_model_limitations_evidence(store):
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    run_step_id = str(uuid.uuid4())
    artifact_id = str(uuid.uuid4())
    now = utc_now_iso()

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Limitations", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (plan_version_id, plan_id, now, "Base"),
    )
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, branch_type, status, base_plan_version_id, "
        " head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'candidate', 'feature', 'active', ?, ?, 'test', ?, ?)",
        (branch_id, project_id, plan_id, plan_version_id, plan_version_id, now, now),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, position, canonical_step_id) "
        "VALUES ('model-limitations', ?, 'cardre.model_limitations', '1', 'report', '{}', 'hash', 0, 'model-limitations')",
        (plan_version_id,),
    )
    store.execute(
        "INSERT INTO branch_step_map "
        "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, is_branch_owned, created_at) "
        "VALUES (?, ?, ?, 'model-limitations', 'model-limitations', 1, ?)",
        (str(uuid.uuid4()), branch_id, plan_version_id, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, plan_version_id, now, now, now),
    )
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, 'model-limitations', ?, 'succeeded', ?, ?, '{}')",
        (run_step_id, run_id, plan_version_id, now, now),
    )

    artifact_dir = store.root / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    artifact_path = artifact_dir / f"{artifact_id}.json"
    artifact_path.write_text(json.dumps({
        "schema_version": SCHEMA_EXPLAINABILITY_REPORT,
        "model_family": "gradient_boosting",
        "limitations": [{
            "code": "INTERPRETABILITY_LIMITED",
            "severity": "block",
            "message": "Post-hoc explanation is required before champion promotion.",
            "accepted": False,
        }],
    }), encoding="utf-8")
    store.execute(
        "INSERT INTO artifacts "
        "(artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, 'report', 'report', ?, 'ph-limit', 'lh-limit', 'application/json', ?, ?)",
        (
            artifact_id,
            str(artifact_path.relative_to(store.root)),
            now,
            json.dumps({"schema_version": SCHEMA_EXPLAINABILITY_REPORT}),
        ),
    )
    store.execute(
        "INSERT INTO artifact_lineage "
        "(lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
        "VALUES (?, ?, ?, ?, 'model-limitations', ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, run_step_id, plan_version_id, artifact_id, now),
    )

    bundle = generate_report_bundle(store, project_id, run_id, branch_id)

    assert any(
        limitation.code == "INTERPRETABILITY_LIMITED" and limitation.severity == "blocker"
        for limitation in bundle.limitations
    )


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

def test_render_report_bundle_empty():
    """Empty report bundle renders to HTML without error."""
    bundle = {
        "summary": {},
        "limitations": [],
        "variables": [],
        "model": {},
        "score_scaling": {},
        "validation": {},
        "cutoffs": {},
        "champion": {},
        "artifacts": [],
        "generated_at": utc_now_iso(),
        "cardre_version": "0.2.0",
    }
    html = render_report_bundle_to_html(bundle)
    assert isinstance(html, str)
    assert len(html) > 100
    assert "<html" in html.lower() or "<!DOCTYPE" in html


def test_generate_report_bundle_missing_run(tmp_path):
    """generate_report_bundle should return a minimal bundle even with no data."""
    from cardre.store.db import ProjectStore
    s = ProjectStore(tmp_path / "test.cardre")
    s.initialize()

    # Create minimal project
    pid = str(uuid.uuid4())
    now = utc_now_iso()
    s.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (pid, "Test", now, "0.2.0"),
    )
    plid = str(uuid.uuid4())
    s.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plid, pid, "Plan", now),
    )
    pvid = str(uuid.uuid4())
    s.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pvid, plid, now, "Base"),
    )
    bid = str(uuid.uuid4())
    s.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, description, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, "
        " branch_point_step_id, branch_point_canonical_step_id, segment_filter_spec_json, "
        " created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'test-branch', NULL, 'feature', 'active', "
        " ?, ?, NULL, NULL, NULL, 'test', ?, ?)",
        (bid, pid, plid, pvid, pvid, now, now),
    )

    bundle = generate_report_bundle(
        store=s,
        project_id=pid,
        run_id="nonexistent",
        target_branch_id=bid,
        report_mode="branch",
    )
    assert bundle is not None
    assert hasattr(bundle, 'model_dump')


def test_generate_report_bundle_preserves_exclusion_summary_counts(store):
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    run_step_id = str(uuid.uuid4())
    now = utc_now_iso()

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Report Test", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (plan_version_id, plan_id, now, "Base"),
    )
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, description, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, branch_point_step_id, "
        " branch_point_canonical_step_id, segment_filter_spec_json, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'branch', NULL, 'feature', 'active', ?, ?, NULL, NULL, NULL, 'test', ?, ?)",
        (branch_id, project_id, plan_id, plan_version_id, plan_version_id, now, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, plan_version_id, now, now, now),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, params_json, params_hash, position, canonical_step_id) "
        "VALUES ('apply-exclusions', ?, 'cardre.apply_exclusions', '1', 'prep', '{}', 'hash-apply-exclusions', 0, 'apply-exclusions')",
        (plan_version_id,),
    )
    store.execute(
        "INSERT INTO branch_step_map "
        "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, is_branch_owned, created_at) "
        "VALUES (?, ?, ?, 'apply-exclusions', 'apply-exclusions', 1, ?)",
        (str(uuid.uuid4()), branch_id, plan_version_id, now),
    )
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, 'apply-exclusions', ?, 'succeeded', ?, ?, '{}')",
        (run_step_id, run_id, plan_version_id, now, now),
    )

    artifact_dir = store.root / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    artifact_id = str(uuid.uuid4())
    artifact_path = artifact_dir / f"{artifact_id}.json"
    artifact_path.write_text(json.dumps({
        "schema_version": SCHEMA_EXCLUSION_SUMMARY,
        "rows_before": 60,
        "rows_after": 45,
        "rows_excluded": 15,
        "rules": [{"reason": "missing income", "rows_removed": 15}],
    }), encoding="utf-8")
    store.execute(
        "INSERT INTO artifacts "
        "(artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, 'report', 'report', ?, 'ph-excl', 'lh-excl', 'application/json', ?, ?)",
        (
            artifact_id,
            str(artifact_path.relative_to(store.root)),
            now,
            json.dumps({"schema_version": SCHEMA_EXCLUSION_SUMMARY}),
        ),
    )
    store.execute(
        "INSERT INTO artifact_lineage "
        "(lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
        "VALUES (?, ?, ?, ?, 'apply-exclusions', ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, run_step_id, plan_version_id, artifact_id, now),
    )

    bundle = generate_report_bundle(store, project_id, run_id, branch_id)

    assert bundle.exclusion_summary.rows_before == 60
    assert bundle.exclusion_summary.rows_after == 45
    assert bundle.exclusion_summary.rules[0].rows_removed == 15


# ---------------------------------------------------------------------------
# ReportGenerationService tests
# ---------------------------------------------------------------------------

def test_report_service_init(store):
    """ReportGenerationService initialises with a store."""
    svc = ReportGenerationService(store)
    assert svc is not None
    assert svc.store is store


def test_report_service_check_readiness_no_data(store):
    """Service readiness check returns blocked for missing data."""
    svc = ReportGenerationService(store)
    result = svc.check_readiness(
        project_id="nonexistent",
        run_id="nonexistent",
        target_branch_id="nonexistent",
    )
    assert not result.ready


def test_renderer_html_output():
    """HTML renderer produces valid output."""
    bundle = {
        "summary": {
            "project_name": "Test",
            "model_name": "Test Model",
            "target": "credit_risk",
            "generated_at": utc_now_iso(),
        },
        "limitations": [],
        "variables": [
            {
                "name": "var1",
                "role": "accepted",
                "iv": 0.5,
                "num_bins": 5,
            }
        ],
        "model": {
            "family": "LogisticRegression",
            "features": {"var1": 0.5},
        },
        "score_scaling": {
            "offset": 500,
            "pdo": 20,
            "odds": 50,
        },
        "validation": {
            "train": {"auc": 0.75, "ks": 0.5},
        },
        "cutoffs": {
            "cutoffs": [{"cutoff": 0.5, "approval_rate": 0.6}],
        },
        "champion": {},
        "artifacts": [],
        "generated_at": utc_now_iso(),
        "cardre_version": "0.2.0",
    }
    html = render_report_bundle_to_html(bundle)
    assert isinstance(html, str)
    assert len(html) > 200
    # Should contain some expected sections
    assert "Test Model" in html or "Test" in html
