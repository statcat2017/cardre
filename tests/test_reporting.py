"""Tests for the reporting layer — evidence_contract, readiness, collector, renderer.

Port from v1: validates that report generation, readiness checks, and
HTML rendering work against the v2 store schema.
"""

from __future__ import annotations

import uuid
from pathlib import Path


from cardre.domain.diagnostics import utc_now_iso
from cardre.readiness import check_report_readiness
from cardre.readiness.dto import ReportReadinessResult
from cardre.reporting.collector import generate_report_bundle
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
    canonical_alias_candidates,
    resolve_canonical_step_id,
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


def test_canonical_alias_candidates():
    """Legacy alias resolution works."""
    candidates = canonical_alias_candidates("logistic-regression")
    assert "logistic-regression" in candidates
    assert "model-fit" in candidates

    candidates = canonical_alias_candidates("model-fit")
    assert "model-fit" in candidates
    assert "logistic-regression" in candidates


def test_resolve_canonical_step_id():
    """Legacy canonical step ID resolution."""
    assert resolve_canonical_step_id("logistic-regression") == "model-fit"
    assert resolve_canonical_step_id("model-fit") == "model-fit"
    assert resolve_canonical_step_id("unknown-step") == "unknown-step"


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
    from cardre.readiness.dto import ReadinessBlocker

    result = ReportReadinessResult(
        blockers=[
            ReadinessBlocker("TARGET_BRANCH_NOT_FOUND", "Branch not found"),
        ],
        target_branch_id="test-branch",
        run_id="test-run",
    )
    assert not result.ready
    assert result.status == "blocked"
    assert len(result.blockers) == 1
    assert result.blockers[0].code == "TARGET_BRANCH_NOT_FOUND"

    d = result.to_dict()
    assert d["status"] == "blocked"
    assert d["blockers"][0]["code"] == "TARGET_BRANCH_NOT_FOUND"


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


def test_generate_report_bundle_missing_run():
    """generate_report_bundle should return a minimal bundle even with no data."""
    from cardre.store.db import ProjectStore
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
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
