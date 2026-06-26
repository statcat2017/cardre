"""Structured error categories for Cardre execution errors."""

from __future__ import annotations

import dataclasses
from typing import Any, Generic, TypeVar, Union

T = TypeVar("T")


@dataclasses.dataclass
class Diagnostic:
    code: str
    message: str
    source: str | None = None
    exception_type: str | None = None
    severity: str = "error"
    context: dict[str, Any] = dataclasses.field(default_factory=dict)


class CardreError(Exception):
    """Base for all typed Cardre errors.

    Subclasses set class-level defaults for code, status_code, severity,
    and recoverable. Callers pass message, context, recoverable, severity,
    and diagnostics at construction. A single FastAPI handler serialises
    any subclass via to_envelope().
    """
    code: str = "CARDRE_ERROR"
    status_code: int = 500
    severity: str = "error"
    recoverable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        context: dict[str, Any] | None = None,
        recoverable: bool | None = None,
        severity: str | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code
        self.message = message or self.code
        self.context = context or {}
        if recoverable is not None:
            self.recoverable = recoverable
        if severity is not None:
            self.severity = severity
        self.diagnostics = diagnostics or []

    def to_envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "severity": self.severity,
            "context": self.context,
            "diagnostics": [dataclasses.asdict(d) for d in self.diagnostics],
        }


class GraphValidationError(CardreError):
    code = "GRAPH_VALIDATION_ERROR"
    status_code = 500


class MissingInputArtifactError(CardreError):
    code = "MISSING_INPUT_ARTIFACT"
    status_code = 500


class ParameterValidationError(CardreError):
    code = "PARAMETER_VALIDATION_ERROR"
    status_code = 400


class ArtifactReadError(CardreError):
    code = "ARTIFACT_READ_ERROR"
    status_code = 500


class ArtifactWriteError(CardreError):
    code = "ARTIFACT_WRITE_ERROR"
    status_code = 500


class NodeExecutionError(CardreError):
    code = "NODE_EXECUTION_ERROR"
    status_code = 500


class ContractViolationError(CardreError):
    code = "CONTRACT_VIOLATION_ERROR"
    status_code = 500


class NodeNotAvailableForLaunch(CardreError):
    """Raised when a deferred node (not in the launch tier) is instantiated."""
    code = "NODE_NOT_AVAILABLE_FOR_LAUNCH"
    status_code = 400


class GovernanceNotEnabled(CardreError):
    """Raised when a governance-gated feature is accessed without CARDRE_GOVERNANCE=1."""
    code = "GOVERNANCE_NOT_ENABLED"
    status_code = 403


class ConcurrentRunError(CardreError):
    """Raised when a run is requested but one is already in progress for the same scope."""
    code = "CONCURRENT_RUN"
    status_code = 409


class SchemaVersionError(CardreError):
    """Raised when the store schema version is newer than the app supports."""
    code = "SCHEMA_VERSION_ERROR"
    status_code = 500


class RunLifecycleError(CardreError):
    code = "RUN_LIFECYCLE_ERROR"
    status_code = 500


class BranchValidationError(CardreError):
    code = "BRANCH_VALIDATION_ERROR"
    status_code = 400

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        super().__init__(message or code, context=context)


class BranchEvidenceError(CardreError):
    code = "BRANCH_EVIDENCE_ERROR"
    status_code = 409

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message or code, context=context)


# --- Result types for the fail-hard-vs-degrade pattern ---


@dataclasses.dataclass
class Ok(Generic[T]):
    value: T
    diagnostics: list[Diagnostic] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Degraded(Generic[T]):
    value: T
    diagnostics: list[Diagnostic]


@dataclasses.dataclass
class Fail:
    diagnostics: list[Diagnostic]


Result = Union[Ok[T], Degraded[T], Fail]


def is_ok(r: Result) -> bool:
    return isinstance(r, Ok)


def is_degraded(r: Result) -> bool:
    return isinstance(r, Degraded)


def is_fail(r: Result) -> bool:
    return isinstance(r, Fail)


def unwrap_or_raise(r: Result[T]) -> T:
    """Fail-hard policy: raise the first diagnostic as a CardreError."""
    if isinstance(r, Ok):
        return r.value
    if isinstance(r, Degraded):
        return r.value
    d = r.diagnostics[0]
    raise CardreError(
        d.message,
        code=d.code,
        context=d.context,
        diagnostics=r.diagnostics,
    )


def unwrap_or_degrade(r: Result[T], default: T, diagnostic: Diagnostic | None = None) -> T:
    """Degrade-gracefully policy: return default + diagnostic(s)."""
    if isinstance(r, Ok):
        return r.value
    if isinstance(r, Degraded):
        return r.value
    return default


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
    "RunLifecycleError",
    "BranchValidationError",
    "BranchEvidenceError",
    "Diagnostic",
    "Ok",
    "Degraded",
    "Fail",
    "Result",
    "is_ok",
    "is_degraded",
    "is_fail",
    "unwrap_or_raise",
    "unwrap_or_degrade",
]
