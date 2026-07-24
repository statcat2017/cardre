"""Tests for the full-section HTML report renderer.

Verifies that the renderer emits every section of the ReportBundle,
preserving the full report structure from the legacy renderer.
"""

from __future__ import annotations

from cardre.adapters.rendering.html_report import HtmlReportRenderer
from cardre.application.reporting.schema import (
    ArtifactEntry,
    CalibrationBin,
    CalibrationRole,
    ChampionInfo,
    CoefficientSignEntry,
    CutoffInfo,
    CutoffTable,
    DatasetRole,
    DatasetTargetSummary,
    DiagnosticEntry,
    ExclusionRuleInfo,
    ExclusionSummaryInfo,
    ImplementationArtifactInfo,
    ImplementationArtifactsInfo,
    Limitation,
    ManualBinningReviewState,
    ManualIntervention,
    MetricsByRole,
    ModelDiagnosticsInfo,
    ModelFeature,
    ModelInfo,
    PathwayStep,
    PathwaySummary,
    PsiEntry,
    RedundancyCluster,
    RedundancyClusterMember,
    RedundancyReviewInfo,
    ReportBundle,
    ReportSummary,
    SampleDefinitionInfo,
    ScoreScalingInfo,
    StabilityInfo,
    ValidationInfo,
    VariableInfo,
    VariableSelectionInfo,
)


def _full_bundle() -> ReportBundle:
    return ReportBundle(
        project_id="p1", run_id="r1", target_branch_id="b1",
        generated_at="2026-07-24T12:00:00Z",
        summary=ReportSummary(model_name="Test Model", target_column="credit_risk",
                              final_variable_count=5, excluded_variable_count=3,
                              target_branch_id="b1", champion_branch_id="b1"),
        dataset_roles=[DatasetRole(role="train", dataset_id="d1", row_count=100, column_count=5,
                                   target=DatasetTargetSummary(good_count=80, bad_count=20, bad_rate=0.2))],
        pathway=PathwaySummary(steps=[PathwayStep(canonical_step_id="sample-definition", step_id="s1", status="succeeded")]),
        champion=ChampionInfo(champion_status="assigned", champion_branch_id="b1"),
        variables=[VariableInfo(variable_name="income", role="included", iv=0.5, final_bin_count=4)],
        model=ModelInfo(target="risk", features=[ModelFeature(variable_name="income", coefficient=1.5)],
                        intercept=2.0),
        score_scaling=ScoreScalingInfo(base_score=600, points_to_double_odds=20),
        validation=ValidationInfo(
            metrics_by_role=[MetricsByRole(role="train", row_count=100, auc=0.8, gini=0.6, ks=0.4)],
            stability=StabilityInfo(psi_by_role=[PsiEntry(comparison="train_test", score_psi=0.1)]),
        ),
        cutoffs=CutoffInfo(cutoff_tables=[CutoffTable(role="train")]),
        manual_interventions=[ManualIntervention(intervention_id="i1", variable_name="income")],
        manual_binning_review=ManualBinningReviewState(review_status="reviewed", edited_variable_count=1),
        redundancy_review=RedundancyReviewInfo(method="correlation", cluster_count=2,
                                                clusters=[RedundancyCluster(cluster_id="c1",
                                                    variables=[RedundancyClusterMember(variable="income")])]),
        limitations=[Limitation(severity="warning", code="W1", message="test")],
        artifacts=[ArtifactEntry(artifact_id="a1", artifact_type="json", role="output")],
        run_status={"run_id": "r1", "status": "succeeded",
                    "diagnostics": [DiagnosticEntry(code="D1", message="diag")]},
        exclusion_summary=ExclusionSummaryInfo(rows_before=100, rows_after=90,
                                                rules=[ExclusionRuleInfo(rule_id="e1", reason="missing")]),
        sample_definition=SampleDefinitionInfo(sample_method="random", sample_domain="otb"),
        variable_selection=VariableSelectionInfo(selected_variables=["income"], min_iv=0.1),
        model_diagnostics=ModelDiagnosticsInfo(
            coefficient_sign_check=[CoefficientSignEntry(variable_name="income", coefficient_sign="positive", status="ok")],
            calibration_diagnostics={"train": CalibrationRole(row_count=100, n_bins=10,
                decile_bins=[CalibrationBin(bin=1, count=10, observed_events=3, expected_events=2.5)])},
        ),
        implementation_artifacts=ImplementationArtifactsInfo(
            scorecard_table=ImplementationArtifactInfo(artifact_id="sc1", description="scorecard"),
        ),
    )


EXPECTED_SECTIONS = [
    "Executive Summary", "Pathway", "Dataset Roles", "Branches", "Champion", "Variables",
    "Model", "Score Scaling", "Validation", "Cutoffs", "Manual Interventions",
    "Manual Binning Review", "Redundancy Review", "Model Diagnostics",
    "Implementation Artifacts", "Sample Definition", "Variable Selection",
    "Exclusion Summary", "Run Status", "Reproducibility", "Artifacts",
    "Modelling Metadata", "Limitations",
]


class TestHtmlRendererFullSections:
    def test_renders_all_sections(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        for section in EXPECTED_SECTIONS:
            assert f"<h2>{section}</h2>" in html, f"Missing section: {section}"

    def test_renders_champion_assignment(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "assigned" in html
        assert "b1" in html

    def test_renders_cutoff_table_role(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "train" in html

    def test_renders_calibration_diagnostics(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "Calibration" in html
        assert "income" in html

    def test_renders_exclusion_rules(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "missing" in html

    def test_renders_manual_binning_review(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "reviewed" in html

    def test_renders_implementation_artifacts(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "scorecard" in html.lower()

    def test_renders_empty_bundle_without_error(self):
        html = HtmlReportRenderer.render_to_html(ReportBundle(project_id="p", run_id="r"))
        for section in EXPECTED_SECTIONS:
            assert f"<h2>{section}</h2>" in html
        assert "No data" in html or "None" in html or "No champion" in html

    def test_renders_blocker_severity_class(self):
        from cardre.application.reporting.schema import Limitation
        bundle = ReportBundle(project_id="p", run_id="r", limitations=[
            Limitation(severity="blocker", code="B1", message="blocked"),
        ])
        html = HtmlReportRenderer.render_to_html(bundle)
        assert "class='blocker'" in html

    def test_executive_summary_shows_model_name_and_target(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "Test Model" in html
        assert "credit_risk" in html

    def test_executive_summary_shows_variable_counts(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "Final variable count" in html
        assert "5" in html
        assert "Excluded variable count" in html
        assert "3" in html

    def test_executive_summary_shows_champion_and_target_branch(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "Champion branch" in html
        assert "Target branch" in html
        assert "b1" in html

    def test_header_shows_generation_metadata(self):
        html = HtmlReportRenderer.render_to_html(_full_bundle())
        assert "Generated:" in html
        assert "2026-07-24T12:00:00Z" in html
