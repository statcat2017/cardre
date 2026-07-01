"""Tests for branch endpoints — governance-gated.

Tests override the governance dependency by monkeypatching ``CardreConfig``
to simulate both enabled and disabled states.
"""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_branch_data(store):
    """Create project, plan, plan versions, and branch."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    base_pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (base_pv_id, plan_id, now, "Base"),
    )
    head_pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 2, 0, ?, ?)",
        (head_pv_id, plan_id, now, "Head"),
    )
    branch_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_branches "
        "(branch_id, project_id, plan_id, name, branch_type, status, "
        " base_plan_version_id, head_plan_version_id, created_reason, created_at, updated_at) "
        "VALUES (?, ?, ?, 'test-branch', 'challenger', 'active', "
        " ?, ?, 'test', ?, ?)",
        (branch_id, project_id, plan_id, base_pv_id, head_pv_id, now, now),
    )
    return project_id, plan_id, branch_id, base_pv_id, head_pv_id, store, store.root


class TestBranches:
    def test_list_branches_governance_disabled(self, api_client, project_with_branch_data):
        """Without governance, branches return 403."""
        project_id, _, _, _, _, _, root = project_with_branch_data
        resp = api_client.get(
            f"/projects/{project_id}/branches",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["code"] == "GOVERNANCE_DISABLED"

    def test_list_branches_governance_enabled(self, api_client, project_with_branch_data, monkeypatch):
        """With governance enabled, branches list successfully."""
        project_id, _, _, _, _, _, root = project_with_branch_data
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": True,
                "launch_mode": True,
                "stale_heartbeat_seconds": 300,
                "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1",
                "api_port": 8752,
                "registry_path": "/tmp",
            }
        )())
        resp = api_client.get(
            f"/projects/{project_id}/branches",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "branches" in data

    def test_get_branch_governance_enabled(self, api_client, project_with_branch_data, monkeypatch):
        project_id, _, branch_id, _, _, _, root = project_with_branch_data
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": True,
                "launch_mode": True,
                "stale_heartbeat_seconds": 300,
                "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1",
                "api_port": 8752,
                "registry_path": "/tmp",
            }
        )())
        resp = api_client.get(
            f"/projects/{project_id}/branches/{branch_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["branch_id"] == branch_id

    def test_get_branch_not_found(self, api_client, project_with_branch_data, monkeypatch):
        project_id, _, _, _, _, _, root = project_with_branch_data
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": True,
                "launch_mode": True,
                "stale_heartbeat_seconds": 300,
                "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1",
                "api_port": 8752,
                "registry_path": "/tmp",
            }
        )())
        resp = api_client.get(
            f"/projects/{project_id}/branches/nonexistent",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "BRANCH_NOT_FOUND"
