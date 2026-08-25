"""Architecture guards: ErrorCode is the single closed error-code vocabulary.

These tests AST-scan ``cardre/`` and the domain-error map to enforce that
every ``CardreError``-family code is an ``ErrorCode`` member. The runtime
constructor also validates, but CI enforcement here prevents drift at the
source. Modelled on ``tests/test_application_no_conn_access.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cardre.api.errors import _DOMAIN_ERROR_MAP
from cardre.domain.errors import (
    INTERNAL_ERROR_CODES,
    CardreError,
    ErrorCode,
    NodeFailedWithArtifacts,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDRE_ROOT = REPO_ROOT / "cardre"

def _cardre_python_files() -> list[Path]:
    return [p for p in CARDRE_ROOT.rglob("*.py") if p.is_file()]


def _cardre_error_constructor_names() -> set[str]:
    names = {"CardreError"}
    stack = list(CardreError.__subclasses__())
    while stack:
        cls = stack.pop()
        names.add(cls.__name__)
        stack.extend(cls.__subclasses__())
    return names


def _literal_cardre_codes(tree: ast.AST, constructor_names: set[str]) -> list[tuple[int, str]]:
    """Return ``(line, code_string)`` for string-constant ``code=`` args."""
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id in constructor_names)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in constructor_names)
            )
        ):
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    sites.append((node.lineno, kw.value.value))
    return sites


def _collect_subclasses() -> list[type[CardreError]]:
    """Collect every CardreError subclass recursively."""
    found: list[type[CardreError]] = []
    stack: list[type[CardreError]] = list(CardreError.__subclasses__())
    while stack:
        cls = stack.pop()
        found.append(cls)
        stack.extend(cls.__subclasses__())
    return found


def test_no_literal_codes_outside_enum() -> None:
    """Every string-literal ``code=`` passed to a CardreError-family
    constructor must be an ``ErrorCode`` member."""
    offenders: list[tuple[str, str]] = []
    constructor_names = _cardre_error_constructor_names()
    for path in _cardre_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for line, code in _literal_cardre_codes(tree, constructor_names):
            if code not in ErrorCode:
                offenders.append((str(path.relative_to(REPO_ROOT)), f"{line}:{code}"))
    assert not offenders, (
        "Raw CardreError code literals outside ErrorCode. Offenders:\n  "
        + "\n  ".join(f"{f}:{c}" for f, c in offenders)
    )


def test_class_level_codes_in_enum() -> None:
    """Every CardreError subclass's class-level ``code`` is an ErrorCode member."""
    for cls in _collect_subclasses():
        code = getattr(cls, "code", None)
        assert code in ErrorCode, (
            f"{cls.__name__} class-level code {code!r} is not an ErrorCode member."
        )


def test_domain_error_map_codes_in_enum() -> None:
    """Every key and value-code in _DOMAIN_ERROR_MAP is an ErrorCode member."""
    for key, (code, status) in _DOMAIN_ERROR_MAP.items():
        assert key in ErrorCode, f"Map key {key!r} is not an ErrorCode member."
        assert code in ErrorCode, f"Map value-code {code!r} is not an ErrorCode member."
        assert isinstance(status, int), f"Map status for {key!r} is not an int: {status!r}."


def test_internal_error_codes_not_in_domain_map() -> None:
    """Internal-only codes must never be mapped to an HTTP status."""
    leaked = INTERNAL_ERROR_CODES & set(_DOMAIN_ERROR_MAP)
    assert not leaked, (
        f"Internal-only codes must not have an HTTP status in _DOMAIN_ERROR_MAP: "
        f"{sorted(c.value for c in leaked)}"
    )


def test_constructor_rejects_unknown_code() -> None:
    """CardreError rejects a code not in ErrorCode at construction time."""
    with pytest.raises(ValueError):
        CardreError("x", code="DEFINITELY_NOT_A_CODE")
    # A valid enum member constructs fine.
    err = CardreError("x", code=ErrorCode.BAD_REQUEST)
    assert err.code == ErrorCode.BAD_REQUEST


def test_node_failed_with_artifacts_exposes_artifacts() -> None:
    staged = [object()]
    error = NodeFailedWithArtifacts("partial failure", staged)
    assert error.artifacts is staged
