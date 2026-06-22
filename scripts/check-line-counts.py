#!/usr/bin/env python3
"""Line-count enforcement safety rail.

Checks that tracked source files stay within their language-specific line-count
thresholds.  Files on the built-in ALLOWLIST are skipped.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LANGUAGE_GLOBS = {
    "python": ["cardre/*.py", "cardre/**/*.py", "sidecar/*.py", "sidecar/**/*.py", "tests/*.py", "tests/**/*.py", "scripts/*.py"],
    "typescript": ["frontend/src/*.ts", "frontend/src/*.tsx", "frontend/src/**/*.ts", "frontend/src/**/*.tsx"],
    "rust": ["frontend/src-tauri/src/*.rs", "frontend/src-tauri/src/**/*.rs"],
}

ALLOWLIST: set[str] = {
    # Python (>1000 lines)
    "cardre/_evidence/models.py",
    "cardre/nodes/prep.py",
    "tests/test_optbinning.py",
    "tests/test_bin_definition_lifecycle.py",
    "tests/test_sidecar_api.py",
    "tests/test_executor.py",
    "tests/test_nodes.py",
    "tests/test_reporting.py",
    # TypeScript/TSX (>600 lines)
    "frontend/src/components/ManualBinningEditor.tsx",
    # Auto-generated files
    "frontend/src/api/schema.d.ts",
    # Rust (>300 lines)
    "frontend/src-tauri/src/main.rs",
}

EXTENSION_THRESHOLDS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Line-count enforcement safety rail")
    parser.add_argument("--threshold-python", type=int, default=1000, help="Python line-count threshold (default: 1000)")
    parser.add_argument("--threshold-ts", type=int, default=600, help="TypeScript/TSX line-count threshold (default: 600)")
    parser.add_argument("--threshold-rust", type=int, default=300, help="Rust line-count threshold (default: 300)")
    return parser.parse_args()


def git_ls_files(globs: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", *globs],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return files


def get_line_counts(files: list[str]) -> dict[str, int]:
    if not files:
        return {}
    result = subprocess.run(
        ["wc", "-l", "--", *files],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"ERROR: wc failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)

    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                count = int(parts[0])
                fname = parts[-1]
                counts[fname] = count
            except ValueError:
                pass
    return counts


def classify_file(filepath: str) -> str | None:
    ext = Path(filepath).suffix
    return EXTENSION_THRESHOLDS.get(ext)


def main() -> None:
    args = parse_args()

    thresholds = {
        "python": args.threshold_python,
        "typescript": args.threshold_ts,
        "rust": args.threshold_rust,
    }

    all_globs: list[str] = []
    for globs in LANGUAGE_GLOBS.values():
        all_globs.extend(globs)

    try:
        files = git_ls_files(all_globs)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    files_to_check = [f for f in files if f not in ALLOWLIST and (REPO_ROOT / f).exists()]
    counts = get_line_counts(files_to_check)

    violations: list[tuple[str, int, int]] = []
    for filepath, count in counts.items():
        lang = classify_file(filepath)
        if lang is None:
            continue
        threshold = thresholds[lang]
        if count > threshold:
            violations.append((filepath, count, threshold))

    if violations:
        for filepath, count, threshold in violations:
            print(f"{filepath}: {count} lines (limit: {threshold})")
        print(f"Line count check failed: {len(files_to_check)} files checked, {len(violations)} violations")
        sys.exit(1)
    else:
        print(f"Line count check passed: {len(files_to_check)} files checked, 0 violations")
        sys.exit(0)


if __name__ == "__main__":
    main()
