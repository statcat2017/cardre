"""V1 compatibility shim — re-exports from cardre.domain.errors.

Phase 5: existing node code imports ``CardreError``, ``Diagnostic``,
``Result``, ``Ok``, ``Degraded`` from ``cardre.errors``.
These now live in ``cardre.domain.errors`` (except Result/Ok/Degraded,
which were v1-specific and are kept as re-exports here).
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from cardre.domain.errors import (
    ArtifactReadError,
    ArtifactWriteError,
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

T = TypeVar("T")


class Result(Generic[T]):
    """V1-compatible Result wrapper (Ok / Degraded / Error).

    Preserved for collector.py which constructs Ok() and Degraded()
    instances.
    """
    def __init__(self, value: T | None = None, *, ok: bool = True,
                 degraded: bool = False,
                 diagnostics: list[Any] | None = None) -> None:
        self._value = value
        self._ok = ok
        self._degraded = degraded
        self.diagnostics = diagnostics or []

    def is_ok(self) -> bool:
        return self._ok and not self._degraded

    def is_degraded(self) -> bool:
        return self._degraded

    def unwrap(self) -> T | None:
        return self._value


def Ok(value: Any = None) -> Result:
    return Result(value, ok=True)


def Degraded(value: Any = None, diagnostics: list[Any] | None = None) -> Result:
    return Result(value, ok=False, degraded=True, diagnostics=diagnostics)


def is_ok(result: Result) -> bool:
    return result.is_ok()


def is_degraded(result: Result) -> bool:
    return result.is_degraded()


__all__ = [
    "ArtifactReadError",
    "ArtifactWriteError",
    "CardreError",
    "ConcurrentRunError",
    "Degraded",
    "Diagnostic",
    "GovernanceNotEnabled",
    "GraphValidationError",
    "MissingInputArtifactError",
    "NodeNotAvailableForLaunch",
    "Ok",
    "OptionalDependencyNotInstalled",
    "ParameterValidationError",
    "PlanContainsUnavailableNodesError",
    "Result",
    "RunLifecycleError",
    "SchemaVersionError",
    "is_degraded",
    "is_ok",
]
