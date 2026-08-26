"""Focused tests for scripts/check-coverage-thresholds.py.

Loads the hyphenated script via importlib (it is not importable as a normal
module) and exercises its package mapping, aggregation, and threshold
enforcement against JSON fixtures built from the configured floors.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-coverage-thresholds.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_coverage_thresholds", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _file_entry(covered: int, total: int, *, covered_branches: int = 0, total_branches: int = 0) -> dict:
    return {
        "summary": {
            "num_statements": total,
            "covered_lines": covered,
            "covered_branches": covered_branches,
            "num_branches": total_branches,
        }
    }


def _report(files: dict[str, dict]) -> dict:
    return {"files": files}


# --- assign_package ---------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("cardre/domain/step.py", "cardre/domain"),
        ("cardre/application/run.py", "cardre/application"),
        ("cardre/adapters/sqlite/connection.py", "cardre/adapters"),
        ("cardre/api/app.py", "cardre/api"),
        ("cardre/nodes/woe.py", "cardre/nodes"),
        ("cardre/modeling/regression.py", "cardre/modeling"),
        ("cardre/bootstrap/container.py", "cardre/bootstrap"),
        ("sidecar/main.py", "sidecar"),
        ("sidecar/nested/mod.py", "sidecar"),
        ("cardre/__init__.py", None),  # bare cardre module, not tracked
        ("cardre/foo.py", None),  # bare cardre module, not tracked
        ("tests/test_x.py", None),  # unrelated path
        ("scripts/check-coverage-thresholds.py", None),  # unrelated path
    ],
)
def test_assign_package(mod, path, expected):
    assert mod.assign_package(path) == expected


# --- measure ----------------------------------------------------------------


def test_measure_aggregates_by_package_and_globally(mod):
    data = _report(
        {
            "cardre/domain/a.py": _file_entry(10, 20, covered_branches=3, total_branches=4),
            "cardre/domain/b.py": _file_entry(5, 5, covered_branches=1, total_branches=1),
            "cardre/api/app.py": _file_entry(8, 10, covered_branches=0, total_branches=2),
            "sidecar/main.py": _file_entry(3, 4, covered_branches=1, total_branches=1),
            "cardre/__init__.py": _file_entry(1, 1),  # ignored (bare module)
            "tests/test_x.py": _file_entry(9, 9),  # ignored (unrelated)
        }
    )
    per_package, global_covered, global_total, global_branch_covered, global_branch_total = mod.measure(data)

    assert per_package == {
        "cardre/domain": (15, 25),
        "cardre/api": (8, 10),
        "sidecar": (3, 4),
    }
    # Global totals include ignored files too.
    assert global_covered == 10 + 5 + 8 + 3 + 1 + 9
    assert global_total == 20 + 5 + 10 + 4 + 1 + 9
    # Global branch totals aggregate across tracked and ignored files.
    assert global_branch_covered == 3 + 1 + 0 + 1
    assert global_branch_total == 4 + 1 + 2 + 1


def test_measure_skips_zero_statement_files(mod):
    data = _report(
        {
            "cardre/domain/a.py": _file_entry(0, 0),
            "cardre/domain/b.py": _file_entry(4, 4, covered_branches=2, total_branches=2),
        }
    )
    per_package, global_covered, global_total, global_branch_covered, global_branch_total = mod.measure(data)
    assert per_package == {"cardre/domain": (4, 4)}
    assert (global_covered, global_total) == (4, 4)
    # Zero-statement files contribute no branches either.
    assert (global_branch_covered, global_branch_total) == (2, 2)


# --- main -------------------------------------------------------------------


def _run_main(mod, monkeypatch, report: Path) -> int:
    monkeypatch.setattr("sys.argv", ["check-coverage-thresholds.py", "--coverage", str(report)])
    return mod.main()


def test_main_missing_report_returns_nonzero(mod, tmp_path, capsys, monkeypatch):
    missing = tmp_path / "nope.json"
    rc = _run_main(mod, monkeypatch, missing)
    assert rc != 0
    assert "not found" in capsys.readouterr().err


def test_main_missing_required_package_returns_nonzero(mod, tmp_path, capsys, monkeypatch):
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(
            _report(
                {
                    "cardre/domain/a.py": _file_entry(100, 100),
                    "sidecar/main.py": _file_entry(100, 100),
                }
            )
        )
    )
    rc = _run_main(mod, monkeypatch, report)
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "cardre/application: no measured coverage" in out


def test_main_below_branch_floor_returns_nonzero(mod, tmp_path, capsys, monkeypatch):
    """Statement floors are met but global branch coverage is below the floor."""
    report = tmp_path / "coverage.json"
    files = {}
    for pkg, floor in mod.PACKAGE_FLOORS.items():
        # Meet the statement floor but keep branches at 50% < 60% floor.
        files[f"{pkg}/a.py"] = _file_entry(int(floor), 100, covered_branches=5, total_branches=10)
    report.write_text(json.dumps(_report(files)))

    rc = _run_main(mod, monkeypatch, report)
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "global branches: 50.0% below 60%" in out


def test_main_branch_floor_met_returns_zero(mod, tmp_path, capsys, monkeypatch):
    """Statement and branch floors are both met."""
    report = tmp_path / "coverage.json"
    files = {}
    for pkg, floor in mod.PACKAGE_FLOORS.items():
        files[f"{pkg}/a.py"] = _file_entry(int(floor), 100, covered_branches=6, total_branches=10)
    report.write_text(json.dumps(_report(files)))

    rc = _run_main(mod, monkeypatch, report)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "branches 60.0% (>= 60%)" in out


def test_main_below_floor_global_and_package_returns_nonzero(mod, tmp_path, capsys, monkeypatch):
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(
            _report(
                {
                    "cardre/domain/a.py": _file_entry(1, 100),  # 1% < 75%
                    "cardre/application/a.py": _file_entry(1, 100),  # 1% < 80%
                    "cardre/adapters/a.py": _file_entry(1, 100),  # 1% < 80%
                    "cardre/api/a.py": _file_entry(1, 100),  # 1% < 80%
                    "cardre/nodes/a.py": _file_entry(1, 100),  # 1% < 70%
                    "cardre/modeling/a.py": _file_entry(1, 100),  # 1% < 75%
                    "cardre/bootstrap/a.py": _file_entry(1, 100),  # 1% < 75%
                    "sidecar/main.py": _file_entry(1, 100),  # 1% < 70%
                }
            )
        )
    )
    rc = _run_main(mod, monkeypatch, report)
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "global: 1.0% below 60%" in out  # global backstop also trips
    assert "cardre/domain: 1.0% below 75%" in out
    assert "cardre/application: 1.0% below 80%" in out


def test_main_no_branch_fields_reports_na(mod, tmp_path, capsys, monkeypatch):
    """A report with only statement fields must not trip the branch floor.

    Coverage JSON produced without ``--cov-branch`` (or by tools that do not
    emit branch metrics) omits ``covered_branches``/``num_branches`` per file.
    The checker must not raise ``KeyError``; branch enforcement is skipped and
    branch coverage is reported as n/a, exactly like the zero-branch path.
    """
    report = tmp_path / "coverage.json"
    files = {}
    for pkg, floor in mod.PACKAGE_FLOORS.items():
        # Only statement fields; no branch keys at all.
        files[f"{pkg}/a.py"] = {
            "summary": {
                "num_statements": 100,
                "covered_lines": int(floor),
            }
        }
    report.write_text(json.dumps(_report(files)))

    rc = _run_main(mod, monkeypatch, report)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "branches n/a (no branches measured)" in out


def test_main_zero_total_branches_returns_zero(mod, tmp_path, capsys, monkeypatch):
    """A valid report with no measured branches must not trip the branch floor.

    Regression guard for the branch-floor edge: when ``num_branches`` totals
    zero across the report, the global branch floor must not be enforced (a
    branch-free surface cannot be below 60%), and the run must succeed. The
    branch coverage is reported as not applicable rather than 0%.
    """
    report = tmp_path / "coverage.json"
    files = {}
    for pkg, floor in mod.PACKAGE_FLOORS.items():
        # Meet the statement floor; zero branches everywhere.
        files[f"{pkg}/a.py"] = _file_entry(int(floor), 100)
    report.write_text(json.dumps(_report(files)))

    rc = _run_main(mod, monkeypatch, report)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "branches n/a (no branches measured)" in out


def test_main_minimal_valid_report_returns_zero(mod, tmp_path, capsys, monkeypatch):
    """Build a report where every configured package meets its floor."""
    files = {}
    for pkg, floor in mod.PACKAGE_FLOORS.items():
        # One file per package at exactly the statement floor and 60% branches.
        files[f"{pkg}/a.py"] = _file_entry(int(floor), 100, covered_branches=6, total_branches=10)
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps(_report(files)))

    rc = _run_main(mod, monkeypatch, report)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    # Branch percentage is reported in the PASS line.
    assert "branches 60.0% (>= 60%)" in out
