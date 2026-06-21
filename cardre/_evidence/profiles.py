"""Evidence matching profiles — maps EvidenceKind to expected artifact shape."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.schemas import (
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MANUAL_BINNING_OVERRIDES,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_REJECT_INFERENCE_RESULT,
    SCHEMA_REJECT_POPULATION_CONFIG,
    SCHEMA_SAMPLE_DEFINITION,
    SCHEMA_SCORE_APPLICATION_EVIDENCE,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_VALIDATION_EVIDENCE,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
    SCHEMA_WOE_APPLICATION_EVIDENCE,
    SCHEMA_WOE_IV_EVIDENCE,
    SCHEMA_WOE_TABLE,
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
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_MODELLING_METADATA,
        required_keys={"target_column", "good_values", "bad_values"},
    ),
    EvidenceKind.SAMPLE_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_SAMPLE_DEFINITION,
        required_keys={"sample_method"},
    ),
    EvidenceKind.REJECT_POPULATION_CONFIG: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_REJECT_POPULATION_CONFIG,
        required_keys={"total_rows", "rejection_source"},
    ),
    EvidenceKind.REJECT_INFERENCE_RESULT: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_REJECT_INFERENCE_RESULT,
        required_keys={"method", "missingness_assumption"},
    ),
    EvidenceKind.BIN_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_BIN_DEFINITION,
        required_keys={"variables"},
        exclude_key="selected",
    ),
    EvidenceKind.SELECTION_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_SELECTION_DEFINITION,
        required_keys={"selected"},
    ),
    EvidenceKind.WOE_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "dataset"},
        schema_version=SCHEMA_WOE_TABLE,
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"variable", "bin_id", "woe"},
    ),
    EvidenceKind.IV_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "dataset"},
        schema_version="",
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"iv", "variable"},
    ),
    EvidenceKind.WOE_IV_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_WOE_IV_EVIDENCE,
        required_keys={"variables"},
    ),
    EvidenceKind.VARIABLE_CLUSTERING: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
        required_keys={"method", "clusters"},
    ),
    EvidenceKind.SCORED_DATASET: _Profile(
        expected_roles={"train", "test", "oot"},
        expected_artifact_types={"dataset"},
        schema_version="",
        expected_media_types={"application/vnd.apache.parquet"},
    ),
    EvidenceKind.MODEL_ARTIFACT: _Profile(
        expected_roles={"model", "report", "definition"},
        expected_artifact_types={"model", "definition", "report"},
        schema_version=SCHEMA_MODEL_ARTIFACT,
        required_keys={"model_family"},
    ),
    EvidenceKind.SCORE_SCALING: _Profile(
        expected_roles={"scorecard", "report"},
        expected_artifact_types={"scorecard", "report"},
        schema_version=SCHEMA_SCORE_SCALING,
        required_keys={"factor", "offset"},
    ),
    EvidenceKind.VALIDATION_METRICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_VALIDATION_METRICS,
        required_keys={"metrics"},
    ),
    EvidenceKind.CUTOFF_ANALYSIS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_CUTOFF_ANALYSIS,
        required_keys={"cutoff_tables"},
    ),
    EvidenceKind.MANUAL_BINNING_OVERRIDES: _Profile(
        expected_roles={"definition", "report"},
        expected_artifact_types={"definition", "report"},
        schema_version=SCHEMA_MANUAL_BINNING_OVERRIDES,
    ),
    EvidenceKind.FROZEN_SCORECARD_BUNDLE: _Profile(
        expected_roles={"scorecard"},
        expected_artifact_types={"scorecard"},
        schema_version=SCHEMA_FROZEN_SCORECARD_BUNDLE,
        required_keys={"components", "feature_contract", "score_scaling"},
    ),
    EvidenceKind.WOE_APPLICATION_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_WOE_APPLICATION_EVIDENCE,
        required_keys={"roles", "policy"},
    ),
    EvidenceKind.SCORE_APPLICATION_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_SCORE_APPLICATION_EVIDENCE,
        required_keys={"roles", "model_artifact_id"},
    ),
    EvidenceKind.VALIDATION_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_VALIDATION_EVIDENCE,
        required_keys={"roles", "stability", "gates"},
    ),
}
