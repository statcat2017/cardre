"""Structured error categories for Cardre — domain kernel only.

Domain errors carry no I/O or registry dependencies.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    GOVERNANCE_DISABLED = "GOVERNANCE_DISABLED"
    PLAN_VERSION_IMMUTABLE = "PLAN_VERSION_IMMUTABLE"
    STORE_VERSION_INCOMPATIBLE = "STORE_VERSION_INCOMPATIBLE"
    RUN_EXECUTION_FAILED = "RUN_EXECUTION_FAILED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    PLAN_VERSION_NOT_FOUND = "PLAN_VERSION_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    STEP_NOT_FOUND = "STEP_NOT_FOUND"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    COMPARISON_NOT_FOUND = "COMPARISON_NOT_FOUND"
    REVIEW_NOT_FOUND = "REVIEW_NOT_FOUND"
    MISSING_PROJECT_ID = "MISSING_PROJECT_ID"
    MISSING_PROJECT_PATH = "MISSING_PROJECT_PATH"
    CONCURRENT_RUN = "CONCURRENT_RUN"
    STORE_ALREADY_EXISTS = "STORE_ALREADY_EXISTS"
    INVALID_PROJECT_PATH = "INVALID_PROJECT_PATH"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    PLAN_VERSION_NOT_COMMITTED = "PLAN_VERSION_NOT_COMMITTED"
    GOVERNANCE_NOT_ENABLED = "GOVERNANCE_NOT_ENABLED"
    GRAPH_VALIDATION_ERROR = "GRAPH_VALIDATION_ERROR"
    PLAN_CONTAINS_UNAVAILABLE_NODES = "PLAN_CONTAINS_UNAVAILABLE_NODES"
    RUN_NOT_RUNNING = "RUN_NOT_RUNNING"
    RUN_PLAN_VERSION_MISMATCH = "RUN_PLAN_VERSION_MISMATCH"
    MISSING_INPUT_ARTIFACT = "MISSING_INPUT_ARTIFACT"
    PARAMETER_VALIDATION_ERROR = "PARAMETER_VALIDATION_ERROR"
    ARTIFACT_READ_ERROR = "ARTIFACT_READ_ERROR"
    ARTIFACT_WRITE_ERROR = "ARTIFACT_WRITE_ERROR"
    NODE_NOT_AVAILABLE_FOR_LAUNCH = "NODE_NOT_AVAILABLE_FOR_LAUNCH"
    NODE_VERSION_MISMATCH = "NODE_VERSION_MISMATCH"
    RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH = "RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH"
    BRANCH_VALIDATION_ERROR = "BRANCH_VALIDATION_ERROR"
    OPTIONAL_DEPENDENCY_NOT_INSTALLED = "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
    RUN_LIFECYCLE_ERROR = "RUN_LIFECYCLE_ERROR"
    PLAN_VERSION_ALREADY_COMMITTED = "PLAN_VERSION_ALREADY_COMMITTED"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    RUN_CANCELLED = "RUN_CANCELLED"
    OUTPUT_CONTRACT_VIOLATION = "OUTPUT_CONTRACT_VIOLATION"
    INPUT_CONTRACT_VIOLATION = "INPUT_CONTRACT_VIOLATION"
    ARTIFACT_STAGING_FAILED = "ARTIFACT_STAGING_FAILED"
    ARTIFACT_PUBLISH_FAILED = "ARTIFACT_PUBLISH_FAILED"

    # --- Branch / governance validation (HTTP 400 family) ---
    SEGMENT_FILTER_RULES_REQUIRED = "SEGMENT_FILTER_RULES_REQUIRED"
    SEGMENT_FILTER_REQUIRED = "SEGMENT_FILTER_REQUIRED"
    SEGMENT_FILTER_INVALID = "SEGMENT_FILTER_INVALID"
    SEGMENT_FILTER_UNSUPPORTED_OPERATOR = "SEGMENT_FILTER_UNSUPPORTED_OPERATOR"
    SEGMENT_FILTER_REASON_REQUIRED = "SEGMENT_FILTER_REASON_REQUIRED"
    SEGMENT_FILTER_VALUE_REQUIRED = "SEGMENT_FILTER_VALUE_REQUIRED"
    BRANCH_NAME_REQUIRED = "BRANCH_NAME_REQUIRED"
    BRANCH_REASON_REQUIRED = "BRANCH_REASON_REQUIRED"
    BRANCH_TYPE_MISMATCH = "BRANCH_TYPE_MISMATCH"
    BRANCH_POINT_NOT_ALLOWED = "BRANCH_POINT_NOT_ALLOWED"
    BRANCH_POINT_NOT_IN_PLAN = "BRANCH_POINT_NOT_IN_PLAN"
    BRANCH_SCOPE_MISMATCH = "BRANCH_SCOPE_MISMATCH"
    BRANCH_NOT_ACTIVE = "BRANCH_NOT_ACTIVE"
    BRANCH_PLAN_VERSION_MISMATCH = "BRANCH_PLAN_VERSION_MISMATCH"

    REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF = "REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF"
    REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD = "REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD"
    EVIDENCE_VALIDATION_ERROR = "EVIDENCE_VALIDATION_ERROR"
    STALE_HEAD_VERSION = "STALE_HEAD_VERSION"
    STALE_BASE_VERSION = "STALE_BASE_VERSION"

    # --- Champion / comparison ---
    CHAMPION_REASON_REQUIRED = "CHAMPION_REASON_REQUIRED"
    CHAMPION_BRANCH_MISMATCH = "CHAMPION_BRANCH_MISMATCH"
    COMPARISON_SNAPSHOT_NOT_FOUND = "COMPARISON_SNAPSHOT_NOT_FOUND"
    COMPARISON_NOT_READY = "COMPARISON_NOT_READY"
    BRANCH_NOT_IN_COMPARISON = "BRANCH_NOT_IN_COMPARISON"

    # --- Reporting / export ---
    REPORT_BLOCKED = "REPORT_BLOCKED"
    CANONICAL_MANIFEST_MISSING = "CANONICAL_MANIFEST_MISSING"
    EXPORT_RUN_NOT_FOUND = "EXPORT_RUN_NOT_FOUND"

    # --- Run manifest (internal: raised during finalization, not HTTP) ---
    MANIFEST_STEP_MISSING = "MANIFEST_STEP_MISSING"
    MANIFEST_PLAN_MISSING = "MANIFEST_PLAN_MISSING"

    # --- Infrastructure ---
    REGISTRY_CORRUPTED = "REGISTRY_CORRUPTED"
    RUN_SCOPE_INVALID = "RUN_SCOPE_INVALID"

    # --- Internal execution (class-level defaults; surface via run diagnostics) ---
    CARDRE_ERROR = "CARDRE_ERROR"
    NODE_FAILED_WITH_ARTIFACTS = "NODE_FAILED_WITH_ARTIFACTS"
    NODE_ROLE_ACCESS_VIOLATION = "NODE_ROLE_ACCESS_VIOLATION"
    RUN_LEASE_LOST = "RUN_LEASE_LOST"


# Internal-only codes that never cross the HTTP boundary. They surface via run
# diagnostics or process-local exceptions, never as API error envelopes, so
# they are excluded from the public TypeScript union. Kept in one canonical set
# shared by scripts/generate-error-codes.py and tests/test_error_code_sync.py.
INTERNAL_ERROR_CODES: frozenset[ErrorCode] = frozenset({
    ErrorCode.CARDRE_ERROR,
    ErrorCode.NODE_FAILED_WITH_ARTIFACTS,
    ErrorCode.NODE_ROLE_ACCESS_VIOLATION,
    ErrorCode.RUN_LEASE_LOST,
    ErrorCode.RUN_LIFECYCLE_ERROR,
    ErrorCode.MANIFEST_STEP_MISSING,
    ErrorCode.MANIFEST_PLAN_MISSING,
    ErrorCode.INPUT_CONTRACT_VIOLATION,
    ErrorCode.OUTPUT_CONTRACT_VIOLATION,
    ErrorCode.ARTIFACT_STAGING_FAILED,
    ErrorCode.ARTIFACT_PUBLISH_FAILED,
    ErrorCode.RUN_EXECUTION_FAILED,
    ErrorCode.RUN_CANCELLED,
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


class GovernanceNotEnabled(CardreError):
    """Raised when a governance-gated feature is accessed without CARDRE_GOVERNANCE=1."""
    code = ErrorCode.GOVERNANCE_NOT_ENABLED
    status_code = 403


class GraphValidationError(CardreError):
    """Raised when a plan graph fails validation."""
    code = ErrorCode.GRAPH_VALIDATION_ERROR
    status_code = 500


class PlanContainsUnavailableNodesError(CardreError):
    """Raised before a run starts when a plan contains unavailable nodes."""
    code = ErrorCode.PLAN_CONTAINS_UNAVAILABLE_NODES
    status_code = 400

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        step_ids = ", ".join(i["step_id"] for i in issues)
        message = (
            f"Plan contains {len(issues)} unavailable node(s): {step_ids}. "
            "See context for details."
        )
        super().__init__(message, context={"issues": issues})


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


class ArtifactReadError(CardreError):
    """Raised when an artifact file cannot be read (missing or hash mismatch)."""
    code = ErrorCode.ARTIFACT_READ_ERROR
    status_code = 400


class ArtifactWriteError(CardreError):
    """Raised when an artifact file cannot be written."""
    code = ErrorCode.ARTIFACT_WRITE_ERROR
    status_code = 500


class NodeNotAvailableForLaunch(CardreError):
    """Raised when a deferred node is instantiated in launch mode."""
    code = ErrorCode.NODE_NOT_AVAILABLE_FOR_LAUNCH
    status_code = 400


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


class RunScopeNotAvailableForLaunch(CardreError):
    """Raised when a run scope is disabled for launch (e.g. ``to_node``)."""
    code = ErrorCode.RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH
    status_code = 400


class BranchValidationError(CardreError):
    """Raised when branch creation or management validation fails."""
    code = ErrorCode.BRANCH_VALIDATION_ERROR
    status_code = 400


class OptionalDependencyNotInstalled(CardreError):
    """Raised when a node's optional dependency group is not installed."""
    code = ErrorCode.OPTIONAL_DEPENDENCY_NOT_INSTALLED
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
    "ErrorCode",
    "GovernanceNotEnabled",
    "GraphValidationError",
    "INTERNAL_ERROR_CODES",
    "MissingInputArtifactError",
    "NodeRoleAccessViolation",
    "NodeNotAvailableForLaunch",
    "NodeVersionMismatchError",
    "OptionalDependencyNotInstalled",
    "ParameterValidationError",
    "PlanContainsUnavailableNodesError",
    "PlanVersionNotCommittedError",
    "RunLifecycleError",
    "RunNotFoundError",
    "RunNotRunningError",
    "RunPlanVersionMismatchError",
    "RunScopeNotAvailableForLaunch",
    "SchemaVersionError",
]
