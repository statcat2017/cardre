"""Evidence matching profiles — maps EvidenceKind to expected artifact shape."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.schemas import (
    SCHEMA_APPLY_MODEL_EVIDENCE,
    SCHEMA_APPLY_WOE_EVIDENCE,
    SCHEMA_CALIBRATION_DIAGNOSTICS,
    SCHEMA_CALIBRATION_REPORT,
    SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
    SCHEMA_COMPARISON_ARTIFACT,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_ENSEMBLE_MODEL_ARTIFACT,
    SCHEMA_EXCLUSION_SUMMARY,
    SCHEMA_EXPLAINABILITY_REPORT,
    SCHEMA_FAIRNESS_REPORT,
    SCHEMA_FEATURE_SELECTION_EVIDENCE,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_HYPERPARAMETER_TUNING_EVIDENCE,
    SCHEMA_IV_TABLE,
    SCHEMA_MANUAL_BINNING_OVERRIDES,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_PROFILE_SUMMARY,
    SCHEMA_PROXY_RISK_REPORT,
    SCHEMA_REJECT_INFERENCE_RESULT,
    SCHEMA_REJECT_POPULATION_CONFIG,
    SCHEMA_REPORT_BUNDLE,
    SCHEMA_RESAMPLING_EVIDENCE,
    SCHEMA_RUN_SUMMARY,
    SCHEMA_SAMPLE_DEFINITION,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_SEPARATION_DIAGNOSTICS,
    SCHEMA_SPLIT_SUMMARY,
    SCHEMA_TECHNICAL_MANIFEST_INDEX,
    SCHEMA_VALIDATION_EVIDENCE,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
    SCHEMA_VIF_DIAGNOSTICS,
    SCHEMA_WOE_IV_EVIDENCE,
    SCHEMA_WOE_TABLE,
    SCHEMA_WOE_TRANSFORM_EVIDENCE,
)
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION


@dataclass
class _Profile:
    expected_roles: set[str]
    expected_artifact_types: set[str]
    schema_version: str
    expected_media_types: set[str] = field(default_factory=lambda: {"application/json"})
    required_keys: set[str] | None = None
    exclude_key: str | None = None
    required_columns: set[str] | None = None


EVIDENCE_PROFILES: dict[EvidenceKind, _Profile] = {
    EvidenceKind.MODELLING_METADATA: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition", "modelling_metadata"},
        schema_version=SCHEMA_MODELLING_METADATA,
        required_keys={"target_column", "good_values", "bad_values"},
    ),
    EvidenceKind.SAMPLE_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition", "sample_definition"},
        schema_version=SCHEMA_SAMPLE_DEFINITION,
        required_keys={"sample_method"},
    ),
    EvidenceKind.SPLIT_SUMMARY: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "split_summary"},
        schema_version=SCHEMA_SPLIT_SUMMARY,
        required_keys={"strategy", "row_counts"},
    ),
    EvidenceKind.PROFILE_SUMMARY: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"profile_summary", "report"},
        schema_version=SCHEMA_PROFILE_SUMMARY,
        required_keys={"profiles"},
    ),
    EvidenceKind.EXCLUSION_SUMMARY: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"exclusion_summary", "report"},
        schema_version=SCHEMA_EXCLUSION_SUMMARY,
        required_keys={"rows_before", "rows_after", "rules"},
    ),
    EvidenceKind.REJECT_POPULATION_CONFIG: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_REJECT_POPULATION_CONFIG,
        required_keys={"total_rows", "rejection_source"},
    ),
    EvidenceKind.REJECT_INFERENCE_RESULT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"reject_inference_result", "report"},
        schema_version=SCHEMA_REJECT_INFERENCE_RESULT,
        required_keys={"method", "missingness_assumption"},
    ),
    EvidenceKind.BIN_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"bin_definition", "definition"},
        schema_version=SCHEMA_BIN_DEFINITION,
        required_keys={"variables"},
        exclude_key="selected",
    ),
    EvidenceKind.SELECTION_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition", "selection_definition"},
        schema_version=SCHEMA_SELECTION_DEFINITION,
        required_keys={"selected"},
    ),
    EvidenceKind.WOE_TRANSFORM_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "woe_transform_evidence"},
        schema_version=SCHEMA_WOE_TRANSFORM_EVIDENCE,
        required_keys={"target_column", "transformed_variables"},
    ),
    EvidenceKind.WOE_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"dataset", "report", "woe_table"},
        schema_version=SCHEMA_WOE_TABLE,
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"variable", "bin_id", "woe"},
    ),
    EvidenceKind.IV_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"dataset", "iv_table", "report"},
        schema_version=SCHEMA_IV_TABLE,
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"iv", "variable"},
    ),
    EvidenceKind.WOE_IV_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "woe_iv_evidence"},
        schema_version=SCHEMA_WOE_IV_EVIDENCE,
        required_keys={"variables"},
    ),
    EvidenceKind.VARIABLE_CLUSTERING: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "variable_clustering"},
        schema_version=SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
        required_keys={"method", "clusters"},
    ),
    EvidenceKind.SCORED_DATASET: _Profile(
        expected_roles={"train", "test", "oot"},
        expected_artifact_types={"dataset", "scored_dataset"},
        schema_version="",
        expected_media_types={"application/vnd.apache.parquet"},
    ),
    EvidenceKind.MODEL_ARTIFACT: _Profile(
        expected_roles={"model", "report", "definition"},
        expected_artifact_types={"definition", "model", "model_artifact", "report"},
        schema_version=SCHEMA_MODEL_ARTIFACT,
        required_keys={"model_family"},
    ),
    EvidenceKind.ENSEMBLE_MODEL_ARTIFACT: _Profile(
        expected_roles={"model"},
        expected_artifact_types={"ensemble_model_artifact", "model"},
        schema_version=SCHEMA_ENSEMBLE_MODEL_ARTIFACT,
        required_keys={"model_family", "model_payload"},
    ),
    EvidenceKind.SCORE_SCALING: _Profile(
        expected_roles={"scorecard", "report"},
        expected_artifact_types={"report", "score_scaling", "scorecard"},
        schema_version=SCHEMA_SCORE_SCALING,
        required_keys={"factor", "offset"},
    ),
    EvidenceKind.VALIDATION_METRICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "validation_metrics"},
        schema_version=SCHEMA_VALIDATION_METRICS,
        required_keys={"metrics"},
    ),
    EvidenceKind.CUTOFF_ANALYSIS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"cutoff_analysis", "report"},
        schema_version=SCHEMA_CUTOFF_ANALYSIS,
        required_keys={"cutoff_tables"},
    ),
    EvidenceKind.MANUAL_BINNING_OVERRIDES: _Profile(
        expected_roles={"definition", "report"},
        expected_artifact_types={"definition", "manual_binning_overrides", "report"},
        schema_version=SCHEMA_MANUAL_BINNING_OVERRIDES,
    ),
    EvidenceKind.FROZEN_SCORECARD_BUNDLE: _Profile(
        expected_roles={"scorecard"},
        expected_artifact_types={"frozen_scorecard_bundle", "scorecard"},
        schema_version=SCHEMA_FROZEN_SCORECARD_BUNDLE,
        required_keys={"components", "feature_contract", "score_scaling"},
    ),
    EvidenceKind.APPLY_WOE_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"apply_woe_evidence", "report"},
        schema_version=SCHEMA_APPLY_WOE_EVIDENCE,
        required_keys={"roles", "policy"},
    ),
    EvidenceKind.APPLY_MODEL_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"apply_model_evidence", "report"},
        schema_version=SCHEMA_APPLY_MODEL_EVIDENCE,
        required_keys={"roles", "model_artifact_id"},
    ),
    EvidenceKind.VALIDATION_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "validation_evidence"},
        schema_version=SCHEMA_VALIDATION_EVIDENCE,
        required_keys={"roles", "stability", "gates"},
    ),
    EvidenceKind.REPORT_BUNDLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "report_bundle"},
        schema_version=SCHEMA_REPORT_BUNDLE,
        required_keys={"project_id", "run_id", "source", "summary"},
    ),
    EvidenceKind.RUN_SUMMARY: _Profile(
        expected_roles={"manifest"},
        expected_artifact_types={"run_summary"},
        schema_version=SCHEMA_RUN_SUMMARY,
        required_keys={"run_id", "steps"},
    ),
    EvidenceKind.TECHNICAL_MANIFEST_INDEX: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "technical_manifest_index"},
        schema_version=SCHEMA_TECHNICAL_MANIFEST_INDEX,
        required_keys={"manifests"},
    ),
    EvidenceKind.COMPARISON_ARTIFACT: _Profile(
        expected_roles={"comparison"},
        expected_artifact_types={"branch_comparison", "comparison_artifact"},
        schema_version=SCHEMA_COMPARISON_ARTIFACT,
        required_keys={"comparison_type", "baseline_branch_id", "challenger_branch_id"},
    ),
    EvidenceKind.FEATURE_SELECTION_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"feature_selection_evidence", "report"},
        schema_version=SCHEMA_FEATURE_SELECTION_EVIDENCE,
        required_keys={"selected", "rejected"},
    ),
    EvidenceKind.RESAMPLING_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "resampling_evidence"},
        schema_version=SCHEMA_RESAMPLING_EVIDENCE,
        required_keys={"original", "resampled"},
    ),
    EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"hyperparameter_tuning_evidence", "report"},
        schema_version=SCHEMA_HYPERPARAMETER_TUNING_EVIDENCE,
        required_keys={"best_score", "best_params"},
    ),
    EvidenceKind.EXPLAINABILITY_REPORT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"explainability_report", "report"},
        schema_version=SCHEMA_EXPLAINABILITY_REPORT,
        required_keys={"model_family", "limitations"},
    ),
    EvidenceKind.FAIRNESS_REPORT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"fairness_report", "report"},
        schema_version=SCHEMA_FAIRNESS_REPORT,
        required_keys={"roles", "parity_summary"},
    ),
    EvidenceKind.PROXY_RISK_REPORT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"proxy_risk_report", "report"},
        schema_version=SCHEMA_PROXY_RISK_REPORT,
        required_keys={"proxy_flags", "overall_risk"},
    ),
    EvidenceKind.CALIBRATION_REPORT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"calibration_report", "report"},
        schema_version=SCHEMA_CALIBRATION_REPORT,
        required_keys={"method", "calibration_error", "bins"},
    ),
    EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"coefficient_sign_diagnostics", "report"},
        schema_version=SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
        required_keys={"variables"},
    ),
    EvidenceKind.SEPARATION_DIAGNOSTICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "separation_diagnostics"},
        schema_version=SCHEMA_SEPARATION_DIAGNOSTICS,
        required_keys={"variables"},
    ),
    EvidenceKind.VIF_DIAGNOSTICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "vif_diagnostics"},
        schema_version=SCHEMA_VIF_DIAGNOSTICS,
        required_keys={"variables"},
    ),
    EvidenceKind.CALIBRATION_DIAGNOSTICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"calibration_diagnostics", "report"},
        schema_version=SCHEMA_CALIBRATION_DIAGNOSTICS,
        required_keys={"roles"},
    ),
    EvidenceKind.SCORE_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "scorecard_table"},
        schema_version=SCHEMA_SCORE_TABLE,
        required_keys={"rows"},
    ),
    EvidenceKind.SCORING_EXPORT_PYTHON: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "scoring_export_python"},
        schema_version=SCHEMA_SCORING_EXPORT_PYTHON,
        required_keys={"source", "function_name"},
    ),
    EvidenceKind.SCORING_EXPORT_SQL: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "scoring_export_sql"},
        schema_version=SCHEMA_SCORING_EXPORT_SQL,
        required_keys={"source", "dialect"},
    ),
}
