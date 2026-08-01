"""Integration tests for governance and manual-binning routes (Commit 2).

Exercises the real application use cases through the FastAPI TestClient
with governance enabled, against the production SQLite persistence stack.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec


@pytest.fixture
def governance_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_GOVERNANCE", "1")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "1")
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return TestClient(app), container


def _provision_project(container, tmp_path, name="Gov Project"):
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / f"{name}.cardre"
    provisioner.initialize(root)
    with container.uow_factory.for_root(root) as uow:
        project_id = uow.projects.create(name)
        uow.commit()
    container.project_registry.register(project_id, root)
    return project_id, root


def _seed_branchable_plan(container, project_id):
    """Seed a committed plan with branchable steps; return (plan_id, pv_id)."""
    steps = [
        StepSpec(step_id="step-sample", node_type="cardre.noop", node_version="1",
                 category="transform", params={}, params_hash=json_logical_hash({}),
                 parent_step_ids=[], branch_label="", position=0,
                 canonical_step_id="sample-definition"),
    ]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()
    return plan_id, pv_id


def _create_branch_via_use_case(container, project_id, plan_id, pv_id, branch_type="segment_challenger"):
    from cardre.application.governance.create_branch import CreateBranchCommand
    uc = container.create_branch_factory(project_id)
    result = uc(CreateBranchCommand(
        project_id=project_id, plan_id=plan_id, name=f"b-{uuid.uuid4().hex[:4]}",
        branch_type=branch_type, branch_point_step_id="sample-definition",
        base_branch_id=None, base_plan_version_id=pv_id,
        created_reason="integration test",
        segment_filter_spec={"rules": [
            {"column": "channel", "operator": "==", "value": "online", "reason": "test"},
        ]},
    ))
    return result.branch_id


# ---------------------------------------------------------------------------
# Governance-disabled 403 envelope
# ---------------------------------------------------------------------------


def test_governance_disabled_returns_403_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_GOVERNANCE", "0")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "1")
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    client = TestClient(app)
    project_id, root = _provision_project(container, tmp_path)
    resp = client.get(
        f"/projects/{project_id}/governance/branches",
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "GOVERNANCE_DISABLED"


# ---------------------------------------------------------------------------
# Branch creation reaches the real use case
# ---------------------------------------------------------------------------


def test_create_branch_reaches_real_use_case(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    resp = client.post(
        f"/projects/{project_id}/governance/branches",
        json={
            "plan_id": plan_id, "name": "seg-1",
            "branch_type": "segment_challenger",
            "base_plan_version_id": pv_id,
            "head_plan_version_id": pv_id,
            "branch_point_step_id": "sample-definition",
            "created_reason": "test",
            "segment_filter_spec": {"rules": [
                {"column": "channel", "operator": "==", "value": "online", "reason": "test"},
            ]},
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "seg-1"
    assert data["branch_type"] == "segment_challenger"
    # The branch row is persisted.
    with container.uow_factory.read_only(project_id) as uow:
        branch = uow.branches.get_branch(data["branch_id"])
    assert branch is not None
    assert branch["plan_id"] == plan_id


def test_create_branch_persists_description(governance_env, tmp_path):
    """Client-supplied description must round-trip (F3)."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    resp = client.post(
        f"/projects/{project_id}/governance/branches",
        json={
            "plan_id": plan_id, "name": "seg-desc",
            "branch_type": "segment_challenger",
            "base_plan_version_id": pv_id,
            "head_plan_version_id": pv_id,
            "branch_point_step_id": "sample-definition",
            "created_reason": "test",
            "description": "description-roundtrip",
            "segment_filter_spec": {"rules": [
                {"column": "channel", "operator": "==", "value": "online", "reason": "test"},
            ]},
        },
    )
    assert resp.status_code == 201, resp.text
    with container.uow_factory.read_only(project_id) as uow:
        branch = uow.branches.get_branch(resp.json()["branch_id"])
    assert branch is not None
    assert branch["description"] == "description-roundtrip"


def test_create_branch_head_version_mismatch_rejected(governance_env, tmp_path):
    """head_plan_version_id that disagrees with the derived head is rejected
    instead of silently discarded (F3)."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    resp = client.post(
        f"/projects/{project_id}/governance/branches",
        json={
            "plan_id": plan_id, "name": "seg-bad",
            "branch_type": "segment_challenger",
            "base_plan_version_id": pv_id,
            "head_plan_version_id": "some-other-version",
            "branch_point_step_id": "sample-definition",
            "created_reason": "test",
            "segment_filter_spec": {"rules": [
                {"column": "channel", "operator": "==", "value": "online", "reason": "test"},
            ]},
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "STALE_HEAD_VERSION"


def test_create_branch_requires_branch_type(governance_env, tmp_path):
    """branch_type is required — the old 'challenger' default is never valid
    and must not silently succeed (F3)."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    resp = client.post(
        f"/projects/{project_id}/governance/branches",
        json={
            "plan_id": plan_id, "name": "seg-missing-type",
            "base_plan_version_id": pv_id,
            "head_plan_version_id": pv_id,
            "branch_point_step_id": "sample-definition",
            "created_reason": "test",
        },
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Comparison creation and refresh
# ---------------------------------------------------------------------------


def _seed_run_with_evidence(container, project_id, root, plan_id, pv_id, step_id, evidence_kind, payload):
    """Insert a succeeded run + run_step + artifact + lineage + evidence edge/artifact."""
    import sqlite3
    db_path = root / "project.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    now = utc_now_iso()
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, run_scope, branch_id, force, "
        "created_at, started_at, heartbeat_at, finished_at) "
        "VALUES (?, ?, 'succeeded', 'full_plan', NULL, 0, ?, ?, ?, ?)",
        (run_id, pv_id, now, now, now, now),
    )
    rs_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
        (rs_id, run_id, step_id, pv_id, now, now),
    )
    art_id = str(uuid.uuid4())
    art_path = root / "artifacts" / f"{art_id}.json"
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text(json.dumps(payload))
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, physical_hash, "
        "logical_hash, media_type, schema_version, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (art_id, "woe_iv_evidence", "report", str(art_path.relative_to(root)),
         f"ph-{art_id}", "lh", "application/json", "cardre.woe_iv_evidence.v1", now,
         json.dumps({"schema_version": "cardre.woe_iv_evidence.v1"})),
    )
    conn.execute(
        "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, "
        "artifact_id, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, rs_id, pv_id, step_id, art_id, now),
    )
    conn.commit()
    conn.close()
    _ = json_logical_hash  # noqa: F841
    return run_id


def test_comparison_refresh_consumes_matched_evidence(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    branch_id = _create_branch_via_use_case(container, project_id, plan_id, pv_id)

    # Seed a woe-iv evidence artifact for the baseline run.
    woe_payload = {"variables": [{"variable": "income", "iv": 0.5, "bins": [], "warnings": []}]}
    _seed_run_with_evidence(
        container, project_id, root, plan_id, pv_id, "final-woe-iv",
        "woe_iv_evidence", woe_payload,
    )

    # Create a comparison.
    resp = client.post(
        f"/projects/{project_id}/governance/comparisons",
        json={
            "plan_id": plan_id, "baseline_branch_id": branch_id,
            "challenger_branch_ids": [], "created_reason": "test",
        },
    )
    assert resp.status_code == 201, resp.text
    comparison_id = resp.json()["comparison_id"]

    # Refresh — must consume the returned dict representation without .get()/dataclass failures.
    resp2 = client.post(
        f"/projects/{project_id}/governance/comparisons/{comparison_id}/refresh",
    )
    assert resp2.status_code == 200, resp2.text


# ---------------------------------------------------------------------------
# Champion assignment
# ---------------------------------------------------------------------------


def test_champion_assignment_works_through_route(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    branch_id = _create_branch_via_use_case(container, project_id, plan_id, pv_id)

    # Seed a comparison snapshot the champion assignment references.
    now = utc_now_iso()
    comparison_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    comparison_artifact_id = str(uuid.uuid4())
    import sqlite3
    conn = sqlite3.connect(str(root / "project.sqlite"))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO branch_comparisons "
        "(comparison_id, project_id, plan_id, baseline_branch_id, comparison_spec_json, "
        " latest_snapshot_id, latest_ready, latest_readiness_json, created_at, created_reason) "
        "VALUES (?, ?, ?, ?, '{}', ?, 1, '{\"ready\": true}', ?, ?)",
        (comparison_id, project_id, plan_id, branch_id, snapshot_id, now, "test"),
    )
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, physical_hash, "
        "logical_hash, media_type, schema_version, created_at, metadata_json) "
        "VALUES (?, 'comparison', 'report', ?, 'ph', 'lh', 'application/json', '', ?, '{}')",
        (comparison_artifact_id, f"comparisons/{comparison_artifact_id}.json", now),
    )
    conn.execute(
        "INSERT INTO branch_comparison_snapshots "
        "(comparison_snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id, "
        " readiness_json, created_at, created_reason) VALUES (?, ?, ?, ?, ?, '{\"ready\": true}', ?, ?)",
        (snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id, now, "test"),
    )
    # The snapshot must include the branch's head plan version.
    with container.uow_factory.read_only(project_id) as uow:
        branch = uow.branches.get_branch(branch_id)
    head_pv_id = branch["head_plan_version_id"]
    conn.execute(
        "INSERT INTO comparison_snapshot_plan_versions "
        "(comparison_snapshot_id, plan_version_id, branch_id) VALUES (?, ?, ?)",
        (snapshot_id, head_pv_id, branch_id),
    )
    conn.commit()
    conn.close()

    resp = client.post(
        f"/projects/{project_id}/governance/champion/assign",
        json={
            "plan_id": plan_id, "branch_id": branch_id,
            "comparison_id": comparison_id, "comparison_snapshot_id": snapshot_id,
            "assigned_reason": "best performer",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["assignment"]["champion_branch_id"] == branch_id


def test_get_champion_plan_level_returns_assignment(governance_env, tmp_path):
    """GET champion with a plan_id returns the plan-scoped assignment."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    branch_id = _create_branch_via_use_case(container, project_id, plan_id, pv_id)

    # Insert a champion assignment directly for this plan.
    import sqlite3

    from cardre.domain.diagnostics import utc_now_iso
    conn = sqlite3.connect(str(root / "project.sqlite"))
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO champion_assignments (champion_assignment_id, project_id, plan_id, "
        " scope_type, scope_key, champion_branch_id, comparison_id, comparison_snapshot_id, "
        " comparison_artifact_id, selected_plan_version_id, assigned_reason, assigned_by, assigned_at) "
        "VALUES (?, ?, ?, 'plan', ?, ?, '', '', '', ?, 'test', NULL, ?)",
        (str(uuid.uuid4()), project_id, plan_id, plan_id, branch_id, pv_id, now),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/projects/{project_id}/governance/champion?plan_id={plan_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment"] is not None
    assert resp.json()["assignment"]["champion_branch_id"] == branch_id


def test_get_champion_project_level_returns_assignment(governance_env, tmp_path):
    """GET champion without plan_id returns the project-scoped assignment —
    the route must not 422 on a missing plan_id (F3)."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id = _seed_branchable_plan(container, project_id)
    branch_id = _create_branch_via_use_case(container, project_id, plan_id, pv_id)

    import sqlite3

    from cardre.domain.diagnostics import utc_now_iso
    conn = sqlite3.connect(str(root / "project.sqlite"))
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO champion_assignments (champion_assignment_id, project_id, plan_id, "
        " scope_type, scope_key, champion_branch_id, comparison_id, comparison_snapshot_id, "
        " comparison_artifact_id, selected_plan_version_id, assigned_reason, assigned_by, assigned_at) "
        "VALUES (?, ?, ?, 'project', ?, ?, '', '', '', ?, 'test', NULL, ?)",
        (str(uuid.uuid4()), project_id, plan_id, project_id, branch_id, pv_id, now),
    )
    conn.commit()
    conn.close()

    resp = client.get(f"/projects/{project_id}/governance/champion")
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment"] is not None
    assert resp.json()["assignment"]["champion_branch_id"] == branch_id


def test_get_champion_no_assignment_returns_none(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    resp = client.get(f"/projects/{project_id}/governance/champion")
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment"] is None


def _seed_mb_plan_and_review(container, project_id, status="pending", notes="initial",
                              step_id="manual-binning"):
    """Seed a committed plan with a manual-binning step and create a review."""
    steps = [
        StepSpec(step_id="automatic-binning", node_type="cardre.automatic_binning",
                 node_version="1", category="fit", params={"max_bins": 20},
                 params_hash=json_logical_hash({"max_bins": 20}),
                 parent_step_ids=[], branch_label="", position=0,
                 canonical_step_id="automatic-binning"),
        StepSpec(step_id=step_id, node_type="cardre.manual_binning",
                 node_version="1", category="refinement", params={"overrides": []},
                 params_hash=json_logical_hash({"overrides": []}),
                 parent_step_ids=["automatic-binning"], branch_label="", position=1,
                 canonical_step_id=step_id),
    ]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        review = uow.manual_binning.create_review(
            plan_version_id=pv_id, step_id=step_id, status=status,
            reviewer_notes=notes, affected_downstream_step_ids=["apply-woe"],
        )
        uow.commit()
        return plan_id, pv_id, review.review_id


# ---------------------------------------------------------------------------
# Manual-binning review list/get/update PATCH semantics
# ---------------------------------------------------------------------------


def test_manual_binning_review_list_and_get(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id, rid = _seed_mb_plan_and_review(container, project_id)
    resp = client.get(
        f"/projects/{project_id}/governance/manual-binning-reviews",
    )
    assert resp.status_code == 200
    assert any(r["review_id"] == rid for r in resp.json())
    resp2 = client.get(
        f"/projects/{project_id}/governance/manual-binning-reviews/{rid}",
    )
    assert resp2.status_code == 200
    assert resp2.json()["review_id"] == rid


def test_manual_binning_patch_notes_only_preserves_status(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id, rid = _seed_mb_plan_and_review(container, project_id, status="pending", notes="orig")
    resp = client.patch(
        f"/projects/{project_id}/governance/manual-binning-reviews/{rid}",
        json={"reviewer_notes": "updated notes"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reviewer_notes"] == "updated notes"
    assert data["status"] == "pending"  # preserved


def test_manual_binning_patch_status_only_preserves_notes(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id, rid = _seed_mb_plan_and_review(container, project_id, status="pending", notes="keep me")
    resp = client.patch(
        f"/projects/{project_id}/governance/manual-binning-reviews/{rid}",
        json={"status": "approved"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "approved"
    assert data["reviewer_notes"] == "keep me"  # preserved


def test_manual_binning_patch_invalid_status_returns_400(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    plan_id, pv_id, rid = _seed_mb_plan_and_review(container, project_id)
    resp = client.patch(
        f"/projects/{project_id}/governance/manual-binning-reviews/{rid}",
        json={"status": "bogus"},
    )
    assert resp.status_code == 400


def test_manual_binning_patch_nonexistent_review_returns_404(governance_env, tmp_path):
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    resp = client.patch(
        f"/projects/{project_id}/governance/manual-binning-reviews/nonexistent",
        json={"status": "approved"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "REVIEW_NOT_FOUND"


def test_manual_binning_edit_atomic(governance_env, tmp_path):
    """POST edit creates a draft plan version and review in one transaction."""
    client, container = governance_env
    project_id, root = _provision_project(container, tmp_path)
    # Seed a committed plan with a manual-binning step.
    steps = [
        StepSpec(step_id="automatic-binning", node_type="cardre.automatic_binning",
                 node_version="1", category="fit", params={"max_bins": 20},
                 params_hash=json_logical_hash({"max_bins": 20}),
                 parent_step_ids=[], branch_label="", position=0,
                 canonical_step_id="automatic-binning"),
        StepSpec(step_id="manual-binning", node_type="cardre.manual_binning",
                 node_version="1", category="refinement", params={"overrides": []},
                 params_hash=json_logical_hash({"overrides": []}),
                 parent_step_ids=["automatic-binning"], branch_label="", position=1,
                 canonical_step_id="manual-binning"),
    ]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    resp = client.post(
        f"/projects/{project_id}/governance/apply-manual-binning-edit",
        json={
            "plan_version_id": pv_id, "step_id": "manual-binning",
            "overrides": [{"variable": "income", "action": "merge_bins"}],
            "reviewer_notes": "edit", "status": "pending",
            "affected_downstream_step_ids": [],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    new_pv_id = data["new_plan_version_id"]
    review_id = data["review_id"]
    with container.uow_factory.read_only(project_id) as uow:
        new_pv = uow.plans.get_version(new_pv_id)
        assert new_pv is not None and new_pv.is_committed is False
        review = uow.manual_binning.get_review(review_id)
        assert review is not None and review.plan_version_id == new_pv_id
