"""HTTP-level regression tests for the ErrorCode closed vocabulary.

These pin behaviour changes: the global ``cardre_error_handler`` now
applies ``translate_domain_error`` to every unwrapped ``CardreError``, and the
domain-error map owns the status for every translated code.
"""

from __future__ import annotations

import pytest

from cardre.api.errors import _DOMAIN_ERROR_MAP, translate_domain_error
from cardre.domain.errors import CardreError, ErrorCode


def test_unwrapped_project_not_found_returns_404(monkeypatch, tmp_path):
    """A plans list endpoint for a nonexistent project id returns 404
    with PROJECT_NOT_FOUND via the global handler (was 500)."""
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))

    from fastapi.testclient import TestClient

    from cardre.api.app import create_app
    from cardre.bootstrap.container import build_container
    from cardre.bootstrap.settings import Settings

    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    client = TestClient(app)

    resp = client.get("/projects/nonexistent-project-id/plans")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.parametrize("key", sorted(_DOMAIN_ERROR_MAP))
def test_translate_domain_error_map_entries(key: str) -> None:
    """translate_domain_error returns the mapped (code, status) for each key."""
    code, status = _DOMAIN_ERROR_MAP[key]
    api_error = translate_domain_error(CardreError("message", code=key))
    assert api_error.code == code
    assert api_error.status_code == status


@pytest.mark.parametrize(
    ("code", "explicit_status"),
    [
        ("CANONICAL_MANIFEST_MISSING", 403),
    ],
)
def test_mapped_status_is_authoritative(code: str, explicit_status: int) -> None:
    """The map is the sole status source: a per-call status_code on a mapped
    domain error is ignored, and the mapped status wins."""
    api_error = translate_domain_error(
        CardreError("message", code=code, status_code=explicit_status),
    )
    mapped_status = _DOMAIN_ERROR_MAP[code][1]
    assert api_error.code == _DOMAIN_ERROR_MAP[code][0]
    assert api_error.status_code == mapped_status
    assert api_error.status_code != explicit_status


def test_unmapped_code_passthrough() -> None:
    """Codes not in the map pass through with their own code and status."""
    api_error = translate_domain_error(
        CardreError("message", code=ErrorCode.BAD_REQUEST, status_code=400),
    )
    assert api_error.code == ErrorCode.BAD_REQUEST
    assert api_error.status_code == 400
