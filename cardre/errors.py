"""V1 compatibility shim — re-exports from cardre.domain.errors.

Phase 5: existing node code imports ``CardreError``, ``Diagnostic``
from ``cardre.errors``. These now live in ``cardre.domain.errors``.

Result/Ok/Degraded were v1-specific and have been inlined in their
only consumer (cardre.reporting.collector).
"""

from __future__ import annotations

from cardre.domain.errors import (
    ArtifactReadError,
    ArtifactWriteError,
    BranchValidationError,
    CardreError,
    ConcurrentRunError,
    Diagnostic,
    GovernanceNotEnabled,
    GraphValidationError,
    MissingInputArtifactError,
    NodeNotAvailableForLaunch,
    OptionalDependencyNotInstalled,
    ParameterValidationError,
    PlanContainsUnavailableNodesError,
    RunLifecycleError,
    SchemaVersionError,
)

__all__ = [
    "ArtifactReadError",
    "ArtifactWriteError",
    "BranchValidationError",
    "CardreError",
    "ConcurrentRunError",
    "Diagnostic",
    "GovernanceNotEnabled",
    "GraphValidationError",
    "MissingInputArtifactError",
    "NodeNotAvailableForLaunch",
    "OptionalDependencyNotInstalled",
    "ParameterValidationError",
    "PlanContainsUnavailableNodesError",
    "RunLifecycleError",
    "SchemaVersionError",
]
