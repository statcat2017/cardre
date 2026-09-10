"""Behavior-level regression for unexpected HTTP failures (Slice 2).

An unhandled exception (here an ordinary ``ValueError`` raised by a test-only
route) must produce a structured JSON 500 in the closed error vocabulary, with
no HTML body and no raw traceback or sensitive exception detail leaking into
the response, while the traceback is still logged server-side.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.errors import ErrorCode


@pytest.fixture
def boom_app(monkeypatch, tmp_path):
    """A configured app plus a test-only route that raises a ValueError."""
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)

    @app.get("/__test/boom", include_in_schema=False)
    def _boom() -> None:
        raise ValueError("SENSITIVE_SECRET_123")  # noqa: TRY002

    client = TestClient(app, raise_server_exceptions=False)
    return client


def test_unexpected_value_error_returns_structured_json_500(boom_app, caplog):
    client = boom_app
    with caplog.at_level(logging.ERROR, logger="cardre.api.errors"):
        resp = client.get("/__test/boom")

    # 500 and a structured JSON body, never HTML.
    assert resp.status_code == 500
    content_type = resp.headers.get("content-type", "")
    assert "application/json" in content_type
    assert "text/html" not in content_type

    # Closed vocabulary envelope.
    payload = resp.json()
    assert payload["detail"]["code"] == ErrorCode.INTERNAL_SERVER_ERROR
    assert payload["detail"]["message"]

    # No raw traceback or sensitive exception detail leaks into the response.
    assert "Traceback" not in resp.text
    assert "SENSITIVE_SECRET_123" not in resp.text
    assert "ValueError" not in resp.text

    # The traceback is still logged server-side.
    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
    assert any(
        "SENSITIVE_SECRET_123" in (rec.exc_text or "")
        for rec in caplog.records
    )
