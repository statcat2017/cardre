"""Structured error categories for Cardre — domain kernel only.

Domain errors carry no I/O or registry dependencies.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    PLAN_VERSION_IMMUTABLE = "PLAN_VERSION_IMMUTABLE"
    STORE_VERSION_INCOMPATIBLE = "STORE_VERSION_INCOMPATIBLE"
    RUN_EXECUTION_FAILED = "RUN_EXECUTION_FAILED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    PLAN_VERSION_NOT_FOUND = "PLAN_VERSION_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    STEP_NOT_FOUND = "STEP_NOT_FOUND"
    REVIEW_NOT_FOUND = "REVIEW_NOT_FOUND"
    MISSING_PROJECT_ID = "MISSING_PROJECT_ID"
    MISSING_PROJECT_PATH = "MISSING_PROJECT_PATH"
    CONCURRENT_RUN = "CONCURRENT_RUN"
    STORE_ALREADY_EXISTS = "STORE_ALREADY_EXISTS"
    INVALID_PROJECT_PATH = "INVALID_PROJECT_PATH"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    PLAN_VERSION_NOT_COMMITTED = "PLAN_VERSION_NOT_COMMITTED"
    GRAPH_VALIDATION_ERROR = "GRAPH_VALIDATION_ERROR"
    RUN_NOT_RUNNING = "RUN_NOT_RUNNING"
    RUN_PLAN_VERSION_MISMATCH = "RUN_PLAN_VERSION_MISMATCH"
    MISSING_INPUT_ARTIFACT = "MISSING_INPUT_ARTIFACT"
    PARAMETER_VALIDATION_ERROR = "PARAMETER_VALIDATION_ERROR"
    ARTIFACT_READ_ERROR = "ARTIFACT_READ_ERROR"
    ARTIFACT_WRITE_ERROR = "ARTIFACT_WRITE_ERROR"
    NODE_VERSION_MISMATCH = "NODE_VERSION_MISMATCH"
    RUN_LIFECYCLE_ERROR = "RUN_LIFECYCLE_ERROR"
    PLAN_VERSION_ALREADY_COMMITTED = "PLAN_VERSION_ALREADY_COMMITTED"
    RUN_CANCELLED = "RUN_CANCELLED"
    OUTPUT_CONTRACT_VIOLATION = "OUTPUT_CONTRACT_VIOLATION"
    INPUT_CONTRACT_VIOLATION = "INPUT_CONTRACT_VIOLATION"
    ARTIFACT_STAGING_FAILED = "ARTIFACT_STAGING_FAILED"
    ARTIFACT_PUBLISH_FAILED = "ARTIFACT_PUBLISH_FAILED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

    EVIDENCE_VALIDATION_ERROR = "EVIDENCE_VALIDATION_ERROR"

    # --- Reporting / export ---
    REPORT_BLOCKED = "REPORT_BLOCKED"
    CANONICAL_MANIFEST_MISSING = "CANONICAL_MANIFEST_MISSING"
    EXPORT_RUN_NOT_FOUND = "EXPORT_RUN_NOT_FOUND"
    REPORT_DATA_INVALID = "REPORT_DATA_INVALID"

    # --- Run manifest (internal: raised during finalization, not HTTP) ---
    MANIFEST_STEP_MISSING = "MANIFEST_STEP_MISSING"
    MANIFEST_PLAN_MISSING = "MANIFEST_PLAN_MISSING"

    # --- Infrastructure ---
    REGISTRY_CORRUPTED = "REGISTRY_CORRUPTED"
    RUN_SCOPE_INVALID = "RUN_SCOPE_INVALID"

    # --- Internal execution (class-level defaults; surface via run diagnostics) ---
    CARDRE_ERROR = "CARDRE_ERROR"
    SCORECARD_DEFINITION_ERROR = "SCORECARD_DEFINITION_ERROR"
    NODE_FAILED_WITH_ARTIFACTS = "NODE_FAILED_WITH_ARTIFACTS"
    NODE_ROLE_ACCESS_VIOLATION = "NODE_ROLE_ACCESS_VIOLATION"
    RUN_LEASE_LOST = "RUN_LEASE_LOST"
    RUN_HEARTBEAT_FAILED = "RUN_HEARTBEAT_FAILED"


# Internal-only codes that never cross the HTTP boundary. They surface via run
# diagnostics or process-local exceptions, never as API error envelopes, so
# they are excluded from the public TypeScript union. Kept in one canonical set
# shared by scripts/generate-error-codes.py and tests/test_error_code_sync.py.
INTERNAL_ERROR_CODES: frozenset[ErrorCode] = frozenset({
    ErrorCode.CARDRE_ERROR,
    ErrorCode.SCORECARD_DEFINITION_ERROR,
    ErrorCode.NODE_FAILED_WITH_ARTIFACTS,
    ErrorCode.NODE_ROLE_ACCESS_VIOLATION,
    ErrorCode.RUN_LEASE_LOST,
    ErrorCode.RUN_HEARTBEAT_FAILED,
    ErrorCode.RUN_LIFECYCLE_ERROR,
    ErrorCode.MANIFEST_STEP_MISSING,
    ErrorCode.MANIFEST_PLAN_MISSING,
    ErrorCode.INPUT_CONTRACT_VIOLATION,
    ErrorCode.OUTPUT_CONTRACT_VIOLATION,
    ErrorCode.ARTIFACT_STAGING_FAILED,
    ErrorCode.ARTIFACT_PUBLISH_FAILED,
    ErrorCode.RUN_EXECUTION_FAILED,
    ErrorCode.RUN_CANCELLED,
    ErrorCode.REPORT_DATA_INVALID,
})


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

    code: ErrorCode = ErrorCode.CARDRE_ERROR
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | str | None = None,
        context: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = ErrorCode(code)
        if status_code is not None:
            self.status_code = status_code
        self.message = message or self.code
        self.context = context or {}
        self.diagnostics = diagnostics or []


class NodeFailedWithArtifacts(CardreError):
    """A node failed but produced artifacts that should be linked to the run step.

    The ``artifacts`` list contains the artifacts the node wrote before
    encountering the failure condition.
    """

    code: ErrorCode = ErrorCode.NODE_FAILED_WITH_ARTIFACTS
    status_code: int = 500

    def __init__(
        self,
        message: str,
        artifacts: list[Any],
        *,
        code: ErrorCode | str | None = None,
    ) -> None:
        self.artifacts = artifacts
        super().__init__(message, code=code)


class GraphValidationError(CardreError):
    """Raised when a plan graph fails validation."""
    code = ErrorCode.GRAPH_VALIDATION_ERROR
    status_code = 500


class PlanVersionNotCommittedError(CardreError):
    """Raised when a draft plan version is submitted for execution."""
    code = ErrorCode.PLAN_VERSION_NOT_COMMITTED
    status_code = 409


class ConcurrentRunError(CardreError):
    """Raised when a run is already in progress for a plan version."""
    code = ErrorCode.CONCURRENT_RUN
    status_code = 409


class SchemaVersionError(CardreError):
    """Raised when the store schema identity does not match the app."""
    code = ErrorCode.STORE_VERSION_INCOMPATIBLE
    status_code = 409


class RunLifecycleError(CardreError):
    code = ErrorCode.RUN_LIFECYCLE_ERROR
    status_code = 500


class RunNotFoundError(CardreError):
    """Raised when a run record does not exist."""
    code = ErrorCode.RUN_NOT_FOUND
    status_code = 404


class RunNotRunningError(CardreError):
    """Raised when a run is not in the 'running' state."""
    code = ErrorCode.RUN_NOT_RUNNING
    status_code = 409


class LeaseLost(CardreError):
    """Raised when a worker's lease is no longer valid (stale recovery,
    cancellation, or a replacement worker took over)."""

    code = ErrorCode.RUN_LEASE_LOST
    status_code = 409

    def __init__(self, run_id: str, reason: str) -> None:
        super().__init__(
            f"Run {run_id!r} lease lost: {reason}",
            code=self.code,
            context={"run_id": run_id, "reason": reason},
            status_code=self.status_code,
        )


class RunPlanVersionMismatchError(CardreError):
    """Raised when a run's plan version does not match the expected one."""
    code = ErrorCode.RUN_PLAN_VERSION_MISMATCH
    status_code = 409


class MissingInputArtifactError(CardreError):
    """Raised when a parent step has no output artifacts for a child to consume."""
    code = ErrorCode.MISSING_INPUT_ARTIFACT
    status_code = 400


class NodeRoleAccessViolation(CardreError):
    """Raised when a node receives an artifact role outside its contract."""
    code = ErrorCode.NODE_ROLE_ACCESS_VIOLATION
    status_code = 400


class ParameterValidationError(CardreError):
    """Raised when node parameter validation fails."""
    code = ErrorCode.PARAMETER_VALIDATION_ERROR
    status_code = 400


class ScorecardDefinitionError(CardreError):
    """Raised when a scorecard bin definition requires a feature that the
    model Artifact does not provide a coefficient for.

    This is a feature-contract violation between the bin definition and the
    model Artifact (an unused selection or a naming mismatch), distinct from a
    malformed or unreadable model Artifact.
    """

    code = ErrorCode.SCORECARD_DEFINITION_ERROR
    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message, code=self.code)


class ArtifactReadError(CardreError):
    """Raised when an artifact file cannot be read (missing or hash mismatch)."""
    code = ErrorCode.ARTIFACT_READ_ERROR
    status_code = 400


class ArtifactWriteError(CardreError):
    """Raised when an artifact file cannot be written."""
    code = ErrorCode.ARTIFACT_WRITE_ERROR
    status_code = 500


class NodeVersionMismatchError(CardreError):
    """Raised when a persisted step's node_version differs from the running node's version."""
    code = ErrorCode.NODE_VERSION_MISMATCH
    status_code = 409

    def __init__(self, step_id: str, node_type: str, persisted: str, current: str) -> None:
        self.step_id = step_id
        self.node_type = node_type
        self.persisted_version = persisted
        self.current_version = current
        message = (
            f"Step {step_id!r} ({node_type!r}) recorded node_version {persisted!r} "
            f"but the current implementation is version {current!r}."
        )
        super().__init__(
            message,
            context={
                "step_id": step_id,
                "node_type": node_type,
                "persisted_version": persisted,
                "current_version": current,
            },
        )

    @classmethod
    def from_mismatches(cls, mismatches: list[dict[str, str]]) -> NodeVersionMismatchError:
        """Build an error covering several mismatched steps (pre-execution validation)."""
        details = [
            f"{m['step_id']!r} ({m['node_type']!r}): {m['persisted_version']!r} != {m['current_version']!r}"
            for m in mismatches
        ]
        first = mismatches[0]
        err = cls(
            step_id=first["step_id"],
            node_type=first["node_type"],
            persisted=first["persisted_version"],
            current=first["current_version"],
        )
        aggregate = (
            f"{len(mismatches)} step(s) record a node_version that does not match "
            f"the current implementation: {'; '.join(details)}."
        )
        err.args = (aggregate,)
        err.message = aggregate
        err.context["mismatches"] = list(mismatches)
        return err


__all__ = [
    "ArtifactReadError",
    "ArtifactWriteError",
    "CardreError",
    "ConcurrentRunError",
    "Diagnostic",
    "ErrorCode",
    "GraphValidationError",
    "INTERNAL_ERROR_CODES",
    "MissingInputArtifactError",
    "NodeRoleAccessViolation",
    "NodeVersionMismatchError",
    "ParameterValidationError",
    "PlanVersionNotCommittedError",
    "RunLifecycleError",
    "RunNotFoundError",
    "RunNotRunningError",
    "RunPlanVersionMismatchError",
    "SchemaVersionError",
    "ScorecardDefinitionError",
]
