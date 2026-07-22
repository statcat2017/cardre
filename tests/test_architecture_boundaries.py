"""Architecture boundary tests for the Cardre hexagonal rewrite."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_importlinter_passes() -> None:
    """Run import-linter and assert exit 0."""
    result = subprocess.run(
        ["lint-imports"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"import-linter failed:\n{result.stdout}\n{result.stderr}"
    )


def test_new_packages_importable() -> None:
    """Assert the new hexagonal packages can be imported."""
    import cardre.adapters  # noqa: F401
    import cardre.adapters.sqlite  # noqa: F401
    import cardre.adapters.system  # noqa: F401
    import cardre.application  # noqa: F401
    import cardre.application.ports  # noqa: F401
    import cardre.bootstrap  # noqa: F401
    import cardre.bootstrap.build_app  # noqa: F401
    import cardre.bootstrap.container  # noqa: F401
    import cardre.bootstrap.settings  # noqa: F401
