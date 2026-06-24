"""Structured error categories for Cardre execution errors."""


class CardreError(Exception):
    pass


class GraphValidationError(CardreError):
    pass


class MissingInputArtifactError(CardreError):
    pass


class ParameterValidationError(CardreError):
    pass


class ArtifactReadError(CardreError):
    pass


class ArtifactWriteError(CardreError):
    pass


class NodeExecutionError(CardreError):
    pass


class ContractViolationError(CardreError):
    pass


class NodeNotAvailableForLaunch(CardreError):
    """Raised when a deferred node (not in the launch tier) is instantiated."""
    pass


class GovernanceNotEnabled(CardreError):
    """Raised when a governance-gated feature is accessed without CARDRE_GOVERNANCE=1."""
    pass


class ConcurrentRunError(CardreError):
    """Raised when a run is requested but one is already in progress for the same scope."""
    pass


class SchemaVersionError(CardreError):
    """Raised when the store schema version is newer than the app supports."""
    pass


__all__ = [
    "CardreError",
    "GraphValidationError",
    "MissingInputArtifactError",
    "ParameterValidationError",
    "ArtifactReadError",
    "ArtifactWriteError",
    "NodeExecutionError",
    "ContractViolationError",
    "NodeNotAvailableForLaunch",
    "GovernanceNotEnabled",
    "ConcurrentRunError",
    "SchemaVersionError",
]
