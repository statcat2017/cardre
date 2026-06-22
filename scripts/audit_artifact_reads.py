#!/usr/bin/env python3
"""Audit tracked Python files for direct artifact reads.

Scans tracked ``.py`` files via ``git ls-files`` and classifies direct artifact
reads in production code, tests, docs, and suppressed low-level exceptions.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
import tokenize
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_SUPPRESSION_REASONS = {
    "dataset-frame-input",
    "artifact-byte-download",
    "low-level-evidence-parser",
    "serialization-compatibility-test",
}

CLASSIFICATIONS = {
    "approved_low_level_io",
    "production_violation",
    "test_violation",
    "documentation_reference",
    "false_positive",
}

DEFAULT_READER_HINT = "Use ArtifactEvidenceReader.read(...) or find(...) instead of direct artifact_path I/O."


@dataclass(frozen=True)
class PatternSpec:
    pattern_type: str
    regex: re.Pattern[str]


PATTERNS: tuple[PatternSpec, ...] = (
    PatternSpec(
        "json_loads_read_text",
        re.compile(r"json\.loads\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\.read_text\s*\(\s*\)\s*\)"),
    ),
    PatternSpec(
        "json_load_open",
        re.compile(r"json\.load\s*\(\s*open\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\)\s*\)"),
    ),
    PatternSpec(
        "path_read_text",
        re.compile(r"Path\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\)\s*\.read_text\s*\(\s*\)"),
    ),
    PatternSpec(
        "pl_read_parquet",
        re.compile(r"pl\.read_parquet\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\)"),
    ),
    PatternSpec(
        "pl_scan_parquet",
        re.compile(r"pl\.scan_parquet\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\)"),
    ),
    PatternSpec(
        "open_artifact_path",
        re.compile(r"open\s*\(\s*[^\n]*?store\.artifact_path\([^\n]*?\)\s*\)"),
    ),
    PatternSpec(
        "artifact_path_read_text",
        re.compile(r"store\.artifact_path\([^\n]*?\)\s*\.read_text\s*\(\s*\)"),
    ),
)

SUPPRESSION_RE = re.compile(r"#\s*cardre-allow-artifact-read:\s*([a-z-]+)")


@dataclass(frozen=True)
class ArtifactReadMatch:
    file: str
    line_number: int
    pattern_type: str
    classification: str
    reader_hint: str | None
    suppression_reason: str | None = None

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "file": self.file,
            "line_number": self.line_number,
            "pattern_type": self.pattern_type,
            "classification": self.classification,
            "reader_hint": self.reader_hint,
        }
        if self.suppression_reason is not None:
            payload["suppression_reason"] = self.suppression_reason
        return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit tracked Python files for direct artifact reads")
    parser.add_argument("--production", action="store_true", help="Scan production/source files only")
    parser.add_argument("--tests", action="store_true", help="Scan test files only")
    parser.add_argument("--json", action="store_true", help="Emit newline-delimited JSON records")
    parser.add_argument(
        "--fail-on",
        choices=sorted(CLASSIFICATIONS),
        help="Exit non-zero if any match has this classification",
    )
    return parser.parse_args(argv)


def git_ls_tracked_python_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
    return [repo_root / rel for rel in result.stdout.splitlines() if rel.strip()]


def _is_docs_path(path: Path) -> bool:
    return "docs" in path.parts


def _is_test_path(path: Path) -> bool:
    return path.parts and path.parts[0] == "tests"


def classify_match(rel_path: str, suppression_reason: str | None) -> str:
    path = Path(rel_path)
    if _is_docs_path(path):
        return "documentation_reference"
    if suppression_reason == "low-level-evidence-parser":
        return "approved_low_level_io"
    if rel_path.startswith("cardre/_evidence/"):
        return "approved_low_level_io"
    if suppression_reason in {
        "dataset-frame-input",
        "artifact-byte-download",
        "serialization-compatibility-test",
    }:
        return "false_positive"
    if _is_test_path(path):
        return "test_violation"
    return "production_violation"


def reader_hint_for(classification: str) -> str | None:
    if classification == "production_violation":
        return DEFAULT_READER_HINT
    return None


def _suppression_reason(line: str) -> str | None:
    match = SUPPRESSION_RE.search(line)
    if not match:
        return None
    reason = match.group(1)
    return reason if reason in ALLOWED_SUPPRESSION_REASONS else None


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _absolute_offset(line_starts: list[int], position: tuple[int, int]) -> int:
    row, col = position
    return line_starts[row - 1] + col


def _ignored_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    line_starts = _line_starts(text)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type not in {tokenize.STRING, tokenize.COMMENT}:
                continue
            spans.append(
                (
                    _absolute_offset(line_starts, token.start),
                    _absolute_offset(line_starts, token.end),
                )
            )
    except tokenize.TokenError:
        return []
    return spans


def _overlaps(span: tuple[int, int], ignored_spans: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in ignored_spans)


def scan_file(path: Path) -> list[ArtifactReadMatch]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    rel_path = path.relative_to(REPO_ROOT).as_posix()
    matches: list[ArtifactReadMatch] = []
    emitted_spans: list[tuple[int, int]] = []
    ignored_spans = _ignored_spans(text)
    line_starts = _line_starts(text)

    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        line_start = line_starts[lineno - 1]
        suppression_reason = _suppression_reason(line)
        for spec in PATTERNS:
            for found in spec.regex.finditer(line):
                span = found.span()
                absolute_span = (line_start + span[0], line_start + span[1])
                if _overlaps(absolute_span, ignored_spans):
                    continue
                if any(absolute_span[0] < end and absolute_span[1] > start for start, end in emitted_spans):
                    continue
                emitted_spans.append(absolute_span)
                classification = classify_match(rel_path, suppression_reason)
                matches.append(
                    ArtifactReadMatch(
                        file=rel_path,
                        line_number=lineno,
                        pattern_type=spec.pattern_type,
                        classification=classification,
                        reader_hint=reader_hint_for(classification),
                        suppression_reason=suppression_reason,
                    )
                )
    return matches


def scan_repo(repo_root: Path, *, include_production: bool, include_tests: bool) -> list[ArtifactReadMatch]:
    matches: list[ArtifactReadMatch] = []
    for path in git_ls_tracked_python_files(repo_root):
        rel_path = path.relative_to(repo_root)
        if _is_docs_path(rel_path):
            continue
        if _is_test_path(rel_path):
            if not include_tests:
                continue
        elif not include_production:
            continue
        matches.extend(scan_file(path))
    matches.sort(key=lambda item: (item.file, item.line_number, item.pattern_type))
    return matches


def _format_human(matches: Iterable[ArtifactReadMatch]) -> str:
    lines = []
    for match in matches:
        suffix = f" [{match.suppression_reason}]" if match.suppression_reason else ""
        lines.append(f"{match.file}:{match.line_number}: {match.classification} {match.pattern_type}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    include_production = args.production or not args.tests
    include_tests = args.tests or not args.production

    try:
        matches = scan_repo(REPO_ROOT, include_production=include_production, include_tests=include_tests)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        for match in matches:
            print(json.dumps(match.to_json(), sort_keys=True))
    else:
        if matches:
            print(_format_human(matches))
        else:
            print("No direct artifact reads found.")

    if args.fail_on and any(match.classification == args.fail_on for match in matches):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
