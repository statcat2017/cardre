#!/usr/bin/env python3
"""Per-package Python coverage threshold enforcement.

Reads the ``coverage.json`` emitted by ``pytest --cov-report=json`` (run from
the repo root) and enforces a per-package statement-coverage floor for the
named production packages, plus a global 60% backstop.

Per-package thresholds are chosen to sit comfortably below current measured
coverage so they act as regression guards rather than aspirational targets.
Raising a floor must be justified by an accompanying coverage increase; see
CONTRIBUTING.md and ADR 0018.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# package prefix -> minimum % statement coverage.
# Measured as of Batch 4C closeout (all comfortably above these floors).
PACKAGE_FLOORS: dict[str, float] = {
    "cardre/domain": 75.0,
    "cardre/application": 80.0,
    "cardre/adapters": 80.0,
    "cardre/api": 80.0,
    "cardre/nodes": 70.0,
    "cardre/modeling": 75.0,
    "cardre/bootstrap": 75.0,
    "sidecar": 70.0,
}

# Global backstop retained across the whole measured surface.
GLOBAL_FLOOR: float = 60.0

REPO_ROOT = Path(__file__).resolve().parent.parent


def assign_package(rel_path: str) -> str | None:
    """Map a coverage file path to its tracked package, if any.

    ``sidecar/*`` is its own package; everything else under ``cardre/`` is
    assigned by its first-level subpackage (``cardre/domain``, etc.). Files not
    under a configured package are ignored rather than binned into a
    mismatched bucket.
    """
    if rel_path.startswith("sidecar/"):
        return "sidecar"
    if rel_path.startswith("cardre/"):
        parts = rel_path.split("/")
        # Only first-level subpackages (cardre/domain/...) are tracked, not
        # bare cardre/*.py modules.
        if len(parts) >= 3:
            return f"{parts[0]}/{parts[1]}"
    return None


def measure(data: dict) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Return per-package (covered, total) statement counts and global totals."""
    per_package: dict[str, list[tuple[int, int]]] = {}
    global_total = 0
    global_covered = 0
    for path, info in data["files"].items():
        summary = info["summary"]
        total = int(summary["num_statements"])
        covered_statements = int(summary["covered_lines"])
        if total <= 0:
            continue
        global_total += total
        global_covered += covered_statements
        pkg = assign_package(path)
        if pkg is not None:
            per_package.setdefault(pkg, []).append((covered_statements, total))
    return (
        {p: (sum(c for c, _ in v), sum(t for _, t in v)) for p, v in per_package.items()},
        global_covered,
        global_total,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage",
        default=str(REPO_ROOT / "coverage.json"),
        help="Path to coverage.json (default: <repo>/coverage.json)",
    )
    args = parser.parse_args()

    coverage_path = Path(args.coverage)
    if not coverage_path.is_file():
        print(
            f"ERROR: coverage report not found at {coverage_path}. "
            "Run `make test-python-ci` (or pytest with --cov-report=json) first.",
            file=sys.stderr,
        )
        return 2

    with coverage_path.open() as f:
        data = json.load(f)

    package_totals, global_covered, global_total = measure(data)

    failures: list[str] = []
    global_pct = 100.0 * global_covered / max(global_total, 1)
    if global_pct < GLOBAL_FLOOR:
        failures.append(
            f"global: {global_pct:.1f}% below {GLOBAL_FLOOR:.0f}%"
        )

    for pkg, floor in sorted(PACKAGE_FLOORS.items()):
        totals = package_totals.get(pkg)
        if totals is None:
            failures.append(f"{pkg}: no measured coverage (package not found in report)")
            continue
        covered, total = totals
        pct = 100.0 * covered / max(total, 1)
        if pct < floor:
            failures.append(f"{pkg}: {pct:.1f}% below {floor:.0f}%")

    if failures:
        print("FAIL: coverage thresholds not met:")
        for msg in failures:
            print(f"  - {msg}")
        print(f"  global coverage: {global_pct:.1f}%")
        for pkg, (covered, total) in sorted(package_totals.items()):
            print(f"    {pkg}: {100.0 * covered / max(total, 1):.1f}%")
        return 1

    parts = [f"PASS: global {global_pct:.1f}% (>= {GLOBAL_FLOOR:.0f}%)"]
    for pkg, (covered, total) in sorted(package_totals.items()):
        parts.append(f"{pkg} {100.0 * covered / max(total, 1):.1f}%")
    print("; ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
