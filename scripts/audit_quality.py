"""Audit quality metrics for the thermo-nuclear code quality sprint.

Emits counts for forbidden patterns and structural metrics.

Modes:
  --baseline   prints counts only, always exits 0 (default for PR0)
  --enforce    exits 1 when any target is missed (target for PR11)
  --json       machine-readable JSON output

Usage:
    python scripts/audit_quality.py
    python scripts/audit_quality.py --json
    python scripts/audit_quality.py --enforce
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDRE = REPO_ROOT / "cardre"


def count_raw_accesses() -> int:
    """Count _raw dict accesses in key modules."""
    targets = [
        CARDRE / "nodes",
        CARDRE / "reporting",
        CARDRE / "services" / "comparison_service.py",
    ]
    count = 0
    for target in targets:
        if target.is_dir():
            for py in target.rglob("*.py"):
                content = py.read_text(encoding="utf-8")
                count += len(re.findall(r'\b_raw\b', content))
        elif target.is_file():
            content = target.read_text(encoding="utf-8")
            count += len(re.findall(r'\b_raw\b', content))
    return count


def count_adapters() -> int:
    """Count class.*Adapter definitions in adapters directory."""
    adapters_dir = CARDRE / "_evidence" / "adapters"
    count = 0
    for py in adapters_dir.rglob("*.py"):
        content = py.read_text(encoding="utf-8")
        count += len(re.findall(r'class\s+\w+Adapter\b', content))
    return count


def count_duplicated_step_resolvers() -> int:
    """Count ResolvedStepRef / resolve_step_for_branch definitions."""
    count = 0
    for py in CARDRE.rglob("*.py"):
        content = py.read_text(encoding="utf-8")
        count += len(re.findall(r'\bResolvedStepRef\b', content))
        count += len(re.findall(r'\b_resolve_step_for_branch\b', content))
        count += len(re.findall(r'\bresolve_step_for_branch\b', content))
    return count


def count_evidence_resolver_refs() -> int:
    """Count EvidenceResolver / BranchRunEvidence / prepare_branch_evidence refs."""
    count = 0
    for py in CARDRE.rglob("*.py"):
        content = py.read_text(encoding="utf-8")
        count += len(re.findall(r'\bEvidenceResolver\b', content))
        count += len(re.findall(r'\bBranchRunEvidence\b', content))
        count += len(re.findall(r'\bprepare_branch_evidence\b', content))
    return count


def count_files_over_1000_lines() -> int:
    """Count files in cardre/ over 1000 lines."""
    count = 0
    for py in CARDRE.rglob("*.py"):
        lines = len(py.read_text(encoding="utf-8").splitlines())
        if lines > 1000:
            count += 1
    return count


def count_bare_string_status_literals() -> int:
    """Count bare string status literals in services/ and execution/."""
    targets = [
        CARDRE / "services",
        CARDRE / "execution",
    ]
    status_pattern = re.compile(
        r"""['"](running|succeeded|failed|pending|skipped|aborted|cancelled)['"]"""
    )
    count = 0
    for target in targets:
        if target.is_dir():
            for py in target.rglob("*.py"):
                content = py.read_text(encoding="utf-8")
                count += len(status_pattern.findall(content))
    return count


METRICS = [
    ("_raw accesses in nodes/, reporting/, comparison_service.py", count_raw_accesses, 0),
    ("class.*Adapter in _evidence/adapters/", count_adapters, 3),
    ("ResolvedStepRef / resolve_step_for_branch definitions", count_duplicated_step_resolvers, 1),
    ("EvidenceResolver / BranchRunEvidence / prepare_branch_evidence refs", count_evidence_resolver_refs, 0),
    ("Files over 1000 lines in cardre/", count_files_over_1000_lines, 0),
    ("Bare string status literals in services/, execution/", count_bare_string_status_literals, 0),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit quality metrics")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--baseline", action="store_true", default=True,
                       help="Print counts only, always exit 0 (default)")
    group.add_argument("--enforce", action="store_true",
                       help="Exit 1 when any target is missed")
    args = parser.parse_args()

    results = []
    for name, fn, target in METRICS:
        count = fn()
        results.append({"check": name, "count": count, "target": target})

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        print()
    else:
        print(f"{'Check':<65} {'Count':>6} {'Target':>6}")
        print("-" * 80)
        for r in results:
            marker = " ✓" if r["count"] <= r["target"] else " ✗"
            print(f"{r['check']:<65} {r['count']:>6} {r['target']:>6}{marker}")

    if args.enforce:
        failed = [r for r in results if r["count"] > r["target"]]
        if failed:
            print(f"\n{len(failed)} metric(s) exceed target — exiting 1")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
