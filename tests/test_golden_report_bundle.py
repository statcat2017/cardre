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
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from tests.acceptance.fixture_pathway import build_acceptance_fixture_steps, write_input_parquet

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
    "points", "points_to_double_odds", "odds",
    "true_positive_rate", "false_positive_rate", "true_negative_rate",
    "false_negative_rate", "precision", "recall", "f1_score",
    "profit", "cost", "approval_rate", "bad_rate",
    "capture_rate", "score_cutoff",
    "upper", "lower", "label", "woe", "iv", "count", "count_0", "count_1",
    "event_rate", "non_event_rate",
    # Filesystem object path embeds the per-run temp/project root.
    "path",
    "score_psi", "variable_psi",
    "vif", "r_squared", "reason",
    "separation_ratio",
    "singleton_variables",
    "message",
    "python_version",
    # Apply-model scored output fields vary per run
    "pd_max", "pd_min", "pd_mean", "pd_std",
    "score_max", "score_min", "score_mean", "score_std",
    "pd_dummy", "score_dummy",
    # Generated scorer source code varies per run (bin boundaries, coefficients)
    "source",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HASH_IN_PATH_RE = re.compile(r"(^|/)(v2|v3):[a-f0-9]+|artifacts/[a-f0-9]{16,}")


# Path prefixes whose entire subtree is non-deterministic
NON_DETERMINISTIC_PATH_PREFIXES: set[str] = {
    "modelling_metadata",
}


def _is_non_deterministic_leaf(key: str, value: object) -> bool:
    if key in NON_DETERMINISTIC_SUFFIXES:
        return True
    if isinstance(value, str) and _UUID_RE.match(value):
        return True
    return bool(isinstance(value, str) and _HASH_IN_PATH_RE.search(value))


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

    parquet_path = write_input_parquet(tmp_path / "input.parquet")
    cat = build_default_catalogue()
    steps = build_acceptance_fixture_steps(parquet_path, cat)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    reader = FsArtifactStore(root)
    with uow_factory.read_only(project_id) as uow:
        collector = ReportCollector(
            EvidenceReader(reader, uow.artifacts, uow.run_steps),
            reader,
        )
        bundle = collector.collect(
            uow, project_id, result.run_id,
        )
    return bundle.model_dump(mode="json")


# Keys dropped only when canonicalizing an *individual list item* for the
# order-insensitive fallback comparison. This is a deliberate, narrow subset of
# ``NON_DETERMINISTIC_SUFFIXES``: it removes genuinely run-volatile ids/hashes/
# timestamps/paths/versions but *keeps* deterministic business metrics such as
# score_cutoff, approval_rate, bad_rate and capture_rate. A corrupted cutoff
# row must therefore still fail the golden comparison instead of being reduced
# to an empty tuple by the global leaf filter.
LIST_VOLATILE_KEYS: set[str] = {
    "branch_id", "requested_branch_id", "resolved_branch_id",
    "dataset_id", "artifact_id",
    "logical_hash", "physical_hash", "config_hash",
    "manifest_hash", "run_manifest_hash", "run_manifest_path",
    "manifest_version", "cardre_version", "pathway_hash",
    "model_logical_hash", "model_physical_hash",
    "generated_at", "started_at", "finished_at",
    "path", "python_version", "message",
    # Generated scorer source varies per run
    "source",
}


def _stable_sort_key(items: list[dict], path: str) -> str | None:
    """Pick a report-defined stable key for a list of dicts, if one exists.

    Returns the name of a deterministic field that is present and unique across
    every item, or ``None`` when no such key exists (so the caller must fall
    back to an order-insensitive comparison).

    Sorting by a stable key here is intentionally *order-insensitive*: the
    generated report guarantees a canonical ordering, and that ordering is
    owned by the generated structural invariants (see
    ``test_generated_report_structural_invariants``), not by the golden
    comparator. The comparator therefore compares lists as multisets.

    A candidate key that is present on the first item but missing or null on a
    later item is a structural defect, not a reason to silently degrade to the
    fallback. It is surfaced explicitly with the offending path and item index
    so the failure is distinguishable and attributable.
    """
    if not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    for key in first:
        if key in NON_DETERMINISTIC_SUFFIXES:
            continue
        if not all(isinstance(item[key], (str, int, float, bool)) for item in items):
            # Only scalar values are a trustworthy sort key; list/dict values
            # (e.g. nested bins or row lists) cannot order the items and must
            # not be picked as the stable key.
            continue
        missing = [
            i for i, item in enumerate(items)
            if key not in item or item[key] is None
        ]
        if missing:
            raise AssertionError(
                f"{path}: stable sort key {key!r} is present on the first "
                f"item but missing/null on item(s) {missing}; refusing to "
                "fall back silently to an order-insensitive comparison"
            )
        if len({repr(item[key]) for item in items}) == len(items):
            return key
    return None


def _canonical_list_item(value: object) -> object:
    """Canonicalize one list item for order-insensitive comparison.

    Recursively drops only the genuinely run-volatile keys in
    ``LIST_VOLATILE_KEYS`` (a narrow subset of ``NON_DETERMINISTIC_SUFFIXES``),
    preserving deterministic business values such as cutoff metrics. This is
    scoped to list items only so the global leaf comparison used for the
    dict-subtree path is not weakened.
    """
    if isinstance(value, dict):
        return tuple(sorted(
            (key, _canonical_list_item(item))
            for key, item in value.items()
            if key not in LIST_VOLATILE_KEYS
        ))
    if isinstance(value, list):
        return tuple(sorted(_canonical_list_item(item) for item in value))
    return value


def test_golden_report_bundle_matches(tmp_path):
    """Compare pathway report output to golden fixture."""
    if not GOLDEN_REPORT_BUNDLE.exists():
        pytest.skip("Golden fixture not found; run with --update-golden to create")
    with open(GOLDEN_REPORT_BUNDLE) as f:
        expected = json.load(f)
    got = _run_pathway(tmp_path)

    def _compare(got: object, expected: object, path: str = "") -> list[str]:
        diffs: list[str] = []
        if any(path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[") for prefix in NON_DETERMINISTIC_PATH_PREFIXES):
            return diffs
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
            if not isinstance(expected, list):
                return [f"{path}: list vs non-list"]
            if len(got) != len(expected):
                return [f"{path}: list length {len(got)} != expected {len(expected)}"]
            # Prefer a report-defined stable key; otherwise compare the
            # order-insensitive multisets of canonical list items. Sorting is
            # intentionally order-insensitive here — canonical ordering is
            # owned by the generated structural invariants, not the golden
            # comparator. The fallback drops only run-volatile keys
            # (LIST_VOLATILE_KEYS) so deterministic cutoff metrics are still
            # compared and corrupted values fail.
            sort_key = _stable_sort_key(got, path) if got and isinstance(got[0], dict) else None
            if sort_key is not None:
                got_items = sorted(got, key=lambda item: item[sort_key])
                expected_items = sorted(expected, key=lambda item: item[sort_key])
            else:
                got_items = sorted(_canonical_list_item(item) for item in got)
                expected_items = sorted(_canonical_list_item(item) for item in expected)
            for i, (g, e) in enumerate(zip(got_items, expected_items, strict=True)):
                diffs.extend(_compare(g, e, f"{path}[{i}]"))
            return diffs
        if got != expected:
            diffs.append(f"{path}: {got!r} != {expected!r}")
        return diffs

    diffs = _compare(got, expected)
    assert not diffs, "Report bundle differs from golden:\n" + "\n".join(diffs[:30])


REQUIRED_REPORT_SECTIONS: dict[str, type] = {
    # Summary / top-level
    "schema_version": str,
    "summary": dict,
    "pathway": dict,
    "variables": list,
    "model": dict,
    "score_scaling": dict,
    "validation": dict,
    "cutoffs": dict,
    "artifacts": list,
    "run_status": dict,
    # Post-purge quality sections
    "exclusion_summary": dict,
    "sample_definition": dict,
    "variable_selection": dict,
    "model_diagnostics": dict,
    "implementation_artifacts": dict,
}


def test_generated_report_has_required_sections(tmp_path):
    """Structural check on freshly generated output (not the golden fixture).

    Exercises the same pathway as the golden comparator but asserts the
    required report sections directly on generated output, so a missing
    section fails even if the golden fixture is stale or absent.
    """
    bundle = _run_pathway(tmp_path)

    ACCEPTED_STATUSES = {"complete", "complete_with_warnings"}
    assert bundle["report_status"] in ACCEPTED_STATUSES, (
        f"Report did not reach a completed status, got {bundle['report_status']!r}"
    )

    for section, expected_type in REQUIRED_REPORT_SECTIONS.items():
        assert section in bundle, f"Report missing required section {section!r}"
        value = bundle[section]
        assert isinstance(value, expected_type), (
            f"Report section {section!r} has type {type(value).__name__}, "
            f"expected {expected_type.__name__}"
        )

    # Deterministic, non-empty structural sanity so the test cannot pass on an
    # empty shell.
    assert len(bundle["variables"]) > 0, "Report should include at least one variable"
    assert bundle["model"]["features"], "Report model should list its features"
    assert bundle["pathway"]["steps"], "Report should include at least one pathway step"
    assert bundle["exclusion_summary"]["rows_before"] >= bundle["exclusion_summary"]["rows_after"]
    assert bundle["implementation_artifacts"]["scorecard_table"], "scorecard_table should be non-empty"
    assert bundle["implementation_artifacts"]["scoring_export_python"], "scoring_export_python should be non-empty"
    assert bundle["implementation_artifacts"]["scoring_export_sql"], "scoring_export_sql should be non-empty"


# Canonical order of pathway steps as emitted by the clean acceptance pathway.
# The generated report guarantees a stable ordering, so we assert both presence
# and relative order.
_EXPECTED_CANONICAL_STEP_ORDER = [
    "apply-exclusions",
    "sample-definition",
    "explicit-missing-outlier-treatment",
    "initial-woe-iv",
    "variable-clustering",
    "manual-binning",
    "final-woe-iv",
    "model-fit",
    "coefficient-sign-check",
    "separation-diagnostics",
    "vif-diagnostics",
    "score-scaling",
    "freeze-scorecard-bundle",
    "apply-woe",
    "apply-model",
    "calibration-diagnostics",
    "validation-metrics",
    "cutoff-analysis",
    "scorecard-table-export",
    "scoring-export-python",
    "scoring-export-sql",
]

# Expected stable signatures of the generated scorer sources.
_EXPECTED_SCORING_PYTHON_MARKERS = ("def score_cardre(record):", "SCORECARD_META")
_EXPECTED_SCORING_SQL_MARKERS = ("-- Standalone scorecard SQL generated by Cardre.", "WITH woe_cte AS")


def _assert_finite_number(value: object, path: str) -> None:
    assert isinstance(value, (int, float)), f"{path} should be numeric, got {type(value).__name__}"
    assert value == value and value not in (float("inf"), float("-inf")), f"{path} must be finite"


def test_generated_report_structural_invariants(tmp_path):
    """Invariants that catch the weak golden comparator's blind spots.

    The comparator only verifies that generated keys exist in the golden
    fixture; it cannot notice content that is present-but-empty, fields with
    broken shapes, or a scrambled step order. These assertions pin the
    deterministic, clean-pathway behaviour of the generated bundle directly.
    """
    bundle = _run_pathway(tmp_path)
    assert bundle["report_status"] in {"complete", "complete_with_warnings"}

    # --- List sections must carry meaningful non-empty content. ---
    assert bundle["variables"], "variables list must be non-empty"
    for variable in bundle["variables"]:
        assert variable.get("variable_name"), "each variable must name itself"
        assert variable.get("role"), f"{variable['variable_name']} must declare a role"
        bins = variable.get("bins")
        assert isinstance(bins, list) and bins, (
            f"variable {variable['variable_name']!r} must have non-empty bins"
        )

    artifacts = bundle["artifacts"]
    assert isinstance(artifacts, list) and artifacts, "artifacts list must be non-empty"
    for artifact in artifacts:
        assert artifact.get("artifact_id"), "each artifact must carry an artifact_id"

    # --- Stable ordering the generated report guarantees ---
    step_ids = [s.get("canonical_step_id") for s in bundle["pathway"]["steps"]]
    assert len(step_ids) == len(set(step_ids)), "pathway step ids must be unique"
    missing = [cid for cid in _EXPECTED_CANONICAL_STEP_ORDER if cid not in step_ids]
    assert not missing, (
        "pathway steps are missing or renamed vs the expected canonical order; "
        f"missing {missing} (found {step_ids})"
    )
    positions = [step_ids.index(cid) for cid in _EXPECTED_CANONICAL_STEP_ORDER]
    assert positions == sorted(positions), (
        "pathway steps must appear in the canonical order; got "
        f"indices {positions} for {_EXPECTED_CANONICAL_STEP_ORDER}"
    )
    assert all(s.get("status") in {"succeeded", "skipped"} for s in bundle["pathway"]["steps"]), \
        "every pathway step must have a terminal status"

    # --- Required numerical/report fields present and finite ---
    scaling = bundle["score_scaling"]
    for field in ("base_score", "points_to_double_odds", "factor", "offset", "min_score", "max_score"):
        assert field in scaling, f"score_scaling missing {field!r}"
        _assert_finite_number(scaling[field], f"score_scaling.{field}")
    summary = bundle["summary"]
    for field in ("final_variable_count", "excluded_variable_count"):
        assert field in summary, f"summary missing {field!r}"
        _assert_finite_number(summary[field], f"summary.{field}")

    # --- Model feature / coefficient shape consistency ---
    model = bundle["model"]
    features = model["features"]
    assert features, "model must list at least one feature"
    _assert_finite_number(model.get("intercept"), "model.intercept")
    seen_names = set()
    for feature in features:
        name = feature.get("variable_name")
        assert name, "each model feature must be named"
        assert name not in seen_names, f"duplicate model feature {name!r}"
        seen_names.add(name)
        assert feature.get("included") is True, f"feature {name!r} must be included"
        _assert_finite_number(feature.get("coefficient"), f"model.features[{name}].coefficient")
    # Every named feature maps onto a scored variable.
    variable_names = {v["variable_name"] for v in bundle["variables"]}
    for name in seen_names:
        base_name = name.rsplit("_woe", 1)[0]
        assert base_name in variable_names, (
            f"model feature {name!r} has no corresponding scored variable"
        )

    # --- Generated scoring source non-empty with an expected signature ---
    py_source = bundle["modelling_metadata"]["scoring-export-python"]
    assert py_source.get("function_name") == "score_cardre", "scoring python function name mismatch"
    assert all(marker in py_source.get("source", "") for marker in _EXPECTED_SCORING_PYTHON_MARKERS), \
        "scoring python source missing expected signature markers"

    sql_source = bundle["modelling_metadata"]["scoring-export-sql"]
    assert sql_source.get("dialect") == "generic", "scoring sql dialect must be generic"
    assert all(marker in sql_source.get("source", "") for marker in _EXPECTED_SCORING_SQL_MARKERS), \
        "scoring sql source missing expected signature markers"

    # --- Cutoff shape: a selected_cutoff dict that is structurally sound. ---
    # The bare ``score`` field is intentionally kept out of
    # NON_DETERMINISTIC_SUFFIXES so the golden comparator compares it; here we
    # pin its shape and, when non-null, require a finite numeric value. A null
    # score is a legitimate default when no cutoff was selected, so we do not
    # demand a number.
    cutoffs = bundle["cutoffs"]
    assert isinstance(cutoffs.get("cutoff_tables"), list), "cutoffs must include cutoff_tables"
    selected = cutoffs.get("selected_cutoff")
    assert isinstance(selected, dict), "cutoffs.selected_cutoff must be a dict"
    assert "score" in selected, "cutoffs.selected_cutoff must declare a score key"
    assert "selection_reason" in selected, "cutoffs.selected_cutoff must declare a selection_reason"
    if selected["score"] is not None:
        _assert_finite_number(selected["score"], "cutoffs.selected_cutoff.score")

    # --- Implementation artifact references present and non-empty ---
    imp = bundle["implementation_artifacts"]
    for key in ("scorecard_table", "scoring_export_python", "scoring_export_sql"):
        artifact = imp[key]
        assert artifact.get("artifact_type"), f"{key} must declare its artifact_type"
        assert artifact.get("artifact_id"), f"{key} must reference a non-empty artifact_id"
        assert artifact.get("description"), f"{key} must carry a non-empty description"


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
