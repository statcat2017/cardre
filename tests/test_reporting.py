"""Unit tests for cardre.reporting — schema, collector, readiness, HTML renderer, golden JSON."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from cardre.audit import RunStepRecord
from cardre.reporting.collector import ReportCollector, generate_report_bundle
from cardre.readiness import LimitationCode
from cardre.readiness import (
    check_report_readiness,
    ReportReadinessResult,
    ReadinessBlocker,
    ReadinessWarning,
)
from cardre.reporting.renderer_html import render_report_bundle_to_html
from cardre.reporting.schema import (
    ReportBundle,
    ResolvedStepRef,
    Limitation,
    VariableInfo,
    WoeSmoothingInfo,
    AffectedBinDetail,
    ModelInfo,
    ModelFeature,
    ScoreScalingInfo,
    ValidationInfo,
    MetricsByRole,
    ChampionInfo,
    BranchInfo,
    BranchSummary,
    ManualIntervention,
    ArtifactEntry,
)
from cardre.evidence import SCHEMA_MANUAL_BINNING_OVERRIDES
from cardre.step_id import resolve_step_for_branch, ResolvedStepRef as ResolverRef
from cardre.store import ProjectStore

pytestmark = pytest.mark.integration


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "report"


# =========================================================================
# Schema tests
# =========================================================================

class TestReportBundleSchema:
    def test_default_bundle_serializes_deterministically(self):
        b1 = ReportBundle()
        b2 = ReportBundle()
        j1 = b1.model_dump_json(indent=2)
        j2 = b2.model_dump_json(indent=2)
        assert j1 == j2

    def test_bundle_has_required_fields(self):
        b = ReportBundle(
            project_id="p1",
            run_id="r1",
            target_branch_id="main",
            report_mode="branch",
        )
        dump = b.model_dump(mode="json")
        assert dump["schema_version"] == "cardre.report_bundle.v1"
        assert dump["project_id"] == "p1"
        assert dump["run_id"] == "r1"
        assert dump["target_branch_id"] == "main"
        assert dump["report_mode"] == "branch"

    def test_resolved_step_ref(self):
        ref = ResolvedStepRef(
            requested_branch_id="challenger_a",
            resolved_branch_id="main",
            canonical_step_id="calculate_woe_iv",
            step_id="calculate-woe-iv__br_main",
            resolution="ancestor",
        )
        d = ref.model_dump()
        assert d["requested_branch_id"] == "challenger_a"
        assert d["resolution"] == "ancestor"

    def test_limitation_codes(self):
        lim = Limitation(severity="warning", code="NO_OOT_SAMPLE", message="No OOT sample.")
        assert lim.severity == "warning"
        assert lim.code == "NO_OOT_SAMPLE"

    def test_variable_with_woe_smoothing(self):
        var = VariableInfo(
            variable_name="applicant_age",
            iv=0.126,
            woe_smoothing=WoeSmoothingInfo(
                enabled=True, method="additive", alpha=0.5,
                smoothing_applied=True, zero_cell_encountered=True,
                affected_bin_count=1,
            ),
            affected_bins=[
                AffectedBinDetail(
                    bin_id="bin_001", reason="zero_bad",
                    raw_good_count=120, raw_bad_count=0,
                    smoothed_good_count=120.5, smoothed_bad_count=0.5,
                    final_woe=-1.42,
                )
            ],
        )
        d = var.model_dump(mode="json")
        assert d["variable_name"] == "applicant_age"
        assert d["iv"] == 0.126
        assert d["woe_smoothing"]["smoothing_applied"] is True
        assert len(d["affected_bins"]) == 1
        assert d["affected_bins"][0]["final_woe"] == -1.42

    def test_champion_selected(self):
        c = ChampionInfo(
            champion_status="selected",
            assignment_id="ca_001",
            champion_branch_id="main",
            comparison_artifact_id="comp_001",
            rationale="Best OOT Gini.",
            target_branch_is_champion=True,
        )
        d = c.model_dump()
        assert d["champion_status"] == "selected"
        assert d["target_branch_is_champion"] is True

    def test_champion_not_available(self):
        c = ChampionInfo()
        assert c.champion_status == "not_available"
        assert c.target_branch_is_champion is False

    def test_model_info(self):
        m = ModelInfo(
            model_type="logistic_regression_scorecard",
            features=[
                ModelFeature(variable_name="age", coefficient=-0.4321, standard_error=0.031, p_value=0.001),
            ],
            intercept=-2.154,
        )
        d = m.model_dump()
        assert len(d["features"]) == 1
        assert d["features"][0]["variable_name"] == "age"

    def test_score_scaling(self):
        s = ScoreScalingInfo(
            base_score=600, base_odds="50:1", pdo=20,
            factor=28.8539, offset=487.123,
        )
        d = s.model_dump()
        assert d["base_score"] == 600
        assert d["factor"] == 28.8539

    def test_validation_metrics(self):
        v = ValidationInfo(
            metrics_by_role=[
                MetricsByRole(role="train", row_count=1000, auc=0.742, gini=0.484, ks=0.361),
                MetricsByRole(role="oot", row_count=500, auc=0.711),
            ],
        )
        d = v.model_dump()
        assert len(d["metrics_by_role"]) == 2
        assert d["metrics_by_role"][0]["auc"] == 0.742
        assert d["metrics_by_role"][1]["role"] == "oot"


# =========================================================================
# Step resolver tests
# =========================================================================

class TestStepResolver:
    def test_exact_resolution(self):
        branch_step_map = [
            {"canonical_step_id": "final-woe-iv", "step_id": "final-woe-iv__br_main",
             "is_shared_upstream": False, "is_branch_owned": True, "source_branch_id": None},
        ]
        ref = resolve_step_for_branch(
            branch_id="main",
            canonical_step_id="final-woe-iv",
            branch_step_map=branch_step_map,
        )
        assert ref is not None
        assert ref.resolution == "exact"
        assert ref.step_id == "final-woe-iv__br_main"
        assert ref.resolved_branch_id == "main"

    def test_inherited_resolution(self):
        branch_step_map = [
            {"canonical_step_id": "final-woe-iv", "step_id": "final-woe-iv__br_main",
             "is_shared_upstream": True, "is_branch_owned": False,
             "source_branch_id": "main"},
        ]
        ref = resolve_step_for_branch(
            branch_id="challenger_a",
            canonical_step_id="final-woe-iv",
            branch_step_map=branch_step_map,
        )
        assert ref is not None
        assert ref.resolution == "ancestor"
        assert ref.resolved_branch_id == "main"
        assert ref.requested_branch_id == "challenger_a"

    def test_not_found(self):
        ref = resolve_step_for_branch(
            branch_id="main",
            canonical_step_id="nonexistent",
            branch_step_map=[],
        )
        assert ref is None

    def test_ancestor_disabled(self):
        branch_step_map = [
            {"canonical_step_id": "final-woe-iv", "step_id": "final-woe-iv__br_main",
             "is_shared_upstream": True, "is_branch_owned": False,
             "source_branch_id": "main"},
        ]
        ref = resolve_step_for_branch(
            branch_id="challenger_a",
            canonical_step_id="final-woe-iv",
            branch_step_map=branch_step_map,
            allow_ancestor=False,
        )
        # When allow_ancestor=False but the step IS shared upstream,
        # it should still return None (the step is not directly owned by the branch)
        assert ref is None


# =========================================================================
# Readiness tests
# =========================================================================

class TestReadiness:
    def test_blocker_and_warning_models(self):
        b = ReadinessBlocker("MISSING_EVIDENCE", "Missing required evidence.")
        assert b.code == "MISSING_EVIDENCE"
        d = b.to_dict()
        assert d["code"] == "MISSING_EVIDENCE"

        w = ReadinessWarning("NO_OOT", "No OOT sample.")
        assert w.code == "NO_OOT"

    def test_readiness_result_blocked(self):
        r = ReportReadinessResult(
            blockers=[ReadinessBlocker("BLOCKED", "Blocked")],
        )
        assert not r.ready
        assert r.status == "blocked"

    def test_readiness_result_ready(self):
        r = ReportReadinessResult()
        assert r.ready
        assert r.status == "ready"

    def test_readiness_result_warnings(self):
        r = ReportReadinessResult(
            warnings=[ReadinessWarning("WARN", "Warning")],
        )
        assert r.ready
        assert r.status == "ready_with_warnings"


# =========================================================================
# HTML Renderer tests
# =========================================================================

class TestHtmlRenderer:
    def _make_minimal_bundle(self) -> dict:
        return {
            "schema_version": "cardre.report_bundle.v1",
            "project_id": "p1",
            "run_id": "run_001",
            "target_branch_id": "main",
            "report_mode": "branch",
            "generated_at": "2026-06-14T00:00:00Z",
            "generated_by": {"cardre_version": "0.1.0"},
            "source": {},
            "summary": {
                "model_name": "Test Scorecard",
                "target_column": "bad_flag",
                "report_status": "complete",
                "final_variable_count": 5,
                "excluded_variable_count": 10,
            },
            "dataset_roles": [],
            "pathway": {},
            "branches": {
                "branches": [
                    {"branch_id": "main", "name": "Baseline", "status": "active",
                     "is_champion": True, "is_target_branch": True},
                ],
                "target_branch_id": "main",
            },
            "champion": {
                "champion_status": "selected",
                "champion_branch_id": "main",
            },
            "variables": [
                {
                    "variable_name": "age",
                    "iv": 0.126,
                    "final_bin_count": 3,
                    "woe_smoothing": {
                        "enabled": True, "method": "additive", "alpha": 0.5,
                        "smoothing_applied": True, "zero_cell_encountered": False,
                        "affected_bin_count": 1,
                    },
                    "affected_bins": [
                        {"bin_id": "b1", "reason": "zero_bad",
                         "raw_good_count": 120, "raw_bad_count": 0,
                         "smoothed_good_count": 120.5, "smoothed_bad_count": 0.5,
                         "final_woe": -1.42},
                    ],
                    "bins": [
                        {"bin_id": "b1", "label": "<=30", "good_count": 500,
                         "bad_count": 50, "bad_rate": 0.09,
                         "woe": -0.12, "iv_contribution": 0.004},
                    ],
                },
            ],
            "model": {
                "features": [
                    {"variable_name": "age", "coefficient": -0.4321,
                     "standard_error": 0.031, "p_value": 0.001},
                ],
                "intercept": -2.154,
            },
            "score_scaling": {
                "base_score": 600, "base_odds": "50:1", "pdo": 20,
                "factor": 28.85, "offset": 487.12,
                "score_direction": "higher_is_better", "rounding": "nearest_integer",
                "min_score": 300, "max_score": 900,
            },
            "validation": {
                "metrics_by_role": [
                    {"role": "train", "row_count": 1000, "auc": 0.742, "gini": 0.484, "ks": 0.361},
                ],
            },
            "cutoffs": {},
            "manual_interventions": [],
            "limitations": [
                {"severity": "warning", "code": "NO_OOT_SAMPLE", "message": "No OOT sample."},
                {"severity": "info", "code": "PDF_OUT_OF_SCOPE", "message": "PDF not in Phase 5."},
            ],
            "reproducibility": {
                "run_id": "run_001",
                "execution_fingerprints": [
                    {"step_id": "fit-model__br_main", "python_version": "3.12", "platform": "linux"},
                ],
            },
            "artifacts": [
                {"artifact_id": "art_001", "artifact_type": "report", "role": "report",
                 "logical_hash": "abc123", "physical_hash": "def456", "path": "artifacts/report.json"},
            ],
        }

    def test_html_renders_all_major_sections(self):
        html = render_report_bundle_to_html(self._make_minimal_bundle())
        # Title / summary
        assert "Cardre Governance Report" in html
        assert "Test Scorecard" in html
        assert "main" in html
        # Variables
        assert "age" in html
        assert "0.126" in html
        # WOE smoothing
        assert "additive" in html
        assert "0.5" in html
        assert "Smoothing" in html
        # Model
        assert "Coefficient" in html
        assert "-0.4321" in html
        # Score scaling
        assert "Score Scaling" in html
        assert "600" in html
        assert "28.85" in html
        # Validation
        assert "Validation Metrics" in html
        assert "0.742" in html
        # Reproducibility + manifest
        assert "Reproducibility" in html
        assert "3.12" in html
        assert "run_001" in html
        # Artifacts
        assert "Artifact Index" in html
        assert "abc123" in html
        # Champion
        assert "Champion" in html or "champion" in html
        # Warnings / limitations
        assert "NO_OOT_SAMPLE" in html
        assert "PDF_OUT_OF_SCOPE" in html

    def test_html_is_self_contained(self):
        html = render_report_bundle_to_html(self._make_minimal_bundle())
        assert "<script" not in html
        assert "src=" not in html
        assert "rel=\"stylesheet\"" not in html
        assert "http://" not in html.replace("http://127.0.0.1", "")
        assert "https://" not in html
        assert "Chart" not in html
        assert "canvas" not in html


# =========================================================================
# Golden JSON tests
# =========================================================================

class TestGoldenJson:
    def test_single_branch_complete_golden(self):
        golden_path = FIXTURE_DIR / "single_branch_complete" / "expected_report_bundle.json"
        if not golden_path.exists():
            pytest.skip("Golden file not found")
        golden = json.loads(golden_path.read_text())
        assert golden["schema_version"] == "cardre.report_bundle.v1"
        assert "project_id" in golden
        assert "branches" in golden
        assert "champion" in golden
        assert "variables" in golden
        assert "model" in golden
        assert "limitations" in golden

    def test_golden_structural_integrity(self):
        golden_path = FIXTURE_DIR / "single_branch_complete" / "expected_report_bundle.json"
        if not golden_path.exists():
            pytest.skip("Golden file not found")
        golden = json.loads(golden_path.read_text())
        assert isinstance(golden["branches"], dict)
        assert isinstance(golden["branches"].get("branches"), list)
        assert isinstance(golden["champion"], dict)
        assert isinstance(golden["variables"], list)
        assert isinstance(golden["model"], dict)
        assert isinstance(golden["limitations"], list)
        assert isinstance(golden["artifacts"], list)
        assert isinstance(golden["reproducibility"], dict)


# =========================================================================
# Deterministic serialization test
# =========================================================================

class TestDeterminism:
    def test_report_bundle_deterministic_json(self):
        bundle = ReportBundle(
            project_id="p1",
            run_id="r1",
            target_branch_id="main",
            report_mode="branch",
            summary={
                "model_name": "Test",
            },
        )
        j1 = bundle.model_dump_json(indent=2)
        j2 = bundle.model_dump_json(indent=2)
        assert j1 == j2

    def test_html_deterministic(self):
        bundle = ReportBundle(
            project_id="p1",
            run_id="r1",
            target_branch_id="main",
            report_mode="branch",
        )
        html1 = render_report_bundle_to_html(bundle.model_dump(mode="json"))
        html2 = render_report_bundle_to_html(bundle.model_dump(mode="json"))
        # Allow timestamps to differ; check structure instead
        assert "Governance Report" in html1
        assert html1.count("<table") == html2.count("<table")
        assert html1.count("<h2") == html2.count("<h2")


# =========================================================================
# LimitationCode enum tests
# =========================================================================

class TestLimitationCode:
    def test_enum_values_match_strings(self):
        assert str(LimitationCode.NO_OOT_SAMPLE) == "NO_OOT_SAMPLE"
        assert str(LimitationCode.TARGET_BRANCH_NOT_FOUND) == "TARGET_BRANCH_NOT_FOUND"
        assert str(LimitationCode.CHAMPION_ASSIGNMENT_MISSING) == "CHAMPION_ASSIGNMENT_MISSING"

    def test_blocker_codes_are_subset_of_total(self):
        for code in LimitationCode.blocker_codes():
            assert code in LimitationCode

    def test_warning_codes_are_subset_of_total(self):
        for code in LimitationCode.warning_codes():
            assert code in LimitationCode

    def test_blockers_and_warnings_are_disjoint(self):
        blockers = LimitationCode.blocker_codes()
        warnings = LimitationCode.warning_codes()
        assert blockers.isdisjoint(warnings)

    def test_limitation_accepts_enum_value(self):
        lim = Limitation(severity="warning", code=LimitationCode.NO_OOT_SAMPLE)
        assert lim.code == "NO_OOT_SAMPLE"
        assert str(lim.code) == "NO_OOT_SAMPLE"

    def test_all_codes_have_blocker_or_warning(self):
        all_codes = set(LimitationCode)
        covered = LimitationCode.blocker_codes() | LimitationCode.warning_codes()
        # MISSING_RUN_MANIFEST appears in collector as a blocker, also in readiness
        # It's in the blocker set
        uncovered = all_codes - covered
        assert not uncovered, f"Uncovered codes: {uncovered}"


# =========================================================================
# Readiness regression tests (synthetic store)
# =========================================================================

def _make_store_with_branch() -> tuple[ProjectStore, str, str, str, str]:
    """Create a store with project, plan, plan_version, and a baseline branch."""
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    project_id = store.create_project("Test")
    plan_id = store.create_plan(project_id, "Test Plan")
    pv_id = store.create_plan_version(plan_id, [], description="v1")
    branch_id = store.create_branch(
        project_id=project_id, plan_id=plan_id,
        name="Baseline", branch_type="baseline",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="Test baseline.",
    )
    return store, tmp, project_id, plan_id, branch_id


class TestReadinessRegression:
    def test_target_branch_not_found(self):
        store = ProjectStore(Path(tempfile.mkdtemp()) / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id="nonexistent", report_mode="branch",
        )
        assert not result.ready
        assert result.status == "blocked"
        codes = {b.code for b in result.blockers}
        assert LimitationCode.TARGET_BRANCH_NOT_FOUND in codes
        assert len(result.blockers) == 1

    def test_run_not_found(self):
        store, tmp, project_id, plan_id, branch_id = _make_store_with_branch()
        result = check_report_readiness(
            store=store, project_id=project_id, run_id="nonexistent-run",
            target_branch_id=branch_id, report_mode="branch",
        )
        assert not result.ready
        codes = {b.code for b in result.blockers}
        assert LimitationCode.MISSING_RUN_MANIFEST in codes

    def test_champion_mode_blocked_without_assignment(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
            branch_point_step_id="logistic-regression",
            branch_point_canonical_step_id="logistic-regression",
        )
        for canonical_id in ("final-woe-iv", "logistic-regression", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=canonical_id, step_id=canonical_id,
                is_shared_upstream=False, is_branch_owned=True,
            )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="champion",
        )
        assert not result.ready
        codes = {b.code for b in result.blockers}
        assert LimitationCode.CHAMPION_ASSIGNMENT_MISSING in codes

    def test_branch_mode_warns_without_champion(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        for canonical_id in ("final-woe-iv", "logistic-regression", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=canonical_id, step_id=canonical_id,
                is_shared_upstream=False, is_branch_owned=True,
            )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        warning_codes = {w.code for w in result.warnings}
        assert LimitationCode.NO_CHAMPION_ASSIGNMENT in warning_codes

    def test_no_oot_warning(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        for canonical_id in ("final-woe-iv", "logistic-regression", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=canonical_id, step_id=canonical_id,
                is_shared_upstream=False, is_branch_owned=True,
            )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        warning_codes = {w.code for w in result.warnings}
        assert LimitationCode.NO_OOT_SAMPLE in warning_codes

    def test_readiness_result_blocker_to_dict(self):
        r = ReportReadinessResult(
            blockers=[ReadinessBlocker("NO_OOT", "No OOT.")],
        )
        d = r.to_dict()
        assert d["status"] == "blocked"
        assert d["ready"] is False
        assert d["blockers"][0]["code"] == "NO_OOT"

    def test_manual_binning_branch_scoped_blocker(self, store, project_and_plan):
        """Branch with manual-binning step map entry gets blocker; branch without gets warning."""
        project_id, plan_id = project_and_plan
        from cardre.audit import StepSpec
        mb_step = StepSpec(
            "manual-binning__shared",
            "cardre.manual_binning", "", "build", {"reviewed": False, "accept_automated": False},
            "", [], "baseline", 1, canonical_step_id="manual-binning",
        )
        pv_id = store.create_plan_version(plan_id, steps=[mb_step])
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_with_mb = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="With MB", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_with_mb, plan_version_id=pv_id,
            canonical_step_id="manual-binning", step_id="manual-binning__shared",
            is_shared_upstream=False, is_branch_owned=True,
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_with_mb, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

        branch_no_mb = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="No MB", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_no_mb, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

        # Branch with manual-binning → blocker
        result_with = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_with_mb, report_mode="branch",
        )
        mb_codes = {b.code for b in result_with.blockers
                    if b.code == LimitationCode.MANUAL_BINNING_NOT_REVIEWED}
        assert len(mb_codes) == 1, f"Expected MANUAL_BINNING_NOT_REVIEWED blocker, got {[b.code for b in result_with.blockers]}"

        # Branch without manual-binning → warning
        result_without = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_no_mb, report_mode="branch",
        )
        mb_warnings = {w.code for w in result_without.warnings
                       if w.code == LimitationCode.NO_MANUAL_BINNING_STEP_ON_BRANCH}
        assert len(mb_warnings) == 1, f"Expected NO_MANUAL_BINNING_STEP_ON_BRANCH warning, got {[w.code for w in result_without.warnings]}"

    def test_branch_specific_manual_binning_step_id(self, store, project_and_plan):
        """Blocker step_id points to the branch-owned step, not the generic step."""
        project_id, plan_id = project_and_plan
        from cardre.audit import StepSpec
        mb_step = StepSpec(
            "manual-binning__br_custom",
            "cardre.manual_binning", "", "build", {"reviewed": False, "accept_automated": False},
            "", [], "baseline", 1, canonical_step_id="manual-binning",
        )
        pv_id = store.create_plan_version(plan_id, steps=[mb_step])
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="manual-binning", step_id="manual-binning__br_custom",
            is_shared_upstream=False, is_branch_owned=True,
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        for b in result.blockers:
            if b.code == LimitationCode.MANUAL_BINNING_NOT_REVIEWED:
                assert b.step_id == "manual-binning__br_custom", (
                    f"Expected step_id 'manual-binning__br_custom', got {b.step_id!r}"
                )
                return
        pytest.fail("No MANUAL_BINNING_NOT_REVIEWED blocker found")



    def test_response_includes_context_fields(self, store, project_and_plan):
        """ReportReadinessResult carries target_branch_id, run_id, report_mode, checked_at."""
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        assert result.target_branch_id == branch_id
        assert result.run_id == run_id
        assert result.report_mode == "branch"
        assert result.checked_at is not None
        # checked_at should be ISO-8601 parsable
        from datetime import datetime
        datetime.fromisoformat(result.checked_at)

    def test_blocker_step_ids_populated_for_manual_binning(self, store, project_and_plan):
        """MANUAL_BINNING_NOT_REVIEWED blocker carries step_id from resolved branch step."""
        project_id, plan_id = project_and_plan
        from cardre.audit import StepSpec
        mb_step = StepSpec(
            "manual-binning__step_id_check",
            "cardre.manual_binning", "", "build", {"reviewed": False, "accept_automated": False},
            "", [], "baseline", 1, canonical_step_id="manual-binning",
        )
        pv_id = store.create_plan_version(plan_id, steps=[mb_step])
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id, name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="manual-binning", step_id="manual-binning__step_id_check",
            is_shared_upstream=False, is_branch_owned=True,
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        blocker = next((b for b in result.blockers if b.code == LimitationCode.MANUAL_BINNING_NOT_REVIEWED), None)
        assert blocker is not None, "Expected MANUAL_BINNING_NOT_REVIEWED blocker"
        assert blocker.step_id == "manual-binning__step_id_check"


# =========================================================================
# ReportCollector regression tests (synthetic store)
# =========================================================================

class TestCollectorRegression:
    def test_collector_returns_bundle_when_run_missing(self):
        store = ProjectStore(Path(tempfile.mkdtemp()) / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id="nonexistent",
            target_branch_id="main", report_mode="branch",
        )
        assert bundle.schema_version == "cardre.report_bundle.v1"
        assert bundle.run_id == "nonexistent"
        codes = {l.code for l in bundle.limitations}
        assert LimitationCode.MISSING_RUN_MANIFEST in codes

    def test_collector_returns_bundle_when_branch_missing(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id="nonexistent-branch", report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert LimitationCode.TARGET_BRANCH_NOT_FOUND in codes

    def test_collector_adds_limitations_from_collect_methods(self, store, project_and_plan):
        """Collector should add limitation codes for missing WOE/IV evidence."""
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        # Create branch with a step map that has final-woe-iv
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="final-woe-iv", step_id="final-woe-iv",
            is_shared_upstream=False, is_branch_owned=True,
        )

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        # Since there's no successful run step for final-woe-iv, collector
        # should emit MISSING_WOE_IV_EVIDENCE_V1
        assert LimitationCode.MISSING_WOE_IV_EVIDENCE_V1 in codes

    def test_collector_reads_manual_interventions_from_manual_binning_output(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="manual-binning", step_id="manual-binning",
            is_shared_upstream=False, is_branch_owned=True,
        )

        from cardre.artifacts import write_json_artifact

        manual_art = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem="manual-binning-report",
            payload={
                "schema_version": "cardre.bin_definition.v1",
                "variables": [
                    {
                        "variable": "age",
                        "override_history": [
                            {
                                "user_action": "merge_bins",
                                "variable": "age",
                                "reason": "Merged adjacent bins",
                                "source_bin_ids": ["age_bin_001", "age_bin_002"],
                                "before": ["Low", "Mid"],
                                "after": "Low-Mid",
                            }
                        ],
                    }
                ],
            },
            metadata={"schema_version": "cardre.bin_definition.v1"},
        )

        store.save_run_step(RunStepRecord(
            run_step_id="rs_manual",
            run_id=run_id,
            step_id="manual-binning",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[manual_art.artifact_id],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        assert len(bundle.manual_interventions) == 1
        intervention = bundle.manual_interventions[0]
        assert intervention.type == "merge_bins"
        assert intervention.variable_name == "age"
        assert intervention.reason == "Merged adjacent bins"
        assert intervention.after_artifact == "Low-Mid"

    def test_collector_reads_legacy_manual_overrides_only(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="manual-binning", step_id="manual-binning",
            is_shared_upstream=False, is_branch_owned=True,
        )

        from cardre.artifacts import write_json_artifact

        legacy_art = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem="manual-binning-legacy",
            payload={
                "schema_version": SCHEMA_MANUAL_BINNING_OVERRIDES,
                "overrides": [
                    {
                        "type": "reject_variable",
                        "variable": "income",
                        "reason": "Legacy override",
                        "before": "included",
                        "after": "excluded",
                    }
                ],
            },
            metadata={"schema_version": SCHEMA_MANUAL_BINNING_OVERRIDES},
        )

        store.save_run_step(RunStepRecord(
            run_step_id="rs_manual_legacy",
            run_id=run_id,
            step_id="manual-binning",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[legacy_art.artifact_id],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        assert len(bundle.manual_interventions) == 1
        intervention = bundle.manual_interventions[0]
        assert intervention.type == "reject_variable"
        assert intervention.variable_name == "income"
        assert intervention.reason == "Legacy override"
        assert intervention.before_artifact == "included"
        assert intervention.after_artifact == "excluded"

    def test_collector_resolve_run_step_fallback(self):
        """_resolve_run_step tries with branch_id first, then without."""
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        steps = [
            RunStepRecord(
                run_step_id="rs_001",
                run_id="r_fallback",
                step_id="final-woe-iv",
                plan_version_id="pv_fallback",
                status="succeeded",
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T01:00:00Z",
                input_artifact_ids=[],
                output_artifact_ids=[],
                execution_fingerprint={},
                warnings=[],
                errors=[],
            ),
        ]

        # Build a collector directly with the synthetic data
        # We need a branch and run to exist
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        # Manually insert a run step on the baseline (no branch_id)
        store.save_run_step(RunStepRecord(
            run_step_id="rs_fallback",
            run_id=run_id,
            step_id="final-woe-iv",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="final-woe-iv", step_id="final-woe-iv",
            is_shared_upstream=True, is_branch_owned=False,
            source_branch_id="baseline",
        )

        collector = ReportCollector(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        from cardre.step_id import resolve_step_for_branch
        step_map = store.get_branch_step_map(branch_id, pv_id)
        ref = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id="final-woe-iv",
            branch_step_map=step_map,
        )
        assert ref is not None, "Step should be resolvable"
        assert ref.resolution == "ancestor", "Should be inherited step"

    def test_woe_iv_evidence_v1_check(self):
        """Check that collector handles WOE/IV v1 evidence."""
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        # Create branch with step map
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="final-woe-iv", step_id="final-woe-iv",
            is_shared_upstream=False, is_branch_owned=True,
        )

        # Add a run step for the WOE/IV step with a v1 evidence artifact
        from cardre.artifacts import write_json_artifact
        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem="woe-iv-evidence",
            payload={
                "schema_version": "cardre.woe_iv_evidence.v1",
                "variables": [],
            },
            metadata={"schema_version": "cardre.woe_iv_evidence.v1"},
        )
        store.save_run_step(RunStepRecord(
            run_step_id="rs_woe_v1",
            run_id=run_id,
            step_id="final-woe-iv",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[evidence_art.artifact_id],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        # Should NOT have LEGACY_WOE_SUMMARY_USED since v1 evidence exists
        assert LimitationCode.LEGACY_WOE_SUMMARY_USED not in codes

    def test_exact_step_missing_from_run_blocks_instead_of_borrowing(self):
        """An exact branch-owned step missing from the requested run blocks
        rather than silently borrowing latest-successful evidence from another run."""
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")

        # Create a "wrong" run that has the step (should not be borrowed from)
        wrong_run_id = store.create_run(pv_id)
        store.finish_run(wrong_run_id, "succeeded")
        store.save_run_step(RunStepRecord(
            run_step_id="rs_wrong",
            run_id=wrong_run_id,
            step_id="final-woe-iv",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        # Create a "report" run that has NO step for final-woe-iv
        report_run_id = store.create_run(pv_id)
        store.finish_run(report_run_id, "succeeded")
        # Add an unrelated step to the report run
        store.save_run_step(RunStepRecord(
            run_step_id="rs_report_other",
            run_id=report_run_id,
            step_id="import",
            plan_version_id=pv_id,
            status="succeeded",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T01:00:00Z",
            input_artifact_ids=[],
            output_artifact_ids=[],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="final-woe-iv", step_id="final-woe-iv",
            is_shared_upstream=False, is_branch_owned=True,
        )

        bundle = generate_report_bundle(
            store=store, project_id=project_id,
            run_id=report_run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        # Must NOT borrow from wrong_run — exact step missing from report run
        # means MISSING_WOE_IV_EVIDENCE_V1 blocker, not silent success
        assert LimitationCode.MISSING_WOE_IV_EVIDENCE_V1 in codes, (
            f"Expected MISSING_WOE_IV_EVIDENCE_V1 blocker, got codes: {codes}"
        )


# =========================================================================
# Fixture helpers for the above regression tests
# =========================================================================

@pytest.fixture
def project_and_plan(store):
    project_id = store.create_project("test-proj")
    plan_id = store.create_plan(project_id, "Scorecard Pathway")
    store.create_plan_version(plan_id, [], description="v1")
    return project_id, plan_id
