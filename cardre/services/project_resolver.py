"""ProjectResolver — registry-backed project store resolution."""

from __future__ import annotations

from pathlib import Path

from cardre.api.errors import PROJECT_NOT_FOUND
from cardre.domain.errors import CardreError
from cardre.store.project_registry import ProjectRegistry


class ProjectResolver:
    """Resolve project ids to canonical project roots."""

    def __init__(self, registry_path: str | Path) -> None:
        self._registry = ProjectRegistry(registry_path)

    def register_project(self, project_id: str, root: str | Path) -> None:
        self._registry.register(project_id, root)

    def list_projects(self) -> dict[str, str]:
        """Return all registered project_id -> root mappings."""
        return self._registry.list_all()

    def resolve_root(self, project_id: str) -> Path:
        root = self._registry.resolve_root(project_id)
        if root is None or not root.exists():
            raise CardreError(
                f"Project {project_id!r} not found",
                code=PROJECT_NOT_FOUND,
                context={"project_id": project_id},
                status_code=404,
            )
        return root
