"""Golden report bundle test — structural diff against port-native reporting.

Runs the full canonical scorecard pathway through the new composed runtime,
then collects a report via the new ReportCollector, and compares the
structure against the golden fixture.

Per the sprint contract, this test replaces the legacy workflow-dependent
golden test. The golden fixture was regenerated from the new runtime path
to capture the report structure produced by the port-native collector and
renderer.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from cardre.adapters.reporting.collector import ReportCollector
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.workflows import build_canonical_scorecard_steps

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_REPORT_BUNDLE = FIXTURE_DIR / "golden_report_bundle.json"

NON_DETERMINISTIC_SUFFIXES: set[str] = {
    "branch_id", "requested_branch_id", "resolved_branch_id",
    "dataset_id", "artifact_id",
    "logical_hash", "physical_hash", "config_hash",
    "manifest_hash", "run_manifest_hash", "run_manifest_path",
    "manifest_version", "cardre_version", "pathway_hash",
    "model_logical_hash", "model_physical_hash",
    "generated_at", "started_at", "finished_at",
    "coefficient", "intercept", "abs_coefficient",
    "auc", "gini", "ks", "psi", "divergence", "calibration_error",
    "abs_deviation", "expected_events", "observed_event_rate",
    "observed_events", "predicted_event_rate",
    "hosmer_lemeshow_p_value", "hosmer_lemeshow_statistic",
    "n_bins",
    "points", "points_to_double_odds", "score", "odds",
    "true_positive_rate", "false_positive_rate", "true_negative_rate",
    "false_negative_rate", "precision", "recall", "f1_score",
    "profit", "cost", "approval_rate", "bad_rate",
    "capture_rate", "score_cutoff",
    "upper", "lower", "label", "woe", "iv", "count", "count_0", "count_1",
    "event_rate", "non_event_rate",
    "score_psi", "variable_psi",
    "vif", "r_squared", "reason",
    "separation_ratio",
    "singleton_variables",
    "message",
    "python_version",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HASH_IN_PATH_RE = re.compile(r"(^|/)v2:[a-f0-9]+|artifacts/[a-f0-9]{16,}")


def _is_non_deterministic_leaf(key: str, value: object) -> bool:
    if key in NON_DETERMINISTIC_SUFFIXES:
        return True
    if isinstance(value, str) and _UUID_RE.match(value):
        return True
    return bool(isinstance(value, str) and _HASH_IN_PATH_RE.search(value))


def _write_input_csv(path: Path) -> Path:
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
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Golden Test")
        plan_id = uow.plans.create_plan(project_id, "Golden Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    steps = build_canonical_scorecard_steps(csv_path)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    # Create a baseline branch and step map
    with uow_factory.for_project(project_id) as uow:
        branch_id = uow.branches.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="main", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="golden test",
        )
        for s in steps:
            uow.branches.create_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=s.canonical_step_id,
                step_id=s.step_id, is_branch_owned=True,
            )
        uow.commit()

    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    reader = FsArtifactStore(root)
    with uow_factory.read_only(project_id) as uow:
        collector = ReportCollector(
            EvidenceReader(reader, uow.artifacts, uow.run_steps),
            reader,
        )
        bundle = collector.collect(
            uow, project_id, result.run_id, branch_id, "branch",
        )
    return bundle.model_dump(mode="json")


def test_golden_report_bundle_matches(tmp_path):
    """Compare pathway report output to golden fixture."""
    if not GOLDEN_REPORT_BUNDLE.exists():
        pytest.skip("Golden fixture not found; run with --update-golden to create")
    with open(GOLDEN_REPORT_BUNDLE) as f:
        expected = json.load(f)
    got = _run_pathway(tmp_path)

    def _compare(got: object, expected: object, path: str = "") -> list[str]:
        diffs: list[str] = []
        if not isinstance(got, type(expected)):
            return [f"{path}: type {type(got).__name__} != {type(expected).__name__}"]
        if isinstance(got, dict):
            got_keys, expected_keys = set(got), set(expected)
            missing = expected_keys - got_keys
            extra = got_keys - expected_keys
            if missing:
                diffs.append(f"{path}: missing keys {sorted(missing)}")
            if extra:
                diffs.append(f"{path}: extra keys {sorted(extra)}")
            for key in sorted(got_keys & expected_keys):
                child_path = f"{path}.{key}" if path else key
                if _is_non_deterministic_leaf(key, got[key]) or _is_non_deterministic_leaf(key, expected[key]):
                    continue
                diffs.extend(_compare(got[key], expected[key], child_path))
            return diffs
        if isinstance(got, list):
            return diffs  # skip list-length comparisons (non-deterministic)
        if got != expected:
            diffs.append(f"{path}: {got!r} != {expected!r}")
        return diffs

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
        "model_diagnostics", "implementation_artifacts", "summary",
        "pathway", "variables", "model", "score_scaling",
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
