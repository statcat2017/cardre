"""Acceptance tests for cardre.reporting — full audit pack generation and summary reports."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre.audit import (
    ExecutionContext,
    StepSpec,
    json_logical_hash,
)
from cardre.executor import PlanExecutor
from cardre.nodes import BuildSummaryReportNode
from cardre.registry import NodeRegistry
from cardre.reporting.collector import generate_report_bundle
from cardre.reporting.readiness import check_report_readiness
from cardre.services.export_service import export_branch_audit_pack
from cardre.store import ProjectStore

from tests.helpers import SAMPLE_GERMAN_CREDIT_LINES, _make_json_artifact, _make_parquet_report, _make_train_artifact, make_store


def _make_german_credit_file(tmp: Path) -> Path:
    """Create a German Credit fixture with 10 rows for meaningful pathway execution."""
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    header = ",".join(columns)
    rows = [",".join(line.split()) for line in SAMPLE_GERMAN_CREDIT_LINES * 5]
    p = tmp / "german_credit.csv"
    p.write_text("\n".join([header] + rows))
    return p


def _create_branch_with_step_map(
    store: ProjectStore,
    branch_id: str,
    project_id: str,
    plan_id: str,
    plan_version_id: str,
) -> None:
    """Create a branch record with full branch_step_map."""
    now = "2026-06-14T00:00:00Z"
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO plan_branches (branch_id, project_id, plan_id, name, description, "
            "branch_type, status, base_branch_id, base_plan_version_id, head_plan_version_id, "
            "branch_point_step_id, branch_point_canonical_step_id, created_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_id, project_id, plan_id, branch_id, None,
             "baseline", "active", None, plan_version_id, plan_version_id,
             None, None, "Automated test", now, now),
        )
    steps = store.get_plan_version_steps(plan_version_id)
    for s in steps:
        store.create_branch_step_map(
            branch_id=branch_id,
            plan_version_id=plan_version_id,
            canonical_step_id=s.canonical_step_id or s.step_id,
            step_id=s.step_id,
            is_branch_owned=True,
            is_shared_upstream=False,
        )


def _assign_champion(store: ProjectStore, project_id: str, plan_id: str, branch_id: str) -> None:
    """Create a comparison snapshot and champion assignment for a branch."""
    from cardre.artifacts import write_json_artifact
    from cardre.services.comparison_service import create_comparison
    from cardre.services.champion_service import assign_champion

    comp = create_comparison(
        store=store,
        project_id=project_id,
        plan_id=plan_id,
        baseline_branch_id=branch_id,
        challenger_branch_ids=[],
        comparison_spec={"roles": ["train"]},
        created_reason="Test",
    )
    snap_art = write_json_artifact(
        store, artifact_type="report", role="report",
        stem=f"comparison-snapshot-{comp['comparison_id']}",
        payload={"dummy": True},
    )
    snapshot_id = str(uuid.uuid4())
    now = "2026-06-14T00:00:00Z"
    pv_id = store.get_latest_plan_version_id(plan_id)
    store._connect().execute(
        "INSERT INTO branch_comparison_snapshots "
        "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
        "comparison_artifact_id, readiness_json, source_plan_version_ids_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (snapshot_id, comp["comparison_id"], project_id, plan_id,
         snap_art.artifact_id, '{"ready": true}',
         json.dumps([pv_id]), now),
    )
    assign_champion(
        store=store,
        project_id=project_id,
        plan_id=plan_id,
        branch_id=branch_id,
        comparison_id=comp["comparison_id"],
        comparison_snapshot_id=snapshot_id,
        assigned_reason="Best OOT Gini and simpler binning.",
    )


# =========================================================================
# Acceptance test 1: Champion report with full pathway
# =========================================================================

@pytest.mark.e2e
class TestAcceptanceChampionReport:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="cardre_p5_acc1_"))
        self.store = ProjectStore(self._tmpdir)
        self.store.initialize()

        # Register scorecard pathway
        from sidecar.proof_pathway import register_scorecard_pathway
        self.project_id = self.store.create_project("Acceptance Test")
        self.plan_id = register_scorecard_pathway(self.store, self.project_id)

        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        # Create CSV data
        source = _make_german_credit_file(self._tmpdir)
        self.source_path = str(source)

        yield
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _import_dataset_and_run(self) -> str:
        """Update the import step's source_path and run the full pathway."""
        from cardre.services.plan_service import PlanService

        plan_service = PlanService(self.store)
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="import",
            base_plan_version_id=self.pv_id,
            params={"source_path": self.source_path},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        # Configure metadata
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="define-metadata",
            base_plan_version_id=self.pv_id,
            params={
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [],
            },
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        # Also update validate-target and split target_column
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="validate-target",
            base_plan_version_id=self.pv_id,
            params={"target_column": "credit_risk_class"},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="split",
            base_plan_version_id=self.pv_id,
            params={
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "credit_risk_class", "role_column": None, "random_seed": 42,
            },
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        # Lower min_iv to let all variables through with small test data
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="variable-selection",
            base_plan_version_id=self.pv_id,
            params={"min_iv": 0.0, "max_variables": 20, "manual_includes": [], "manual_excludes": []},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        # Run the plan
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(self.store, self.pv_id)
        return run_id

    def test_acceptance_1_full_champion_report(self):
        """Complete champion branch generates audit pack with report."""
        run_id = self._import_dataset_and_run()
        assert run_id is not None

        # Verify run succeeded
        run = self.store.get_run(run_id)
        assert run["status"] == "succeeded", f"Run status: {run['status']}"

        branch_id = "main"
        _create_branch_with_step_map(self.store, branch_id, self.project_id,
                                      self.plan_id, self.pv_id)
        _assign_champion(self.store, self.project_id, self.plan_id, branch_id)

        # Generate report bundle
        bundle = generate_report_bundle(
            store=self.store,
            project_id=self.project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="champion",
        )
        assert bundle.schema_version == "cardre.report_bundle.v1"
        assert bundle.report_mode == "champion"

        # Champion should be selected
        assert bundle.champion.champion_status == "selected", \
            f"Expected selected, got {bundle.champion.champion_status}"
        assert bundle.champion.target_branch_is_champion is True

        # Should have variables with WOE/IV evidence
        assert len(bundle.variables) > 0, "Expected at least one variable"

        # Export audit pack with report
        result = export_branch_audit_pack(
            store=self.store,
            project_id=self.project_id,
            plan_id=self.plan_id,
            branch_id=branch_id,
            include_report=True,
            report_mode="champion",
        )
        export_dir = Path(result["export_path"])
        assert export_dir.exists()

        # Verify report files exist
        report_bundle = export_dir / "report" / "report_bundle.json"
        assert report_bundle.exists(), f"report_bundle.json not found"

        report_html = export_dir / "report" / "report.html"
        assert report_html.exists(), f"report.html not found"

        # Verify HTML is self-contained
        html_content = report_html.read_text()
        assert "<script" not in html_content
        assert "rel=\"stylesheet\"" not in html_content

        # Verify checksums include report files
        checksums_file = export_dir / "checksums.sha256"
        assert checksums_file.exists()
        checksums_content = checksums_file.read_text()
        assert "report_bundle.json" in checksums_content
        assert "report.html" in checksums_content
        assert "branch.json" in checksums_content  # Phase 4 file preserved

        # Verify champion assignment in export
        champ_file = export_dir / "champion_assignment.json"
        assert champ_file.exists()

        # Verify bundle determinism
        with open(report_bundle) as f:
            bundle_data = json.loads(f.read())
        bundle2 = generate_report_bundle(
            store=self.store,
            project_id=self.project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="champion",
        )
        bundle2_data = bundle2.model_dump(mode="json")
        assert bundle_data["variables"] == bundle2_data["variables"]
        assert bundle_data["model"] == bundle2_data["model"]

        # Verify no hardcoded step IDs in pathway
        for step in bundle_data.get("pathway", {}).get("steps", []):
            assert step.get("resolution") in ("exact", "ancestor")


# =========================================================================
# Acceptance test 2: No champion branch
# =========================================================================

@pytest.mark.e2e
class TestAcceptanceNoChampionBranch:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="cardre_p5_acc2_"))
        self.store = ProjectStore(self._tmpdir)
        self.store.initialize()

        from sidecar.proof_pathway import register_scorecard_pathway
        self.project_id = self.store.create_project("No Champion Test")
        self.plan_id = register_scorecard_pathway(self.store, self.project_id)
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        source = _make_german_credit_file(self._tmpdir)
        self.source_path = str(source)

        yield
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_pathway(self) -> str:
        from cardre.services.plan_service import PlanService
        plan_service = PlanService(self.store)
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="import",
            base_plan_version_id=self.pv_id,
            params={"source_path": self.source_path},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="define-metadata",
            base_plan_version_id=self.pv_id,
            params={
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [],
            },
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="validate-target",
            base_plan_version_id=self.pv_id,
            params={"target_column": "credit_risk_class"},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)
        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="split",
            base_plan_version_id=self.pv_id,
            params={
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "credit_risk_class", "role_column": None, "random_seed": 42,
            },
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        plan_service.update_params(
            plan_id=self.plan_id,
            step_id="variable-selection",
            base_plan_version_id=self.pv_id,
            params={"min_iv": 0.0, "max_variables": 20, "manual_includes": [], "manual_excludes": []},
        )
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(self.store, self.pv_id)
        return run_id

    def test_branch_mode_warns_no_champion(self):
        """Branch mode report generates with NO_CHAMPION_ASSIGNMENT warning."""
        run_id = self._run_pathway()
        run = self.store.get_run(run_id)
        assert run["status"] == "succeeded", f"Run failed: {run['status']}"

        branch_id = "challenger_a"
        _create_branch_with_step_map(self.store, branch_id, self.project_id,
                                      self.plan_id, self.pv_id)

        readiness = check_report_readiness(
            store=self.store,
            project_id=self.project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="branch",
        )
        assert readiness.ready, f"Branch mode should be ready, blockers: {[b.code for b in readiness.blockers]}"
        warning_codes = {w.code for w in readiness.warnings}
        assert "NO_CHAMPION_ASSIGNMENT" in warning_codes, \
            f"Expected NO_CHAMPION_ASSIGNMENT, got: {warning_codes}"

        bundle = generate_report_bundle(
            store=self.store,
            project_id=self.project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="branch",
        )
        assert bundle.champion.champion_status == "not_available"
        limitation_codes = {l.code for l in bundle.limitations}
        assert "NO_CHAMPION_ASSIGNMENT" in limitation_codes

    def test_champion_mode_blocked(self):
        """Champion mode is blocked without champion assignment."""
        run_id = self._run_pathway()
        run = self.store.get_run(run_id)
        assert run["status"] == "succeeded"

        branch_id = "challenger_a"
        _create_branch_with_step_map(self.store, branch_id, self.project_id,
                                      self.plan_id, self.pv_id)

        readiness = check_report_readiness(
            store=self.store,
            project_id=self.project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="champion",
        )
        assert not readiness.ready, "Champion mode should be blocked"
        blocker_codes = {b.code for b in readiness.blockers}
        assert "CHAMPION_ASSIGNMENT_MISSING" in blocker_codes, \
            f"Expected CHAMPION_ASSIGNMENT_MISSING, got: {blocker_codes}"


# ======================================================================
# Build Summary Report
# ======================================================================

class BuildSummaryReportTests(unittest.TestCase):

    def test_build_summary_created(self) -> None:
        store, tmp = make_store()
        store.initialize()

        scorecard = {
            "base_score": 600, "base_odds": 50,
            "points_to_double_odds": 20, "higher_score_is_lower_risk": True,
            "intercept": -0.5, "base_points": 500, "attributes": [],
            "target_column": "target",
        }
        sc_art = _make_json_artifact(store, scorecard, role="scorecard", stem="sc")

        model = {
            "target_column": "target", "features": ["x_woe"],
            "intercept": -0.5, "coefficients": {"x_woe": 0.8},
            "class_mapping": {"good": "g", "bad": "b"},
            "training": {"row_count": 100, "converged": True, "iterations": 10, "params": {}},
            "warnings": [],
        }
        model_art = _make_json_artifact(store, model, role="model", stem="model3")

        woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["Low"],
            "row_count": [50], "good_count": [40], "bad_count": [10],
            "good_distribution": [0.5], "bad_distribution": [0.5],
            "woe": [0.3], "iv_component": [0.1],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe3")

        params = {}
        spec = StepSpec(
            step_id="bsr", node_type="cardre.build_summary_report",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[sc_art, model_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = BuildSummaryReportNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "report")
        report = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("model_summary", report)
        self.assertIn("scorecard_summary", report)
        self.assertIn("woe_iv_references", report)
