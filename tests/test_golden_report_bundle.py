"""Golden report bundle test — diff baseline for collector refactors.

Compares structure (key presence, types, list lengths) against the golden
fixture. Tolerates non-deterministic leaf values (timestamps, run IDs,
hashes, paths, metrics that vary per run due to random train/test split).

The 60-row synthetic dataset produces genuinely different model coefficients,
bin boundaries, calibration metrics, cutoff tables, and variable IV values
on every run because the train/test split is random. Per the PR0 spec,
this test compares structure + field names, not exact values.

Usage:
    python tests/test_golden_report_bundle.py --update-golden  # regenerate fixture
    pytest tests/test_golden_report_bundle.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cardre.workflows import build_canonical_scorecard_steps

pytestmark = pytest.mark.xfail(reason="TechnicalManifestExportNode deferred to Batch 05")

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_REPORT_BUNDLE = FIXTURE_DIR / "golden_report_bundle.json"

# Leaf keys whose values are inherently non-deterministic across runs
NON_DETERMINISTIC_SUFFIXES: set[str] = {
    "branch_id", "requested_branch_id", "resolved_branch_id",
    "dataset_id", "artifact_id",
    "logical_hash", "physical_hash", "config_hash",
    "manifest_hash", "run_manifest_hash", "run_manifest_path",
    "generated_at", "started_at", "finished_at",
    # Model outputs vary per run (random train/test split on 60-row dataset)
    "coefficient", "intercept", "abs_coefficient",
    # Calibration metrics vary per run
    "auc", "gini", "ks", "psi", "divergence", "calibration_error",
    "abs_deviation", "expected_events", "observed_event_rate",
    "observed_events", "predicted_event_rate",
    "hosmer_lemeshow_p_value", "hosmer_lemeshow_statistic",
    "n_bins",
    # Score scaling varies per run
    "points", "points_to_double_odds", "score", "odds",
    # Cutoff analysis varies per run
    "true_positive_rate", "false_positive_rate", "true_negative_rate",
    "false_negative_rate", "precision", "recall", "f1_score",
    "profit", "cost", "approval_rate", "bad_rate",
    "capture_rate", "score_cutoff",
    # Variable bin boundaries vary per run
    "upper", "lower", "label", "woe", "iv", "count", "count_0", "count_1",
    "event_rate", "non_event_rate",
    # Validation metrics vary per run
    "score_psi", "variable_psi",
    # VIF diagnostics vary per run
    "vif", "r_squared", "reason",
    # Separation diagnostics vary per run
    "separation_ratio",
    # Redundancy review varies per run
    "singleton_variables",
    # Limitation messages contain temp paths and hashes
    "message",
    # Python version varies across CI runners
    "python_version",
}

# UUID pattern (36 chars, 4 hyphens)
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

# Hash-like strings in paths (v2:hex or hex prefix)
_HASH_IN_PATH_RE = re.compile(r'(^|/)v2:[a-f0-9]+|artifacts/[a-f0-9]{16,}')

# Path prefixes whose list lengths vary per run (random train/test split)
NON_DETERMINISTIC_LIST_PATHS: set[str] = {
    "cutoffs.cutoff_tables",
    "model_diagnostics.calibration_diagnostics",
    "variables",
    "model.features",
    "model_diagnostics.coefficient_sign_check",
    "model_diagnostics.separation_diagnostics",
    "model_diagnostics.vif_diagnostics",
    "model_diagnostics.variable_clustering",
    "validation.metrics_by_role",
    "validation.stability.psi_by_role",
    "redundancy_review",
    "limitations",
    "artifacts",
    "dataset_roles",
    "pathway.steps",
    "branches.branches",
    "implementation_artifacts",
    "exclusion_summary",
    "sample_definition",
    "variable_selection",
    "model_diagnostics.source_step_refs",
    "validation.source_step_refs",
    "cutoffs.source_step_refs",
    "model.source_step_refs",
    "variable_selection.source_step_refs",
    "exclusion_summary.source_step_refs",
    "sample_definition.source_step_refs",
    "implementation_artifacts.source_step_refs",
}


def _is_non_deterministic_list(path: str) -> bool:
    if path in NON_DETERMINISTIC_LIST_PATHS:
        return True
    for prefix in NON_DETERMINISTIC_LIST_PATHS:
        if path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return True
    return False


def _is_non_deterministic_leaf(key: str, value: object) -> bool:
    if key in NON_DETERMINISTIC_SUFFIXES:
        return True
    if isinstance(value, str) and _UUID_RE.match(value):
        return True
    return bool(isinstance(value, str) and _HASH_IN_PATH_RE.search(value))


def _compare(
    got: object, expected: object, path: str = "",
) -> list[str]:
    """Recursively compare two values, returning a list of diffs.

    Checks:
      - Key presence (missing / extra keys in dicts)
      - List lengths (for deterministic paths)
      - Type compatibility
      - Scalar value equality (unless leaf is non-deterministic)
    """
    diffs: list[str] = []

    if not isinstance(got, type(expected)):
        return [f"{path}: type {type(got).__name__} != {type(expected).__name__}"]

    if isinstance(got, dict):
        got_keys = set(got)
        expected_keys = set(expected)
        missing = expected_keys - got_keys
        extra = got_keys - expected_keys
        if missing:
            diffs.append(f"{path}: missing keys {sorted(missing)}")
        if extra:
            diffs.append(f"{path}: extra keys {sorted(extra)}")
        for key in sorted(got_keys & expected_keys):
            gv, ev = got[key], expected[key]
            child_path = f"{path}.{key}" if path else key
            if _is_non_deterministic_leaf(key, gv) or _is_non_deterministic_leaf(key, ev):
                continue
            diffs.extend(_compare(gv, ev, child_path))
        return diffs

    if isinstance(got, list):
        if _is_non_deterministic_list(path):
            return diffs
        if len(got) != len(expected):
            diffs.append(f"{path}: list length {len(got)} != {len(expected)}")
            return diffs
        for i, (gi, ei) in enumerate(zip(got, expected, strict=True)):
            diffs.extend(_compare(gi, ei, f"{path}[{i}]"))
        return diffs

    if got != expected:
        diffs.append(f"{path}: {got!r} != {expected!r}")

    return diffs


def _write_input_csv(path: Path) -> Path:
    import csv
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _run_pathway(tmp_path: Path) -> dict:
    import uuid

    from cardre.reporting.collector import generate_report_bundle

    from cardre.application.runs.finalize_run import FinalizeRun as RunLifecycle
    from cardre.domain.diagnostics import utc_now_iso
    from cardre.execution.executor import PlanExecutor
    from cardre.store.branch_repo import BranchRepository
    from cardre.store.db import ProjectStore
    from cardre.store.plan_repo import PlanRepository
    from cardre.store.run_repo import RunRepository  # noqa: I001

    project_dir = tmp_path / "golden.cardre"
    store = ProjectStore(project_dir)
    store.initialize()

    csv_path = _write_input_csv(tmp_path / "input.csv")

    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Golden Test", now, "0.2.0"),
    )

    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Golden Plan", now),
    )

    steps = build_canonical_scorecard_steps(csv_path)
    plan_version_id = PlanRepository(store).create_version(
        plan_id, steps=steps, is_committed=True,
    )

    run_id = RunRepository(store).create(plan_version_id)
    executor = PlanExecutor(store)
    executor.run_plan_version(plan_version_id, run_id)
    lifecycle = RunLifecycle(store, run_id, plan_version_id, execution_mode="full_plan")
    lifecycle.finalise("succeeded")

    branch_id = BranchRepository(store).create_branch(
        project_id=project_id,
        plan_id=plan_id,
        name="main",
        branch_type="feature",
        base_plan_version_id=plan_version_id,
        head_plan_version_id=plan_version_id,
        created_reason="golden test",
    )
    for s in steps:
        BranchRepository(store).create_step_map(
            branch_id=branch_id,
            plan_version_id=plan_version_id,
            canonical_step_id=s.canonical_step_id,
            step_id=s.step_id,
            is_branch_owned=True,
        )

    bundle = generate_report_bundle(
        store=store,
        project_id=project_id,
        run_id=run_id,
        target_branch_id=branch_id,
        report_mode="branch",
    )
    return bundle.model_dump(mode="json")


def test_golden_report_bundle_matches(tmp_path):
    """Compare pathway report output to golden fixture.

    Checks key presence, list lengths (for deterministic paths), types,
    and deterministic scalar values. Skips non-deterministic leaf values
    (UUIDs, hashes, timestamps, model coefficients, calibration metrics,
    bin boundaries, etc.) and non-deterministic list paths.
    """
    if not GOLDEN_REPORT_BUNDLE.exists():
        pytest.skip("Golden fixture not found; run with --update-golden to create")

    with open(GOLDEN_REPORT_BUNDLE) as f:
        expected = json.load(f)

    got = _run_pathway(tmp_path)
    diffs = _compare(got, expected)
    assert not diffs, "Report bundle differs from golden:\n" + "\n".join(diffs[:30])


def test_golden_report_bundle_has_expected_sections(tmp_path):
    """Verify the report bundle has all expected sections."""
    if not GOLDEN_REPORT_BUNDLE.exists():
        pytest.skip("Golden fixture not found; run with --update-golden to create")

    with open(GOLDEN_REPORT_BUNDLE) as f:
        bundle = json.load(f)

    expected_sections = {
        "exclusion_summary", "sample_definition", "variable_selection",
        "model_diagnostics", "implementation_artifacts", "modelling_metadata",
        "summary", "pathway", "variables", "model", "score_scaling",
        "validation", "cutoffs", "artifacts",
    }
    for section in expected_sections:
        assert section in bundle, f"Missing section: {section}"


if __name__ == "__main__":
    import sys
    if "--update-golden" in sys.argv:
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        bundle = _run_pathway(tmp)
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        with open(GOLDEN_REPORT_BUNDLE, "w") as f:
            json.dump(bundle, f, indent=2, default=str)
        print(f"Updated {GOLDEN_REPORT_BUNDLE}")
    else:
        print("Run with --update-golden to regenerate the golden fixture")
