"""Evidence reader ports used by application use cases.

``EvidenceReaderPort`` is the typed-evidence surface used by reporting and
governance use cases. ``NodeInputReader`` is the typed-evidence surface used
by node execution: it binds an ``ArtifactReader`` to the domain ``EvidenceKind``
registry so nodes can read inputs without depending on concrete adapters.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import polars as pl

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind


@runtime_checkable
class EvidenceReaderPort(Protocol):
    def read_optional(self, artifact_id: str, kind: Any) -> Any | None: ...

    def read_step_output_optional(self, run_step_id: str, kind: Any) -> Any | None: ...


@runtime_checkable
class NodeInputReader(Protocol):
    def find_optional(
        self, artifacts: list[ArtifactRef], kind: EvidenceKind
    ) -> Any | None: ...

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any: ...

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None: ...

    def read_dataframe(self, art: ArtifactRef) -> pl.DataFrame: ...

    def read_bytes(self, art: ArtifactRef) -> bytes: ...


__all__ = ["EvidenceReaderPort", "NodeInputReader"]
