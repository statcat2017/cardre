"""Logistic scorecard model artifact contract for Cardre.

Provides the strict logistic scorecard artifact schema and typed
sub-contracts. There is no model-family dispatch or generic multi-family
shape; ``ModelArtifactV1`` is the one current persisted model payload.
"""

from cardre.modeling.schema import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    FeatureContract,
    ModelArtifactV1,
    TrainingMetadata,
)

__all__ = [
    "MODEL_ARTIFACT_SCHEMA_VERSION",
    "FeatureContract",
    "ModelArtifactV1",
    "TrainingMetadata",
]
