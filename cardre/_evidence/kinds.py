"""Evidence kind enum and error types."""

from __future__ import annotations

from enum import Enum

from cardre.domain.artifacts import ArtifactRef


class EvidenceKind(Enum):
    MODELLING_METADATA = "modelling_metadata"
    BIN_DEFINITION = "bin_definition"
    SAMPLE_DEFINITION = "sample_definition"
    SPLIT_SUMMARY = "split_summary"
    PROFILE_SUMMARY = "profile_summary"
    EXCLUSION_SUMMARY = "exclusion_summary"
    REJECT_POPULATION_CONFIG = "reject_population_config"
    REJECT_INFERENCE_RESULT = "reject_inference_result"
    SELECTION_DEFINITION = "selection_definition"
    WOE_TRANSFORM_EVIDENCE = "woe_transform_evidence"
    WOE_TABLE = "woe_table"
    WOE_IV_EVIDENCE = "woe_iv_evidence"
    VARIABLE_CLUSTERING = "variable_clustering"
    MODEL_ARTIFACT = "model_artifact"
    SCORE_SCALING = "score_scaling"
    VALIDATION_METRICS = "validation_metrics"
    CUTOFF_ANALYSIS = "cutoff_analysis"
    SCORED_DATASET = "scored_dataset"
    MANUAL_BINNING_OVERRIDES = "manual_binning_overrides"
    IV_TABLE = "iv_table"
    FROZEN_SCORECARD_BUNDLE = "frozen_scorecard_bundle"
    APPLY_WOE_EVIDENCE = "apply_woe_evidence"
    WOE_APPLICATION_EVIDENCE = "apply_woe_evidence"
    APPLY_MODEL_EVIDENCE = "apply_model_evidence"
    SCORE_APPLICATION_EVIDENCE = "apply_model_evidence"
    VALIDATION_EVIDENCE = "validation_evidence"
    REPORT_BUNDLE = "report_bundle"
    RUN_MANIFEST = "run_manifest"
    TECHNICAL_MANIFEST_INDEX = "technical_manifest_index"
    COMPARISON_ARTIFACT = "comparison_artifact"
    FEATURE_SELECTION_EVIDENCE = "feature_selection_evidence"
    RESAMPLING_EVIDENCE = "resampling_evidence"
    HYPERPARAMETER_TUNING_EVIDENCE = "hyperparameter_tuning_evidence"
    ENSEMBLE_MODEL_ARTIFACT = "ensemble_model_artifact"
    EXPLAINABILITY_REPORT = "explainability_report"
    FAIRNESS_REPORT = "fairness_report"
    PROXY_RISK_REPORT = "proxy_risk_report"
    CALIBRATION_REPORT = "calibration_report"


class EvidenceError(Exception):
    """Base for evidence-module errors."""


class EvidenceSchemaError(EvidenceError):
    """Evidence payload did not satisfy schema requirements."""


class LegacyEvidenceCompatibilityError(EvidenceSchemaError):
    """Legacy payload matched only via compatibility heuristics."""


class EvidenceNotFoundError(EvidenceError):
    """No artifact matched the requested evidence kind."""

    def __init__(
        self,
        kind: EvidenceKind,
        *,
        artifact_id: str | None = None,
        step_id: str | None = None,
        candidate_artifact_ids: list[str] | None = None,
        expected_schema: str | None = None,
        actual_schema: str | None = None,
        expected_role: str | None = None,
        expected_artifact_type: str | None = None,
        expected_media_type: str | None = None,
    ) -> None:
        self.kind = kind
        self.artifact_id = artifact_id
        self.step_id = step_id
        self.candidate_artifact_ids = candidate_artifact_ids or []
        self.expected_schema = expected_schema
        self.actual_schema = actual_schema
        self.expected_role = expected_role
        self.expected_artifact_type = expected_artifact_type
        self.expected_media_type = expected_media_type

        details = [f"kind={kind.value}"]
        if artifact_id:
            details.append(f"artifact_id={artifact_id}")
        if step_id:
            details.append(f"step_id={step_id}")
        if expected_schema:
            details.append(f"expected_schema={expected_schema}")
        if actual_schema:
            details.append(f"actual_schema={actual_schema}")
        if expected_role:
            details.append(f"expected_role={expected_role}")
        if expected_artifact_type:
            details.append(f"expected_artifact_type={expected_artifact_type}")
        if expected_media_type:
            details.append(f"expected_media_type={expected_media_type}")
        if self.candidate_artifact_ids:
            details.append(f"candidates={self.candidate_artifact_ids}")
        super().__init__("No artifact found for evidence " + ", ".join(details))


class AmbiguousEvidenceError(EvidenceError):
    """Multiple artifacts matched the requested evidence kind."""

    def __init__(
        self,
        kind: EvidenceKind,
        candidates: list[ArtifactRef],
        *,
        step_id: str | None = None,
        expected_schema: str | None = None,
        expected_role: str | None = None,
        expected_artifact_type: str | None = None,
        expected_media_type: str | None = None,
    ) -> None:
        self.kind = kind
        self.candidates = candidates
        self.candidate_artifact_ids = [c.artifact_id for c in candidates]
        self.step_id = step_id
        self.expected_schema = expected_schema
        self.expected_role = expected_role
        self.expected_artifact_type = expected_artifact_type
        self.expected_media_type = expected_media_type
        super().__init__(
            f"Multiple artifacts ({len(candidates)}) matched evidence kind "
            f"{kind.value}: {self.candidate_artifact_ids}"
        )


class EvidenceParseError(EvidenceSchemaError):
    """Artifact contents could not be parsed as the expected evidence kind."""

    def __init__(
        self,
        message: str,
        *,
        kind: EvidenceKind | None = None,
        artifact_id: str | None = None,
        step_id: str | None = None,
        expected_schema: str | None = None,
        actual_schema: str | None = None,
        expected_role: str | None = None,
        expected_artifact_type: str | None = None,
        expected_media_type: str | None = None,
    ) -> None:
        self.kind = kind
        self.artifact_id = artifact_id
        self.step_id = step_id
        self.expected_schema = expected_schema
        self.actual_schema = actual_schema
        self.expected_role = expected_role
        self.expected_artifact_type = expected_artifact_type
        self.expected_media_type = expected_media_type
        super().__init__(message)
