#!/usr/bin/env python3
"""Ratchet-style scanner for direct artifact reads bypassing ArtifactEvidenceReader.

Compares current violation count against a stored baseline.  Only fails when the
count *increases* — preventing regressions without requiring a full rewrite of
existing code.

Usage::
    python3 scripts/scan-direct-artifact-reads.py              # check against baseline
    python3 scripts/scan-direct-artifact-reads.py --update     # update baseline
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = REPO_ROOT / ".artifact-read-baseline.json"

EXCLUDED_MODULES: set[str] = {
    "cardre/_evidence/reader.py",
    "cardre/evidence.py",
    "cardre/store/project_store.py",
    "cardre/services/export_service.py",
    "cardre/services/import_service.py",
    "cardre/services/manual_binning_service.py",
    "tests/helpers.py",
}

PATTERNS = [
    re.compile(r"store\.artifact_path\("),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan for direct artifact reads")
    parser.add_argument("--update", action="store_true", help="Update baseline file")
    return parser.parse_args()


def git_ls_python_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_violations(files: list[str]) -> dict[str, list[int]]:
    violations: dict[str, list[int]] = {}
    for filepath in files:
        path = REPO_ROOT / filepath
        if not path.exists():
            continue
        if filepath in EXCLUDED_MODULES:
            continue
        with open(path) as f:
            lines = f.readlines()
        file_violations = [
            lineno for lineno, line in enumerate(lines, 1)
            if any(p.search(line) for p in PATTERNS)
        ]
        if file_violations:
            violations[filepath] = file_violations
    return violations


def main() -> int:
    args = parse_args()
    files = git_ls_python_files()
    current = collect_violations(files)
    current_count = sum(len(v) for v in current.values())

    if args.update:
        with open(BASELINE_FILE, "w") as f:
            json.dump(current, f, indent=2, sort_keys=True)
        print(f"Baseline updated: {current_count} violations across {len(current)} files.")
        return 0

    if not BASELINE_FILE.exists():
        print(f"No baseline file found at {BASELINE_FILE}. Run with --update to create one.")
        print(f"Current violations: {current_count}")
        return 0

    with open(BASELINE_FILE) as f:
        baseline = json.load(f)
    baseline_count = sum(len(v) for v in baseline.values())

    new_files = set(current) - set(baseline)
    if new_files:
        print("New direct artifact reads in files not in baseline:")
        for fp in sorted(new_files):
            print(f"  {fp}: lines {current[fp]}")
        print(f"\nBaseline: {baseline_count} violations in {len(baseline)} files")
        print(f"Current:  {current_count} violations in {len(current)} files")
        print("FAIL: New files with direct artifact reads detected.")
        return 1

    increased = {
        fp: current[fp]
        for fp in baseline
        if len(current.get(fp, [])) > len(baseline.get(fp, []))
    }
    if increased:
        print("Increased direct artifact reads in existing files:")
        for fp, lines in sorted(increased.items()):
            new_lines = set(lines) - set(baseline.get(fp, []))
            print(f"  {fp}: new lines {sorted(new_lines)}")
        print(f"\nBaseline: {baseline_count} violations in {len(baseline)} files")
        print(f"Current:  {current_count} violations in {len(current)} files")
        print("FAIL: Direct artifact read count increased.")
        return 1

    print(f"OK — {current_count} violations in {len(current)} files (baseline: {baseline_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
