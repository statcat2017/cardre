"""Tests for ProjectStore connection lifecycle."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.db import ProjectStore


def test_api_request_closes_store_after_dependency_exit(raw_project_path, api_client, store, monkeypatch):
    from cardre.config import CardreConfig
    from cardre.services.project_resolver import ProjectResolver

    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Lifecycle Project", now, "0.2.0"),
    )
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)
    store.close()

    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    monkeypatch.setattr(ProjectStore, "close", close_spy)

    resp = api_client.get(
        f"/projects/{project_id}/runs",
        headers={"X-Project-Id": project_id},
    )

    assert resp.status_code == 200, resp.text
    assert close_calls == [str(store.root)]


def test_project_store_context_manager_closes_on_exit(store, monkeypatch):
    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    monkeypatch.setattr(ProjectStore, "close", close_spy)

    with ProjectStore(store.root) as opened:
        assert opened.root == store.root
        opened.execute("SELECT 1")

    assert close_calls == [str(store.root)]


def test_api_requests_use_distinct_sqlite_connections(api_client, tmp_path, monkeypatch):
    project_root = tmp_path / "isolated.cardre"
    create_resp = api_client.post(
        "/projects",
        json={"name": "Isolated Project", "path": str(project_root)},
    )
    assert create_resp.status_code == 201, create_resp.text
    project_id = create_resp.json()["project_id"]

    connections: list[object] = []
    original_connect = ProjectStore._connect

    def connect_spy(self):
        conn = original_connect(self)
        connections.append(conn)
        return conn

    monkeypatch.setattr(ProjectStore, "_connect", connect_spy)

    for _ in range(2):
        resp = api_client.get(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200, resp.text

    assert len({id(conn) for conn in connections}) == 2


def test_api_dependency_closes_store_on_handler_error(api_client, tmp_path, monkeypatch):

    project_root = tmp_path / "error-path.cardre"
    create_resp = api_client.post(
        "/projects",
        json={"name": "Error Path Project", "path": str(project_root)},
    )
    assert create_resp.status_code == 201, create_resp.text
    project_id = create_resp.json()["project_id"]

    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    def boom(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ProjectStore, "close", close_spy)
    from cardre.store.run_repo import RunRepository
    monkeypatch.setattr(RunRepository, "list_for_project", boom)

    with pytest.raises(RuntimeError, match="boom"):
        api_client.get(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
        )

    assert close_calls == [str(project_root)]
