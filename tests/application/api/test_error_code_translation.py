"""HTTP-level regression tests for the ErrorCode closed vocabulary.

These pin Phase 4 behaviour changes: the global ``cardre_error_handler`` now
applies ``translate_domain_error`` to every unwrapped ``CardreError``, so a
missing project on a governance route returns 404 (not the old 500), and the
domain-error map owns the status for every translated code.
"""

from __future__ import annotations

import pytest

from cardre.api.errors import _DOMAIN_ERROR_MAP, translate_domain_error
from cardre.domain.errors import CardreError


def test_unwrapped_project_not_found_returns_404(monkeypatch, tmp_path):
    """A governance list endpoint for a nonexistent project id returns 404
    with PROJECT_NOT_FOUND via the global handler (was 500)."""
    monkeypatch.setenv("CARDRE_GOVERNANCE", "1")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))

    from fastapi.testclient import TestClient

    from cardre.api.app import create_app
    from cardre.bootstrap.container import build_container
    from cardre.bootstrap.settings import Settings

    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    client = TestClient(app)

    resp = client.get("/projects/nonexistent-project-id/governance/branches")
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
        ("BRANCH_SCOPE_MISMATCH", 409),
        ("BRANCH_NOT_ACTIVE", 409),
        ("COMPARISON_NOT_READY", 400),
        ("CANONICAL_MANIFEST_MISSING", 404),
    ],
)
def test_explicit_domain_status_overrides_map_default(code: str, explicit_status: int) -> None:
    """The map supplies defaults but must not erase contextual domain status."""
    api_error = translate_domain_error(
        CardreError("message", code=code, status_code=explicit_status),
    )
    assert api_error.code == _DOMAIN_ERROR_MAP[code][0]
    assert api_error.status_code == explicit_status
