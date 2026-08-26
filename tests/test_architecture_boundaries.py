"""Architecture boundary tests for the Cardre hexagonal rewrite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_importlinter_passes() -> None:
    """Run import-linter and assert exit 0."""
    import shutil
    if shutil.which("lint-imports") is None:
        pytest.skip("import-linter not installed (install with: pip install import-linter)")
    result = subprocess.run(
        ["lint-imports"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"import-linter failed:\n{result.stdout}\n{result.stderr}"
    )
