"""Architecture guard: cardre/application/** must never touch ``uow._conn``.

R5 pushed all persistence SQL behind typed repository operations on the
adapter. import-linter forbids *importing* ``cardre.adapters`` from
``cardre.application``, but a runtime ``uow._conn.execute(...)`` reach-through
would slip past import-linter. This test AST-scans every application module
and fails on any attribute access whose attribute is ``_conn``.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "cardre" / "application"


def _application_python_files() -> list[Path]:
    return [p for p in APP_ROOT.rglob("*.py") if p.is_file()]


def _uses_conn_access(tree: ast.AST) -> list[str]:
    """Return a list of line numbers accessing ``._conn``."""
    return [
        f"{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "_conn"
    ]


def test_application_never_accesses_conn() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _application_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for line in _uses_conn_access(tree):
            offenders.append((str(path.relative_to(REPO_ROOT)), line))
    assert not offenders, (
        "cardre/application/** must not access ``._conn`` (R5 invariant). "
        "Offenders:\n  " + "\n  ".join(f"{f}:{line}" for f, line in offenders)
    )


def test_conn_detector_flags_known_bad() -> None:
    bad = ast.parse("uow._conn.execute('SELECT 1')")
    assert _uses_conn_access(bad), "detector must flag ._conn access"


def test_conn_detector_ignores_unrelated() -> None:
    ok = ast.parse("uow.runs.list_for_plan_version()")
    assert not _uses_conn_access(ok)
