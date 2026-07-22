"""StagingOutputPublisher — OutputPublisher implementation for node execution.

Wraps a ``StagedArtifactWriter`` and accumulates metrics, warnings, and
execution fingerprint to produce a ``NodeResult``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from cardre.application.ports.artifact_store import StagedArtifactWriter
from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import NodeResult


class StagingOutputPublisher:
    """Binds a ``StagedArtifactWriter`` to the ``OutputPublisher`` protocol."""

    def __init__(self, writer: StagedArtifactWriter) -> None:
        self._writer = writer
        self._staged_artifacts: list[Any] = []
        self._metrics: JsonDict = {}
        self._warnings: list[JsonDict] = []
        self._execution_fingerprint: JsonDict | None = None

    def publish_json(
        self,
        *,
        role: str,
        kind: EvidenceKind,
        payload: JsonDict,
        metadata: JsonDict | None = None,
    ) -> Any:
        staged = self._writer.stage_json(role=role, kind=kind.value, payload=payload, metadata=metadata)
        self._staged_artifacts.append(staged)
        return staged

    def publish_table(
        self,
        *,
        role: str,
        kind: EvidenceKind,
        frame: pl.DataFrame,
        metadata: JsonDict | None = None,
    ) -> Any:
        staged = self._writer.stage_table(role=role, kind=kind.value, frame=frame, metadata=metadata)
        self._staged_artifacts.append(staged)
        return staged

    def add_metric(self, name: str, value: float | int | str | bool) -> None:
        self._metrics[name] = value

    def add_warning(self, warning: JsonDict) -> None:
        self._warnings.append(warning)

    def set_execution_fingerprint(self, fp: JsonDict) -> None:
        self._execution_fingerprint = fp

    def build_result(self) -> NodeResult:
        return NodeResult(
            staged_artifacts=list(self._staged_artifacts),
            metrics=dict(self._metrics),
            execution_fingerprint=dict(self._execution_fingerprint) if self._execution_fingerprint else None,
            warnings=list(self._warnings),
        )


__all__ = ["StagingOutputPublisher"]
