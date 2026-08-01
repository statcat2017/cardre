"""Manifest publisher port — canonical run-manifest publication boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cardre.domain.diagnostics import JsonDict


@runtime_checkable
class ManifestPublisherPort(Protocol):
    """Canonical run-manifest publication and read access."""

    def publish(self, run_id: str, payload: JsonDict) -> Path: ...
    def read(self, run_id: str) -> JsonDict | None: ...
    def list_manifests(self) -> list[dict[str, str]]: ...


@runtime_checkable
class ManifestPublisherFactoryPort(Protocol):
    """Resolve a ``ManifestPublisherPort`` for a project."""

    def __call__(self, project_id: str) -> ManifestPublisherPort: ...


__all__ = ["ManifestPublisherFactoryPort", "ManifestPublisherPort"]
