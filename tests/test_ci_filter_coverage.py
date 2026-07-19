"""Verify every required file path is covered by at least one CI filter.

Loads path-filter definitions directly from ``.github/workflows/ci.yml`` so
that any change to the workflow is automatically reflected here.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

REQUIRED_PATHS = [
    "tools/reference_extractors/extract_scorecard_r_german_credit.R",
    "scripts/pr-gate.sh",
    "scripts/check-sidecar-naming.py",
    ".github/dependabot.yml",
    "Makefile",
    "docs/architecture/reporting.md",
    "frontend/src/components/ProjectView.tsx",
    "frontend/src-tauri/src/main.rs",
    "cardre/execution/run_lifecycle.py",
]


def _parse_filters() -> dict[str, list[str]]:
    """Parse the ``dorny/paths-filter`` block from ``ci.yml``."""
    text = WORKFLOW_PATH.read_text()

    m = re.search(r"^\s+filters:\s*\|\s*$", text, re.MULTILINE)
    assert m, "Could not find 'filters: |' in ci.yml"

    lines = text[m.end() :].split("\n")

    filters: dict[str, list[str]] = {}
    current: str | None = None

    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()

        if indent < 12:
            break  # end of literal block
        if indent == 12:
            current = stripped.rstrip(":")
            filters[current] = []
        elif indent == 14 and current and stripped.startswith("- "):
            pattern = stripped[2:].strip().strip("'")
            filters[current].append(pattern)

    return filters


def _path_matches(path: str, pattern: str) -> bool:
    """dorny/paths-filter glob match using PurePosixPath suffix semantics."""
    from fnmatch import fnmatch

    if pattern.startswith("!"):
        return not fnmatch(path, pattern[1:])
    return fnmatch(path, pattern)


def _owning_filters(path: str, filters: dict[str, list[str]]) -> list[str]:
    return [
        name
        for name, patterns in filters.items()
        if any(_path_matches(path, p) for p in patterns)
    ]


def test_required_paths_have_owning_filters() -> None:
    filters = _parse_filters()
    failures = []
    for path in REQUIRED_PATHS:
        if not _owning_filters(path, filters):
            failures.append(path)
    assert not failures, (
        f"{len(failures)} path(s) not covered by any CI filter: "
        + ", ".join(failures)
    )


def test_each_substantive_filter_owns_at_least_one_required_path() -> None:
    """Every substantive validation lane must own at least one required path.

    The ``ci`` filter is a meta-filter for the workflow itself; ``sidecar``
    overlaps with ``python``+``rust``.  Only the document-owning lanes are
    checked here.
    """
    filters = _parse_filters()
    for name in ("python", "frontend", "rust", "openapi", "docs"):
        patterns = filters.get(name, [])
        hits = [p for p in REQUIRED_PATHS if any(_path_matches(p, pat) for pat in patterns)]
        assert hits, f"filter {name!r} matches none of the required paths"
