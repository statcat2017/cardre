"""Evidence kind enum and error types."""

from __future__ import annotations

from enum import Enum
from typing import Any

from cardre.audit import ArtifactRef


class EvidenceKind(Enum):
    MODELLING_METADATA = "modelling_metadata"
    BIN_DEFINITION = "bin_definition"
    SAMPLE_DEFINITION = "sample_definition"
    REJECT_POPULATION_CONFIG = "reject_population_config"
    REJECT_INFERENCE_RESULT = "reject_inference_result"
    SELECTION_DEFINITION = "selection_definition"
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
    WOE_APPLICATION_EVIDENCE = "woe_application_evidence"
    SCORE_APPLICATION_EVIDENCE = "score_application_evidence"
    VALIDATION_EVIDENCE = "validation_evidence"


class EvidenceError(Exception):
    """Base for evidence-module errors."""


class EvidenceNotFoundError(EvidenceError):
    """No artifact matched the requested evidence kind."""

    def __init__(self, kind: EvidenceKind) -> None:
        self.kind = kind
        super().__init__(f"No artifact found for evidence kind: {kind.value}")


class AmbiguousEvidenceError(EvidenceError):
    """Multiple artifacts matched the requested evidence kind."""

    def __init__(self, kind: EvidenceKind, candidates: list[ArtifactRef]) -> None:
        self.kind = kind
        self.candidates = candidates
        super().__init__(
            f"Multiple artifacts ({len(candidates)}) matched evidence kind "
            f"{kind.value}"
        )


class EvidenceParseError(EvidenceError):
    """Artifact contents could not be parsed as the expected evidence kind."""
