#!/usr/bin/env python3
"""Line-count enforcement safety rail.

Checks that tracked source files stay within their language-specific line-count
thresholds.  Policy uses three buckets:

  GENERATED_FILES   — excluded from maintainability limits entirely.
  SEAM_WATCHLIST    — architectural seams that may exceed the normal threshold
                      up to a documented seam-specific limit.
  LINE_COUNT_DEBT   — temporary exceptions for known over-limit files pending
                      structural split.  Warns when the file no longer needs it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LANGUAGE_GLOBS: dict[str, list[str]] = {
    "python": [
        "cardre/*.py",
        "cardre/**/*.py",
        "sidecar/*.py",
        "sidecar/**/*.py",
        "tests/*.py",
        "tests/**/*.py",
        "scripts/*.py",
    ],
    "typescript": [
        "frontend/src/*.ts",
        "frontend/src/*.tsx",
        "frontend/src/**/*.ts",
        "frontend/src/**/*.tsx",
    ],
    "rust": [
        "frontend/src-tauri/src/*.rs",
        "frontend/src-tauri/src/**/*.rs",
    ],
}

EXTENSION_THRESHOLDS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
}

# ── Generated / mechanically produced files ──────────────────────────

GENERATED_FILES: set[str] = {
    "frontend/src/api/schema.d.ts",
}

# ── Architectural seam watchlist ─────────────────────────────────────

SEAM_WATCHLIST: dict[str, dict[str, Any]] = {
    "cardre/executor.py": {
        "threshold": 1400,
        "owner": "execution seam",
        "split_only_on": [
            "ExecutionPlan/action planning becomes reusable",
            "error classification becomes reusable outside executor",
            "fingerprinting becomes shared evidence policy",
            "input resolution becomes a branch/evidence service",
        ],
    },
    "cardre/store/project_store.py": {
        "threshold": 1400,
        "owner": "ProjectStore compatibility facade",
        "split_only_on": [
            "migration runner extraction",
            "query/read-model extraction",
            "remaining direct SQL can move behind repositories",
        ],
    },
    "cardre/reporting/collector.py": {
        "threshold": 1400,
        "owner": "report bundle collector",
        "split_only_on": [
            "section collector clarifies evidence contract",
            "shared evidence lookup moves to evidence seam",
        ],
    },
    "cardre/services/comparison_service.py": {
        "threshold": 1200,
        "owner": "comparison materialisation",
        "split_only_on": [
            "branch readiness policy extraction",
            "typed evidence lookup extraction",
            "comparison snapshot builder extraction",
        ],
    },
    "cardre/modeling/adapters.py": {
        "threshold": 1400,
        "owner": "model application adapter seam",
        "split_only_on": [
            "adapter family modules preserve registry contract",
            "shared scoring/evidence helpers remain single-source",
        ],
    },
}

# ── Temporary line-count debt ────────────────────────────────────────

LINE_COUNT_DEBT: dict[str, dict[str, Any]] = {
    "cardre/_evidence/models.py": {
        "current_count": 1116,
        "ceiling": 1300,
        "reason": "data-model file; candidate for domain-split",
    },
    "cardre/nodes/prep.py": {
        "current_count": 1073,
        "ceiling": 1300,
        "reason": "node module; candidate for node-family split",
    },
    "tests/test_executor.py": {
        "current_count": 1043,
        "ceiling": 1200,
        "reason": "executor integration test; candidate for scenario split",
    },
    "tests/test_optbinning.py": {
        "current_count": 1444,
        "ceiling": 1700,
        "reason": "optbinning integration test; pending optbinning path cleanup",
    },
    "tests/test_bin_definition_lifecycle.py": {
        "current_count": 1216,
        "ceiling": 1400,
        "reason": "lifecycle test; candidate for scenario split",
    },
    "tests/test_nodes.py": {
        "current_count": 1205,
        "ceiling": 1400,
        "reason": "node integration test; candidate for node-family split",
    },
    "tests/test_reporting.py": {
        "current_count": 1055,
        "ceiling": 1300,
        "reason": "reporting test; candidate by template split",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Line-count enforcement safety rail",
    )
    parser.add_argument(
        "--threshold-python",
        type=int,
        default=1000,
        help="Python line-count threshold (default: 1000)",
    )
    parser.add_argument(
        "--threshold-ts",
        type=int,
        default=600,
        help="TypeScript/TSX line-count threshold (default: 600)",
    )
    parser.add_argument(
        "--threshold-rust",
        type=int,
        default=300,
        help="Rust line-count threshold (default: 300)",
    )
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
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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


# ── Existence / duplication health checks ────────────────────────────

PolicyHealthIssues = list[str]


def check_policy_health() -> PolicyHealthIssues:
    """Verify all policy entries refer to real files without cross-bucket
    duplication.  Returns a list of human-readable issue descriptions."""
    issues: list[str] = []

    for fpath in GENERATED_FILES:
        if not (REPO_ROOT / fpath).is_file():
            issues.append(f"GENERATED_FILES entry does not exist: {fpath}")

    for fpath in SEAM_WATCHLIST:
        if not (REPO_ROOT / fpath).is_file():
            issues.append(f"SEAM_WATCHLIST entry does not exist: {fpath}")

    for fpath in LINE_COUNT_DEBT:
        if not (REPO_ROOT / fpath).is_file():
            issues.append(f"LINE_COUNT_DEBT entry does not exist: {fpath}")

    all_paths: dict[str, list[str]] = {}
    for p in GENERATED_FILES:
        all_paths.setdefault(p, []).append("GENERATED_FILES")
    for p in SEAM_WATCHLIST:
        all_paths.setdefault(p, []).append("SEAM_WATCHLIST")
    for p in LINE_COUNT_DEBT:
        all_paths.setdefault(p, []).append("LINE_COUNT_DEBT")

    for fpath, buckets in all_paths.items():
        if len(buckets) > 1:
            issues.append(
                f"{fpath} appears in multiple buckets: {', '.join(buckets)}"
            )

    return issues


# ── Core policy check (testable without subprocess) ──────────────────

CheckResult = tuple[
    list[tuple[str, int, int, str]],  # violations: (filepath, count, limit, tag)
    list[tuple[str, int, int, str]],  # seam_warnings
    list[str],                        # stale_debts
]


def check_line_counts(
    counts: dict[str, int],
    thresholds: dict[str, int],
) -> CheckResult:
    """Evaluate line-counts against the three-bucket policy.

    Parameters
    ----------
    counts : dict[str, int]
        Map of filepath -> line count.  Generated files must already be
        excluded before calling this function.
    thresholds : dict[str, int]
        Language -> normal threshold (e.g. ``{"python": 1000}``).

    Returns
    -------
    violations : list of (filepath, count, limit, tag)
        Hard failures.  *tag* is ``"seam:<owner>"``, ``"debt:<path>"``,
        or ``""`` for ordinary over-threshold files.
    seam_warnings : list of (filepath, count, normal_threshold, owner)
        Seam files above the normal threshold but under the seam threshold.
    stale_debts : list of filepath
        Debt entries that no longer need an exemption.
    """
    violations: list[tuple[str, int, int, str]] = []
    seam_warnings: list[tuple[str, int, int, str]] = []
    stale_debts: list[str] = []

    for filepath, count in counts.items():
        lang = classify_file(filepath)
        if lang is None:
            continue
        normal_threshold = thresholds[lang]

        seam_info = SEAM_WATCHLIST.get(filepath)
        if seam_info is not None:
            seam_threshold = seam_info["threshold"]
            if count > seam_threshold:
                violations.append((filepath, count, seam_threshold, f"seam:{seam_info['owner']}"))
            elif count > normal_threshold:
                seam_warnings.append((filepath, count, normal_threshold, seam_info["owner"]))
            continue

        debt_info = LINE_COUNT_DEBT.get(filepath)
        if debt_info is not None:
            ceiling = debt_info["ceiling"]
            if count > ceiling:
                violations.append((filepath, count, ceiling, f"debt:{filepath}"))
            elif count <= normal_threshold:
                stale_debts.append(filepath)
            continue

        if count > normal_threshold:
            violations.append((filepath, count, normal_threshold, ""))

    return violations, seam_warnings, stale_debts


def filter_policy_files(files: list[str]) -> list[str]:
    """Remove generated files and non-existent paths from a file list."""
    return [
        f for f in files
        if f not in GENERATED_FILES and (REPO_ROOT / f).exists()
    ]


def main() -> None:
    args = parse_args()

    thresholds = {
        "python": args.threshold_python,
        "typescript": args.threshold_ts,
        "rust": args.threshold_rust,
    }

    health_issues = check_policy_health()

    all_globs: list[str] = []
    for globs in LANGUAGE_GLOBS.values():
        all_globs.extend(globs)

    try:
        files = git_ls_files(all_globs)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    files_to_check = filter_policy_files(files)
    counts = get_line_counts(files_to_check)

    violations, seam_warnings, stale_debts = check_line_counts(counts, thresholds)

    has_error = bool(health_issues)

    if health_issues:
        for issue in health_issues:
            print(f"POLICY: {issue}")

    if violations:
        has_error = True
        for filepath, count, effective_threshold, tag in violations:
            if tag.startswith("seam:"):
                owner = tag.removeprefix("seam:")
                print(
                    f"FAIL: {filepath}: {count} lines "
                    f"(seam limit: {effective_threshold}) — "
                    f"owned by: {owner}"
                )
            elif tag.startswith("debt:"):
                print(
                    f"FAIL: {filepath}: {count} lines "
                    f"(debt ceiling: {effective_threshold}) — "
                    f"exceeded LINE_COUNT_DEBT ceiling; split or justify"
                )
            else:
                print(
                    f"FAIL: {filepath}: {count} lines "
                    f"(limit: {effective_threshold})"
                )

    if seam_warnings:
        for filepath, count, normal_threshold, owner in seam_warnings:
            print(
                f"WARN: {filepath}: {count} lines "
                f"(normal limit: {normal_threshold}) — seam-approved, "
                f"owned by: {owner}"
            )
            print("      Check documented decomposition triggers before splitting.")

    if stale_debts:
        for filepath in stale_debts:
            print(
                f"STALE: {filepath} is in LINE_COUNT_DEBT "
                f"but is under the limit; remove the exemption."
            )

    if has_error:
        summary = (
            f"FAIL: {len(violations)} violation(s), "
            f"{len(seam_warnings)} seam warning(s), "
            f"{len(stale_debts)} stale exemption(s)"
        )
        if health_issues:
            summary += f", {len(health_issues)} policy health issue(s)"
        print(summary)
        sys.exit(1)

    parts = [f"PASS: {len(files_to_check)} files checked, 0 violations"]
    if seam_warnings:
        parts.append(f"{len(seam_warnings)} seam warning(s)")
    if stale_debts:
        parts.append(f"{len(stale_debts)} stale exemption(s)")
    print("; ".join(parts))
    sys.exit(0)


if __name__ == "__main__":
    main()
