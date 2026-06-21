"""Guardrail: ban direct artifact file reads outside the evidence module.

Direct ``json.loads(store.artifact_path(...).read_text())`` bypasses the
typed ``ArtifactEvidenceReader`` and couples callers to file-layout details.
This test scans the backend source tree for the pattern and only permits
it in approved modules.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules where direct artifact reads are approved.
APPROVED_PATTERNS: set[str] = {
    "cardre/evidence.py",
    "cardre/_evidence/",
}

# Existing violations that should be migrated to ArtifactEvidenceReader
# over subsequent PRs. New violations will fail this test.
_EXISTING_VIOLATORS: set[str] = {
    "cardre/nodes/build/export.py",
    "cardre/nodes/build/freeze.py",
    "cardre/nodes/build/models.py",
    "cardre/nodes/build/selection.py",
    "cardre/nodes/ensembles.py",
    "cardre/nodes/explainability.py",
    "cardre/nodes/fairness.py",
    "cardre/nodes/feature_selection.py",
    "cardre/nodes/validate/apply.py",
    "cardre/services/manual_binning_service.py",
}

DIRECT_READ_RE = re.compile(
    r"json\.loads\s*\(.*artifact_path.*read_text|"
    r"artifact_path\(.*\)\.read_text\(\)|"
    r"path\.read_text\(\)  #.*artifact_path",
)


def _source_files() -> list[Path]:
    """Return all tracked Python source files under cardre/."""
    result = subprocess.run(
        ["git", "ls-files", "--", "cardre/*.py", "cardre/**/*.py"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    return [REPO_ROOT / f for f in result.stdout.strip().splitlines() if f]


def _has_direct_read(path: Path) -> bool:
    """Check whether *path* contains a direct artifact read pattern."""
    try:
        text = path.read_text()
    except (FileNotFoundError, UnicodeDecodeError):
        return False
    return bool(DIRECT_READ_RE.search(text))


def test_no_new_direct_artifact_reads():
    """New direct artifact file reads must live in an approved module.

    Existing violations are documented in _EXISTING_VIOLATORS and will
    be migrated over subsequent PRs. Any new violation fails the test.
    """
    new_violations: list[str] = []
    for f in _source_files():
        if not _has_direct_read(f):
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(a) for a in APPROVED_PATTERNS):
            continue
        if rel in _EXISTING_VIOLATORS:
            continue
        new_violations.append(rel)

    assert not new_violations, (
        "New direct artifact reads found outside approved modules. "
        "Use ``ArtifactEvidenceReader`` instead or add the module to "
        "APPROVED_PATTERNS or _EXISTING_VIOLATORS.\n"
        + "\n".join(f"  {v}" for v in new_violations)
    )
