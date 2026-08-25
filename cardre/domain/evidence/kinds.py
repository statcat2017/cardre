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
    APPLY_MODEL_EVIDENCE = "apply_model_evidence"
    REPORT_BUNDLE = "report_bundle"
    RUN_SUMMARY = "run_summary"
    TECHNICAL_MANIFEST_INDEX = "technical_manifest_index"
    COMPARISON_ARTIFACT = "comparison_artifact"
    SCORE_TABLE = "scorecard_table"
    COEFFICIENT_SIGN_DIAGNOSTICS = "coefficient_sign_diagnostics"
    SEPARATION_DIAGNOSTICS = "separation_diagnostics"
    VIF_DIAGNOSTICS = "vif_diagnostics"
    CALIBRATION_DIAGNOSTICS = "calibration_diagnostics"
    SCORING_EXPORT_PYTHON = "scoring_export_python"
    SCORING_EXPORT_SQL = "scoring_export_sql"


class RoleKind(Enum):
    """Typed semantic role vocabulary for node contracts.

    A ``RoleKind`` is a stable, machine-checkable name for the set of
    ``EvidenceKind`` values that may legitimately flow through a role in the
    scorecard pipeline. Contracts declare ``RoleKind`` (or a concrete
    ``EvidenceKind``) in ``ArtifactRoleSpec.kinds``; the output-contract
    validator expands the role kind to its concrete evidence kinds, so a node
    emitting an out-of-set kind fails before publication. Loose string labels
    are no longer valid contract kinds.
    """

    DATASET = ("dataset", (
        EvidenceKind.MODELLING_METADATA,
        EvidenceKind.SPLIT_SUMMARY,
        EvidenceKind.WOE_TABLE,
        EvidenceKind.WOE_TRANSFORM_EVIDENCE,
        EvidenceKind.SCORED_DATASET,
    ))
    DEFINITION = ("definition", (
        EvidenceKind.MODELLING_METADATA,
        EvidenceKind.SAMPLE_DEFINITION,
        EvidenceKind.BIN_DEFINITION,
        EvidenceKind.SELECTION_DEFINITION,
    ))
    REPORT = ("report", (
        EvidenceKind.MODELLING_METADATA,
        EvidenceKind.SPLIT_SUMMARY,
        EvidenceKind.PROFILE_SUMMARY,
        EvidenceKind.EXCLUSION_SUMMARY,
        EvidenceKind.WOE_TABLE,
        EvidenceKind.WOE_IV_EVIDENCE,
        EvidenceKind.WOE_TRANSFORM_EVIDENCE,
        EvidenceKind.IV_TABLE,
        EvidenceKind.VARIABLE_CLUSTERING,
        EvidenceKind.MODEL_ARTIFACT,
        EvidenceKind.SCORE_SCALING,
        EvidenceKind.VALIDATION_METRICS,
        EvidenceKind.CUTOFF_ANALYSIS,
        EvidenceKind.SCORED_DATASET,
        EvidenceKind.FROZEN_SCORECARD_BUNDLE,
        EvidenceKind.APPLY_WOE_EVIDENCE,
        EvidenceKind.APPLY_MODEL_EVIDENCE,
        EvidenceKind.REPORT_BUNDLE,
        EvidenceKind.SCORE_TABLE,
        EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS,
        EvidenceKind.SEPARATION_DIAGNOSTICS,
        EvidenceKind.VIF_DIAGNOSTICS,
        EvidenceKind.CALIBRATION_DIAGNOSTICS,
        EvidenceKind.SCORING_EXPORT_PYTHON,
        EvidenceKind.SCORING_EXPORT_SQL,
    ))
    RUN_SUMMARY = ("run_summary", (EvidenceKind.RUN_SUMMARY,))
    TECHNICAL_MANIFEST_INDEX = (
        "technical_manifest_index",
        (EvidenceKind.TECHNICAL_MANIFEST_INDEX,),
    )

    def __init__(self, label: str, kinds: tuple[EvidenceKind, ...]) -> None:
        self.label = label
        self.kinds = kinds


def expand_role_kind(role_kind: RoleKind) -> tuple[EvidenceKind, ...]:
    """Return the concrete evidence kinds for a role-kind token."""
    return role_kind.kinds


class EvidenceError(Exception):
    """Base for evidence-module errors."""


class EvidenceSchemaError(EvidenceError):
    """Evidence payload did not satisfy schema requirements."""


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
