"""Structured error categories for Cardre — domain kernel only.

Domain errors carry no I/O or registry dependencies.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class Diagnostic:
    """A typed diagnostic message (error, warning, info)."""
    code: str
    message: str
    source: str | None = None
    exception_type: str | None = None
    severity: str = "error"
    context: dict[str, Any] = dataclasses.field(default_factory=dict)


class CardreError(Exception):
    """Base for all typed Cardre errors.

    Subclasses set class-level defaults for code and status_code.
    """

    code: str = "CARDRE_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        context: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code
        self.message = message or self.code
        self.context = context or {}
        self.diagnostics = diagnostics or []


class GovernanceNotEnabled(CardreError):
    """Raised when a governance-gated feature is accessed without CARDRE_GOVERNANCE=1."""
    code = "GOVERNANCE_NOT_ENABLED"
    status_code = 403


class GraphValidationError(CardreError):
    """Raised when a plan graph fails validation."""
    code = "GRAPH_VALIDATION_ERROR"
    status_code = 500


class PlanContainsUnavailableNodesError(CardreError):
    """Raised before a run starts when a plan contains unavailable nodes."""
    code = "PLAN_CONTAINS_UNAVAILABLE_NODES"
    status_code = 400

    def __init__(self, issues: list[dict]) -> None:
        self.issues = issues
        step_ids = ", ".join(i["step_id"] for i in issues)
        message = (
            f"Plan contains {len(issues)} unavailable node(s): {step_ids}. "
            "See context for details."
        )
        super().__init__(message, context={"issues": issues})


class PlanVersionNotCommittedError(CardreError):
    """Raised when a draft plan version is submitted for execution."""
    code = "PLAN_VERSION_NOT_COMMITTED"
    status_code = 409


class ConcurrentRunError(CardreError):
    """Raised when a run is already in progress for a plan version."""
    code = "CONCURRENT_RUN"
    status_code = 409


class SchemaVersionError(CardreError):
    """Raised when the store schema identity does not match the app."""
    code = "STORE_VERSION_INCOMPATIBLE"
    status_code = 409


class RunLifecycleError(CardreError):
    code = "RUN_LIFECYCLE_ERROR"
    status_code = 500


class MissingInputArtifactError(CardreError):
    """Raised when a parent step has no output artifacts for a child to consume."""
    code = "MISSING_INPUT_ARTIFACT"
    status_code = 400


class ParameterValidationError(CardreError):
    """Raised when node parameter validation fails."""
    code = "PARAMETER_VALIDATION_ERROR"
    status_code = 400


class ArtifactReadError(CardreError):
    """Raised when an artifact file cannot be read (missing or hash mismatch)."""
    code = "ARTIFACT_READ_ERROR"
    status_code = 400


class ArtifactWriteError(CardreError):
    """Raised when an artifact file cannot be written."""
    code = "ARTIFACT_WRITE_ERROR"
    status_code = 500


class NodeNotAvailableForLaunch(CardreError):
    """Raised when a deferred node is instantiated in launch mode."""
    code = "NODE_NOT_AVAILABLE_FOR_LAUNCH"
    status_code = 400


class BranchValidationError(CardreError):
    """Raised when branch creation or management validation fails."""
    code = "BRANCH_VALIDATION_ERROR"
    status_code = 400


class OptionalDependencyNotInstalled(CardreError):
    """Raised when a node's optional dependency group is not installed."""
    code = "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
    status_code = 400

    def __init__(self, node_type: str, missing_groups: list[str]) -> None:
        self.node_type = node_type
        self.missing_groups = list(missing_groups)
        hint = f"pip install -e '.[{','.join(missing_groups)}]'"
        message = (
            f"Node {node_type!r} requires optional dependency group(s) "
            f"{missing_groups} which are not installed. Install with: {hint}"
        )
        super().__init__(message, context={"node_type": node_type, "missing_groups": list(missing_groups)})


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
    "PlanVersionNotCommittedError",
    "PlanContainsUnavailableNodesError",
    "RunLifecycleError",
    "SchemaVersionError",
]
