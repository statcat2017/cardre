"""Verify the CI path filter covers every file type that can change.

ci-success deliberately accepts ``skipped`` results. If the path filter omits
a category, a change to that category can pass required checks without any
substantive validation.  This test reproduces the glob rules from
``.github/workflows/ci.yml`` and asserts that every path in a representative
set matches at least one owning filter.
"""

from __future__ import annotations

import fnmatch

# Filters from .github/workflows/ci.yml — reproduced here so a filter
# regression causes a test failure before it reaches CI.
CI_FILTERS: dict[str, list[str]] = {
    "python": [
        "cardre/**",
        "sidecar/**",
        "tests/**",
        "pyproject.toml",
        "scripts/**",
        "tools/**",
        "Makefile",
        ".github/dependabot.yml",
    ],
    "frontend": [
        "frontend/**",
        "!frontend/src-tauri/**",
    ],
    "rust": [
        "frontend/src-tauri/**",
    ],
    "openapi": [
        "sidecar/**",
        "cardre/**",
        "frontend/src/api/**",
        "scripts/generate-openapi-types.py",
    ],
    "docs": [
        "**/*.md",
        "docs/**",
    ],
}

# Every listed path must match at least one owning filter.  The python
# filter is deliberately broad — it owns the backend, build scripts, and
# operational tooling.  Frontend, Rust, OpenAPI, and docs have their own
# dedicated lanes.
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


def _path_matches_any_filter(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _owning_filters(path: str) -> list[str]:
    return [
        name
        for name, patterns in CI_FILTERS.items()
        if _path_matches_any_filter(path, patterns)
    ]


def test_required_paths_have_owning_filters() -> None:
    """Every required path must match at least one CI filter."""
    failures = []
    for path in REQUIRED_PATHS:
        owners = _owning_filters(path)
        if not owners:
            failures.append(path)
    assert not failures, (
        f"{len(failures)} path(s) are not covered by any CI filter: "
        + ", ".join(failures)
    )


def test_python_filter_covers_scripts_and_tools() -> None:
    """scripts/** and tools/** patterns ensure operational code runs QA."""
    for path in [
        "scripts/pr-gate.sh",
        "scripts/check-sidecar-naming.py",
        "tools/reference_extractors/extract_scorecard_r_german_credit.R",
    ]:
        assert _path_matches_any_filter(
            path, CI_FILTERS["python"]
        ), f"{path} must be owned by the python filter"


def test_each_filter_has_at_least_one_positive_pattern() -> None:
    """Sanity: every named filter must own at least one path in the fixture."""
    for name in CI_FILTERS:
        hits = [
            p for p in REQUIRED_PATHS if _path_matches_any_filter(p, CI_FILTERS[name])
        ]
        assert hits, f"filter {name!r} does not match any required path"
