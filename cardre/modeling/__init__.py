"""Generic model artifact contract for Cardre.

Provides the model artifact schema and typed sub-contracts so that
logistic, decision-tree, random-forest, GBDT, and later optional boosting
models share a common artifact shape.
"""

from cardre.modeling.schema import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    FeatureContract,
    InterpretabilityMetadata,
    ModelArtifactV1,
    PredictionContract,
    TrainingMetadata,
)

__all__ = [
    "MODEL_ARTIFACT_SCHEMA_VERSION",
    "FeatureContract",
    "InterpretabilityMetadata",
    "ModelArtifactV1",
    "PredictionContract",
    "TrainingMetadata",
]
