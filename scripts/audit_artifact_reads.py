#!/usr/bin/env python3
"""Audit tracked Python files for direct artifact reads.

Scans tracked ``.py`` files via ``git ls-files`` and classifies direct artifact
reads in production code, tests, docs, and suppressed low-level exceptions.
"""

from __future__ import annotations

import argparse
import ast
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
DEFAULT_APPROVED_MODULES = (
    "cardre/artifacts.py",
    "cardre/evidence.py",
    "cardre/_evidence/",
    "cardre/modeling/serialization.py",
)

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
DOC_PATH = "docs/architecture/artifact-evidence-access.md"

SUPPRESSION_RE = re.compile(r"#\s*cardre-allow-artifact-read:\s*([a-z-]+)")


@dataclass(frozen=True)
class ArtifactReadMatch:
    file: str
    line_number: int
    pattern_type: str
    classification: str
    suggested_reader: str | None
    doc_path: str | None
    invalid_suppression: bool
    suppression_reason: str | None = None

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "file": self.file,
            "line_number": self.line_number,
            "pattern_type": self.pattern_type,
            "classification": self.classification,
            "suggested_reader": self.suggested_reader,
            "doc_path": self.doc_path,
            "invalid_suppression": self.invalid_suppression,
            "reader_hint": self.suggested_reader,
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
        "--approved-modules",
        help="Comma-separated approved path prefixes overriding the default low-level IO modules",
    )
    parser.add_argument(
        "--fail-on",
        choices=sorted(CLASSIFICATIONS),
        help="Exit non-zero if any match has this classification",
    )
    return parser.parse_args(argv)


def _parse_approved_modules(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_APPROVED_MODULES
    modules = tuple(part.strip() for part in value.split(",") if part.strip())
    return modules or DEFAULT_APPROVED_MODULES


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


def _is_approved_module(rel_path: str, approved_modules: tuple[str, ...]) -> bool:
    return any(rel_path == module or rel_path.startswith(module) for module in approved_modules)


def classify_match(rel_path: str, suppression_reason: str | None, approved_modules: tuple[str, ...]) -> str:
    path = Path(rel_path)
    if _is_docs_path(path):
        return "documentation_reference"
    if _is_approved_module(rel_path, approved_modules):
        return "approved_low_level_io"
    if suppression_reason == "low-level-evidence-parser":
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


def suggested_reader_for(classification: str) -> str | None:
    if classification == "production_violation":
        return DEFAULT_READER_HINT
    return None


def doc_path_for(classification: str) -> str | None:
    if classification == "production_violation":
        return DOC_PATH
    return None


def _suppression_reason(line: str) -> tuple[str | None, bool]:
    match = SUPPRESSION_RE.search(line)
    if not match:
        return None, False
    reason = match.group(1)
    if reason in ALLOWED_SUPPRESSION_REASONS:
        return reason, False
    return reason, True


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


def _expr_contains_artifact_source(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "artifact_path":
            return True
        if isinstance(expr.func, ast.Name) and expr.func.id == "Path":
            return any(_expr_contains_artifact_source(arg) for arg in expr.args)
        return any(_expr_contains_artifact_source(arg) for arg in expr.args)
    if isinstance(expr, ast.Attribute):
        return _expr_contains_artifact_source(expr.value)
    if isinstance(expr, ast.Subscript):
        return _expr_contains_artifact_source(expr.value)
    if isinstance(expr, ast.BoolOp):
        return any(_expr_contains_artifact_source(value) for value in expr.values)
    if isinstance(expr, ast.BinOp):
        return _expr_contains_artifact_source(expr.left) or _expr_contains_artifact_source(expr.right)
    if isinstance(expr, ast.IfExp):
        return (
            _expr_contains_artifact_source(expr.body)
            or _expr_contains_artifact_source(expr.orelse)
            or _expr_contains_artifact_source(expr.test)
        )
    return False


def _collect_aliases(text: str) -> set[str]:
    aliases: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return aliases
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not _expr_contains_artifact_source(node.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and _expr_contains_artifact_source(node.value) and isinstance(node.target, ast.Name):
                aliases.add(node.target.id)
    return aliases


def _line_mentions_source(line: str, aliases: set[str]) -> bool:
    if ".artifact_path(" in line:
        return True
    if not aliases:
        return False
    read_tokens = ("read_text(", "read_parquet(", "scan_parquet(", "open(", "json.loads(", "json.load(", "Path(")
    return any(alias in line and any(token in line for token in read_tokens) for alias in aliases)


def _match_span(line: str, line_start: int, pattern: str) -> tuple[int, int] | None:
    match = re.search(pattern, line)
    if not match:
        return None
    return line_start + match.start(), line_start + match.end()


def _append_match(
    matches: list[ArtifactReadMatch],
    *,
    rel_path: str,
    line_number: int,
    pattern_type: str,
    suppression_reason: str | None,
    invalid_suppression: bool,
    approved_modules: tuple[str, ...],
) -> None:
    classification = classify_match(rel_path, None if invalid_suppression else suppression_reason, approved_modules)
    matches.append(
        ArtifactReadMatch(
            file=rel_path,
            line_number=line_number,
            pattern_type=pattern_type,
            classification=classification,
            suggested_reader=suggested_reader_for(classification),
            doc_path=doc_path_for(classification),
            invalid_suppression=invalid_suppression,
            suppression_reason=suppression_reason,
        )
    )


def scan_file(path: Path, *, approved_modules: tuple[str, ...]) -> list[ArtifactReadMatch]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    rel_path = path.relative_to(REPO_ROOT).as_posix()
    matches: list[ArtifactReadMatch] = []
    ignored_spans = _ignored_spans(text)
    line_starts = _line_starts(text)
    aliases = _collect_aliases(text)

    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        line_start = line_starts[lineno - 1]
        suppression_reason, invalid_suppression = _suppression_reason(line)
        line_has_source = _line_mentions_source(line, aliases)

        if ".artifact_path(" in line:
            span = _match_span(line, line_start, r"\.artifact_path\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="artifact_path_call",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )

        if not line_has_source:
            continue

        if "json.loads(" in line and "read_text(" in line:
            span = _match_span(line, line_start, r"json\.loads\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="json_loads_read_text",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )
        if "json.load(" in line and "open(" in line:
            span = _match_span(line, line_start, r"json\.load\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="json_load_open",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )
        if "Path(" in line and "read_text(" in line:
            span = _match_span(line, line_start, r"Path\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="path_read_text",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )
        if "pl.read_parquet(" in line:
            span = _match_span(line, line_start, r"pl\.read_parquet\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="pl_read_parquet",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )
        if "pl.scan_parquet(" in line:
            span = _match_span(line, line_start, r"pl\.scan_parquet\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="pl_scan_parquet",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )
        if "open(" in line:
            span = _match_span(line, line_start, r"open\(")
            if not _overlaps(span, ignored_spans):
                _append_match(
                    matches,
                    rel_path=rel_path,
                    line_number=lineno,
                    pattern_type="open_artifact_path",
                    suppression_reason=suppression_reason,
                    invalid_suppression=invalid_suppression,
                    approved_modules=approved_modules,
                )

    return matches


def scan_repo(
    repo_root: Path,
    *,
    include_production: bool,
    include_tests: bool,
    approved_modules: tuple[str, ...],
) -> list[ArtifactReadMatch]:
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
        matches.extend(scan_file(path, approved_modules=approved_modules))
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
    approved_modules = _parse_approved_modules(args.approved_modules)

    try:
        matches = scan_repo(
            REPO_ROOT,
            include_production=include_production,
            include_tests=include_tests,
            approved_modules=approved_modules,
        )
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
