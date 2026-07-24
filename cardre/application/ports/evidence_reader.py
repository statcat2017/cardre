"""Typed evidence reader port used by reporting use cases."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvidenceReaderPort(Protocol):
    def read_optional(self, artifact_id: str, kind: Any) -> Any | None: ...

    def read_step_output_optional(self, run_step_id: str, kind: Any) -> Any | None: ...


__all__ = ["EvidenceReaderPort"]
