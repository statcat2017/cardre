"""ResolveProject — resolve a project ID to its filesystem root."""

from __future__ import annotations

from pathlib import Path

from cardre.application.ports.project_registry import ProjectRegistryPort


class ResolveProject:
    """Resolve a project ID to its filesystem root.

    Wraps ``ProjectRegistryPort.resolve_root`` so the API layer
    never imports the registry adapter directly.
    """

    def __init__(self, registry: ProjectRegistryPort) -> None:
        self._registry = registry

    def __call__(self, project_id: str) -> Path | None:
        return self._registry.resolve_root(project_id)
