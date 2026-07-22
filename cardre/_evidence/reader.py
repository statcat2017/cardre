"""Backward-compat adapter — wraps new EvidenceReader for old ProjectStore callers.

Deprecated: use ``cardre.adapters.evidence.reader.EvidenceReader`` instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from cardre._evidence.kinds import (
    EvidenceKind,
    EvidenceParseError,
)
from cardre.adapters.evidence.parsers import get_adapter, match
from cardre.adapters.evidence.reader import EvidenceReader
from cardre.domain.artifacts import ArtifactRef
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.run_step_repo import RunStepRepository


class _StoreArtifactReader:
    """Adapts a ProjectStore to the ArtifactReader protocol."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def read_bytes(self, artifact: ArtifactRef) -> bytes:
        return self.resolve_path(artifact).read_bytes()

    def resolve_path(self, artifact: ArtifactRef) -> Path:
        return self._store.artifact_path(artifact)


class ArtifactEvidenceReader:
    """Backward-compatible reader that wraps the new EvidenceReader.

    Constructed with a ``ProjectStore``, just like the original.
    """

    def __init__(self, store: Any) -> None:
        self._inner = EvidenceReader(
            artifact_reader=_StoreArtifactReader(store),
            artifact_repo=ArtifactRepository(store),
            run_step_repo=RunStepRepository(store),
        )

    def find(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any:
        return self._inner.find(artifacts, kind)

    def find_optional(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any | None:
        return self._inner.find_optional(artifacts, kind)

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        return self._inner.read(artifact_id, kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        return self._inner.read_optional(artifact_id, kind)

    def require_model(self, model_art: ArtifactRef, node_type: str) -> Any:
        return self._inner.require_model(model_art, node_type)

    def read_dataframe(self, art: ArtifactRef) -> pl.DataFrame:
        return self._inner.read_dataframe(art)

    def read_step_output_optional(self, run_step_id: str, kind: EvidenceKind) -> Any | None:
        return self._inner.read_step_output_optional(run_step_id, kind)

    # ------------------------------------------------------------------
    # Internal (exposed for test parity — deprecated)
    # ------------------------------------------------------------------

    def _match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        spec = get_adapter(kind)
        return match(artifacts, spec.profile, self._inner._reader)

    def _parse(self, art: ArtifactRef, kind: EvidenceKind) -> Any:
        path = self._inner._reader.resolve_path(art)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")
        return get_adapter(kind).parse(path, art, self._inner._reader)


__all__ = ["ArtifactEvidenceReader"]
