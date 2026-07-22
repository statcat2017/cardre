"""Port for publishing run manifests to the filesystem."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cardre.domain.diagnostics import JsonDict


@runtime_checkable
class ManifestPublisherPort(Protocol):
    def publish(self, run_id: str, payload: JsonDict) -> Path: ...
