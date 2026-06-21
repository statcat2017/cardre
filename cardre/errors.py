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


class CancellationError(CardreError):
    pass


class NodeNotAvailableForLaunch(CardreError):
    """Raised when a deferred node (not in the launch tier) is instantiated."""
    pass


class GovernanceNotEnabled(CardreError):
    """Raised when a governance-gated feature is accessed without CARDRE_GOVERNANCE=1."""
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
    "CancellationError",
    "NodeNotAvailableForLaunch",
    "GovernanceNotEnabled",
]
