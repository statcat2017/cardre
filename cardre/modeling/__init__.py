"""Generic model artifact contract for Cardre.

Provides schema definitions, validation helpers, and legacy-compatibility
resolvers so that logistic, decision-tree, random-forest, GBDT, and later
optional boosting models share a common artifact shape.
"""

from cardre.modeling.schema import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    FeatureContract,
    InterpretabilityMetadata,
    ModelArtifactV1,
    PredictionContract,
    TrainingMetadata,
    estimate_probability_column_index,
    validate_model_artifact,
)
from cardre.modeling.serialization import (
    read_estimator_artifact,
    write_estimator_artifact,
)

__all__ = [
    "MODEL_ARTIFACT_SCHEMA_VERSION",
    "FeatureContract",
    "InterpretabilityMetadata",
    "ModelArtifactV1",
    "PredictionContract",
    "TrainingMetadata",
    "estimate_probability_column_index",
    "read_estimator_artifact",
    "validate_model_artifact",
    "write_estimator_artifact",
]
