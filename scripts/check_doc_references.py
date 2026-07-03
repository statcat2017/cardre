#!/usr/bin/env python3
"""Check markdown docs for stale file-path references and broken links.

Scans markdown files for:
1. Backtick-quoted paths that look like repo file references (e.g. `cardre/store.py`)
2. Markdown link targets (e.g. [text](architecture/reporting.md))

Fails if any referenced path does not exist in the repo.

Relative Markdown links are resolved against the source file's directory.
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
    # Pre-existing stale refs in current docs (v1 files deleted in v2 refactor)
    "cardre/_evidence/reader.py::_to_typed",
    "cardre/executor.py",
    "cardre/registry.py",
    "cardre/run_lifecycle.py",
    "cardre/staleness.py",
    "cardre/store/project_store.py",
    "cardre/services/evidence_policy.py",
    "cardre/services/report_generation_service.py",
    "sidecar/models.py",
    "sidecar/routes/health.py",
    "sidecar/routes/projects.py",
    "sidecar/routes/datasets.py",
    "sidecar/routes/plans.py",
    "sidecar/routes/runs.py",
    "sidecar/routes/artifacts.py",
    "sidecar/routes/branches.py",
    "sidecar/routes/node_types.py",
    "sidecar/routes/exports.py",
    "sidecar/routes/reports.py",
    "sidecar/routes/comparisons.py",
    "sidecar/routes/champion.py",
    "sidecar/routes/binning.py",
    "tests/test_artifact_guardrail.py",
    "tests/test_evidence_reader.py",
    "tests/test_evidence_profiles.py",
    "tests/helpers/evidence_assertions.py",
    "tests/test_artifact_serialization.py",
    "tests/test_legacy_artifact_compatibility.py",
    "frontend/src-tauri/binaries/cardre-api-{target-triple}",
    # Sidecar binary paths — these are naming-pattern references, not real files
    "frontend/src-tauri/binaries/",
    "frontend/src-tauri/binaries/cardre-api-{triple}{.exe?}",
    # Command examples in AGENTS.md that are not literal file paths
    "scripts/pr-gate.sh --no-open",
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
BACKTICK_PATH_PATTERN = re.compile(r"`((?:cardre|sidecar|frontend|tests|scripts|docs|\.github)/[^`]+)`")

# Pattern matches Markdown link targets (relative paths)
# Captures the path portion of [text](path) or [text](path#anchor)
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


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


def resolve_link_target(source_file: Path, target: str) -> str | None:
    """Resolve a Markdown link target to a repo-relative path.

    Returns None if the target is an external URL or not a file path.
    """
    if target.startswith("http://") or target.startswith("https://"):
        return None
    if target.startswith("#"):
        return None
    # Resolve relative to the source file's parent directory
    resolved = (source_file.parent / target).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return None


def check_doc_references() -> int:
    """Check all markdown files for stale path references. Returns exit code."""
    tracked = get_tracked_files()
    markdown_files = find_markdown_files()

    errors: list[tuple[str, int, str, str]] = []  # (file, line_num, ref, kind)

    for md_file in markdown_files:
        rel_path = str(md_file.relative_to(REPO_ROOT))
        if is_historical(rel_path):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check backtick-quoted paths
        for match in BACKTICK_PATH_PATTERN.finditer(text):
            ref = match.group(1)
            if ref in KNOWN_EXCEPTIONS:
                continue
            if ref in tracked:
                continue
            if (REPO_ROOT / ref).is_dir() or (REPO_ROOT / ref).is_file():
                continue
            line_num = text[:match.start()].count("\n") + 1
            errors.append((rel_path, line_num, ref, "backtick"))

        # Check Markdown link targets (resolved relative to source file)
        for match in MARKDOWN_LINK_PATTERN.finditer(text):
            target = match.group(2).split("#")[0].split("?")[0]  # strip anchor and query
            resolved = resolve_link_target(md_file, target)
            if resolved is None:
                continue
            if resolved in KNOWN_EXCEPTIONS:
                continue
            if resolved in tracked:
                continue
            if (REPO_ROOT / resolved).is_dir() or (REPO_ROOT / resolved).is_file():
                continue
            line_num = text[:match.start()].count("\n") + 1
            errors.append((rel_path, line_num, resolved, "markdown link"))

    if errors:
        for filepath, line_num, ref, kind in errors:
            print(f"STALE {kind.upper()}: {filepath}:{line_num}: `{ref}` does not exist in the repo")
        print(f"\nFAIL: {len(errors)} stale reference(s) found")
        return 1

    print(f"PASS: {len(markdown_files)} markdown files checked, 0 stale references")
    return 0


if __name__ == "__main__":
    sys.exit(check_doc_references())
