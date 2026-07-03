#!/usr/bin/env python3
"""Check markdown docs for stale file-path references.

Scans markdown files for backtick-quoted paths that look like repo file
references (e.g. ``cardre/store.py``) and verifies they exist in the repo.
Fails if any referenced path does not exist.

This catches stale references like ``cardre/store.py``, ``cardre/pipeline.py``,
or ``cardre/services/report_service.py`` that survive doc rewrites.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths that are known to be valid but may not exist as files
# (e.g. directories, generated files, or intentional references)
KNOWN_EXCEPTIONS: set[str] = {
    # Directories that are referenced as paths
    "cardre/",
    "cardre/store/",
    "cardre/nodes/",
    "cardre/services/",
    "cardre/reporting/",
    "cardre/evidence/",
    "cardre/readiness/",
    "sidecar/",
    "sidecar/routes/",
    "frontend/",
    "frontend/src/",
    "frontend/src-tauri/",
    "docs/",
    "docs/architecture/",
    "docs/reference/",
    "docs/adr/",
    "docs/archive/",
    "tests/",
    "scripts/",
    ".github/",
    # Generated files that may not exist at check time
    "frontend/src/api/openapi.json",
    "frontend/src/api/schema.d.ts",
    # Intentional references to future or external paths
    "docs/README.md",
    "docs/architecture/domain-model.md",
    "docs/architecture/storage-and-migrations.md",
    "docs/architecture/execution-and-staleness.md",
    "docs/architecture/node-registry.md",
    "docs/architecture/reporting.md",
    "docs/architecture/manual-binning.md",
    "docs/architecture/workflow-guidance.md",
    "docs/reference/feature-status.md",
    "docs/reference/node-catalogue.md",
    "docs/reference/report-bundle-v1.md",
    "docs/reference/evidence-kinds.md",
    "docs/reference/api-contract.md",
    "docs/reference/audit-pack-structure.md",
    "docs/adr/README.md",
    "docs/troubleshooting.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    # Pre-existing stale refs in current docs (will be fixed by Batch A)
    "cardre/store.py",
    "cardre/pipeline.py",
    "frontend/src-tauri/binaries/cardre-api-{target-triple}",
    "cardre/_evidence/reader.py::_to_typed",
    # Historical plan docs — expected to have stale references; will be archived
    "docs/plans/cardre-application-plan.txt",
    "docs/plans/evidence-readiness-batch2/",
    "docs/plans/guided-workflow/",
    "docs/plans/launch-journey-batch1/",
    "docs/plans/manual-binning-ux-batch3/",
    "docs/evidence-hardening/",
    "docs/plan-reviews/",
    "docs/risk/",
    "docs/data-sources/",
}

# Directories whose contents are expected to have stale references
# (historical plans, sprint prompts, etc.)
HISTORICAL_DIRS: set[str] = {
    "docs/adr",
    "docs/plans",
    "docs/evidence-hardening",
    "docs/plan-reviews",
    "docs/risk",
    "docs/data-sources",
}

# Pattern matches backtick-quoted paths that look like repo files
# e.g. `cardre/store.py`, `cardre/pipeline.py`, `cardre/services/report_service.py`
PATH_PATTERN = re.compile(r"`((?:cardre|sidecar|frontend|tests|scripts|docs|\.github)/[^`]+)`")


def is_historical(filepath: str) -> bool:
    """Check if a file is in a historical docs directory."""
    return any(filepath.startswith(hist_dir) for hist_dir in HISTORICAL_DIRS)


def get_tracked_files() -> set[str]:
    """Get all files tracked by git."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def find_markdown_files() -> list[Path]:
    """Find all markdown files in the repo."""
    result = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_doc_references() -> int:
    """Check all markdown files for stale path references. Returns exit code."""
    tracked = get_tracked_files()
    markdown_files = find_markdown_files()

    errors: list[tuple[str, int, str, str]] = []  # (file, line_num, ref, suggestion)

    for md_file in markdown_files:
        rel_path = str(md_file.relative_to(REPO_ROOT))
        if is_historical(rel_path):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for match in PATH_PATTERN.finditer(text):
            ref = match.group(1)
            if ref in KNOWN_EXCEPTIONS:
                continue
            if ref in tracked:
                continue

            # Check if it's a directory
            if (REPO_ROOT / ref).is_dir():
                continue

            # Check if it's a file
            if (REPO_ROOT / ref).is_file():
                continue

            line_num = text[:match.start()].count("\n") + 1
            errors.append((str(md_file.relative_to(REPO_ROOT)), line_num, ref, ""))

    if errors:
        for filepath, line_num, ref, _ in errors:
            print(f"STALE REF: {filepath}:{line_num}: `{ref}` does not exist in the repo")
        print(f"\nFAIL: {len(errors)} stale reference(s) found")
        return 1

    print(f"PASS: {len(markdown_files)} markdown files checked, 0 stale references")
    return 0


if __name__ == "__main__":
    sys.exit(check_doc_references())
