from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_branch(store):
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    from cardre.store.branch_repo import BranchRepository
    branch_id = BranchRepository(store).create_branch(
        project_id, plan_id, "champion-test", "challenger",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id, created_reason="test",
    )
    return project_id, plan_id, branch_id, pv_id, store, store.root


class TestChampionRoutes:
    @pytest.fixture(autouse=True)
    def _enable_raw_path(self, raw_project_path):
        pass

    def test_get_champion_governance_disabled(self, api_client, project_with_branch, monkeypatch):
        project_id, _, _, _, _, root = project_with_branch
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": False, "launch_mode": True,
                "stale_heartbeat_seconds": 300, "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1", "api_port": 8752, "registry_path": "/tmp",
            }
        )())
        resp = api_client.get(
            f"/projects/{project_id}/champion",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "GOVERNANCE_DISABLED"

    def test_get_champion_no_assignment(self, api_client, project_with_branch, monkeypatch):
        project_id, _, _, _, _, root = project_with_branch
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": True, "launch_mode": True,
                "stale_heartbeat_seconds": 300, "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1", "api_port": 8752, "registry_path": "/tmp",
            }
        )())
        resp = api_client.get(
            f"/projects/{project_id}/champion",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "assignment" in data
