"""StepInputCollection — InputCollection implementation for node execution.

Wraps an ``EvidenceReader`` and the node's input artifacts to satisfy
the ``InputCollection`` protocol defined in ``cardre/nodes/contracts.py``.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.schemas import SCHEMA_FROZEN_SCORECARD_BUNDLE
from cardre.adapters.evidence.reader import EvidenceReader
from cardre.domain.artifacts import ArtifactRef
from cardre.execution.context import TargetMeta


class StepInputCollection:
    """Binds an ``EvidenceReader`` and a list of input ``ArtifactRef``s
    to the ``InputCollection`` protocol."""

    def __init__(
        self,
        reader: EvidenceReader,
        input_artifacts: list[ArtifactRef],
    ) -> None:
        self._reader = reader
        self._input_artifacts = input_artifacts

    def by_role(self, role: str) -> list[ArtifactRef]:
        return [a for a in self._input_artifacts if a.role == role]

    def by_kind(self, kind: EvidenceKind) -> list[Any]:
        """Return all artifacts matching *kind*. Raises ``AmbiguousEvidenceError``
        if multiple artifacts match (they should be disambiguated by the caller
        or the plan author)."""
        result = self._reader.find_optional(self._input_artifacts, kind)
        if result is None:
            return []
        return [result]

    def first(self, role: str) -> Any | None:
        matched = self.by_role(role)
        return matched[0] if matched else None

    def require(self, role: str, node_type: str) -> ArtifactRef:
        art = self.first(role)
        if art is None:
            raise ValueError(f"{node_type} requires a '{role}' artifact")
        return art  # type: ignore[no-any-return]

    def read(self, artifact: ArtifactRef, kind: EvidenceKind) -> Any:
        return self._reader.read(artifact.artifact_id, kind)

    def read_optional(self, artifact: ArtifactRef, kind: EvidenceKind) -> Any | None:
        return self._reader.read_optional(artifact.artifact_id, kind)

    def read_dataframe(self, artifact: ArtifactRef) -> pl.DataFrame:
        return self._reader.read_dataframe(artifact)

    def target_metadata(self) -> Any | None:
        meta = self._reader.find_optional(self._input_artifacts, EvidenceKind.MODELLING_METADATA)
        if meta is None:
            return None
        return TargetMeta(
            target_column=meta.target_column,
            good_values=frozenset(str(v) for v in meta.good_values),
            bad_values=frozenset(str(v) for v in meta.bad_values),
            indeterminate_values=frozenset(str(v) for v in meta.indeterminate_values) if hasattr(meta, "indeterminate_values") else frozenset(),
            all_known=frozenset(str(v) for v in meta.all_known) if hasattr(meta, "all_known") else frozenset(),
        )

    def find_frozen_bundle(self) -> Any | None:
        return next(
            (a for a in self._input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )


__all__ = ["StepInputCollection"]
