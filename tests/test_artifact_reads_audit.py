"""Regression tests for the artifact-read audit whitelist.

The approved-module list in ``scripts/audit_artifact_reads.py`` is part of
``make preflight`` and must contain only modules that exist today and are the
documented authorities for direct artifact I/O (see
docs/architecture/artifact-evidence-access.md).
"""

from __future__ import annotations

from pathlib import Path

from scripts import audit_artifact_reads as audit  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_approved_modules_exist_in_repo():
    for module in audit.DEFAULT_APPROVED_MODULES:
        assert (REPO_ROOT / module).exists(), (
            f"Approved artifact-read module {module!r} does not exist; "
            "remove it from DEFAULT_APPROVED_MODULES"
        )


def test_approved_modules_are_the_documented_authorities():
    """Only the evidence packages and the filesystem artifact store are
    allowed to do direct artifact I/O."""
    assert set(audit.DEFAULT_APPROVED_MODULES) == {
        "cardre/domain/evidence/",
        "cardre/adapters/evidence/",
        "cardre/adapters/filesystem/artifact_store.py",
    }


def test_no_obsolete_paths_in_approved_modules():
    """Legacy/deleted modules must not appear in the approved list."""
    obsolete = {
        "cardre/artifacts.py",
        "cardre/evidence.py",
        "cardre/_evidence/",
        "cardre/modeling/serialization.py",
    }
    assert not obsolete.intersection(audit.DEFAULT_APPROVED_MODULES), (
        "DEFAULT_APPROVED_MODULES still lists an obsolete/deleted module"
    )


def test_suppression_reasons_are_not_stale():
    """No suppression reason may reference deleted test files."""
    assert "serialization-compatibility-test" not in audit.ALLOWED_SUPPRESSION_REASONS
