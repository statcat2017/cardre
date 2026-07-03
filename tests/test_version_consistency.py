"""Tests for version string consistency (#219)."""

from __future__ import annotations


def test_single_version_source_of_truth():
    """All version strings come from cardre._version."""
    from cardre._version import __version__
    assert __version__ == "0.2.0"


def test_health_response_uses_central_version():
    """HealthResponse default matches the central version."""
    from cardre._version import __version__
    from cardre.api.schemas import HealthResponse

    resp = HealthResponse()
    assert resp.version == __version__


def test_fingerprints_uses_central_version():
    """fingerprints.CARDRE_VERSION matches the central version."""
    from cardre._version import __version__
    from cardre.execution.fingerprints import CARDRE_VERSION

    assert __version__ == CARDRE_VERSION


def test_pyproject_version_matches():
    """pyproject.toml version matches the central version."""
    import tomllib
    from pathlib import Path

    from cardre._version import __version__

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == __version__
