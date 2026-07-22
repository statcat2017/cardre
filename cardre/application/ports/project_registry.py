"""Project registry port — maps project IDs to filesystem roots."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProjectRegistryPort(Protocol):
    """Persist project-id to project-root mappings."""

    def register(self, project_id: str, root: str | Path) -> None: ...

    def resolve_root(self, project_id: str) -> Path | None: ...

    def list_all(self) -> dict[str, str]: ...
