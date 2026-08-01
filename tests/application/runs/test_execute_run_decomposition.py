"""Pin the structural invariants of the decomposed ExecuteRun.

These tests do NOT re-prove the R3 lease/cancellation behaviour (that lives in
test_dispatch_fencing_concurrency.py); they prove the decomposition preserved
the same observable structure through a cleaner shape.

Behaviour preservation itself is covered by the full tests/application/runs
and tests/application/execution suites (composed execution, dispatch/fencing,
publication durability, contract/identity), which run the real ExecuteRun.
"""
from __future__ import annotations

import ast
from pathlib import Path

EXEC = Path(__file__).resolve().parents[3] / "cardre" / "application" / "runs" / "execute_run.py"


def _source() -> str:
    return EXEC.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source())


def _function(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_tree()) if isinstance(n, ast.FunctionDef) and n.name == name)


# --- structural guards ---


def test_no_run_summary_ref_instance_state() -> None:
    """The _run_summary_ref side-channel must be gone (moved into the hook)."""
    assert "_run_summary_ref" not in _source()


def test_no_inline_node_type_special_case_in_call() -> None:
    """__call__ must not special-case 'cardre.technical_manifest_export'."""
    call = _function("__call__")
    segment = ast.get_source_segment(_source(), call) or ""
    assert "technical_manifest_export" not in segment


def test_run_summary_hook_exists_and_owns_special_case() -> None:
    """The hook class must exist and be the only home of the special case."""
    tree = _tree()
    assert any(isinstance(n, ast.ClassDef) and n.name == "_RunSummaryHook" for n in ast.walk(tree))
    segment = ast.get_source_segment(_source(), next(
        n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "_RunSummaryHook"
    )) or ""
    assert "technical_manifest_export" in segment


def test_fenced_persist_helper_exists() -> None:
    """A module-level fenced-persist context manager must be extracted."""
    tree = _tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_fenced_persist" in names


def test_read_uow_helper_exists() -> None:
    tree = _tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_read_uow" in names


def test_call_body_under_100_lines() -> None:
    call = _function("__call__")
    assert call.end_lineno - call.lineno + 1 <= 100, (
        f"__call__ must stay under 100 lines (got {call.end_lineno - call.lineno + 1})"
    )


def test_call_opens_no_raw_uows() -> None:
    """__call__ must not hand-roll raw UoW blocks; reads go through helpers."""
    call = _function("__call__")
    direct = sum(
        1 for n in ast.walk(call)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_uow_factory"
    )
    assert direct == 0, (
        f"__call__ must not call _uow_factory() directly (got {direct}); "
        "use _read_uow/_fenced_persist/_claim_run"
    )


def test_persist_step_outputs_extracted() -> None:
    assert _function("_persist_step_outputs").end_lineno - _function("_persist_step_outputs").lineno + 1 > 0


def test_execute_steps_extracted() -> None:
    assert _function("_execute_steps").end_lineno - _function("_execute_steps").lineno + 1 > 0
