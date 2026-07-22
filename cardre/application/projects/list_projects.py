"""ListProjects use case — list all registered projects."""

from __future__ import annotations

from pathlib import Path

from cardre.application.ports.project_registry import ProjectRegistryPort
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.project import Project


class ListProjects:
    """List all registered projects, separating unavailable ones."""

    def __init__(
        self,
        registry: ProjectRegistryPort,
        uow_factory: UnitOfWorkFactory,
    ) -> None:
        self._registry = registry
        self._uow_factory = uow_factory

    def __call__(self) -> tuple[list[Project], list[dict[str, str]]]:
        registry = self._registry.list_all()
        projects: list[Project] = []
        unavailable: list[dict[str, str]] = []
        for project_id, root_str in registry.items():
            root = Path(root_str)
            if not root.exists():
                unavailable.append({
                    "project_id": project_id,
                    "root": root_str,
                    "code": "PROJECT_ROOT_MISSING",
                    "message": f"Project root {root_str} does not exist.",
                })
                continue
            try:
                with self._uow_factory.for_root_readonly(root) as uow:
                    project = uow.projects.get(project_id)
                    if project is not None:
                        projects.append(project)
                    else:
                        unavailable.append({
                            "project_id": project_id,
                            "root": root_str,
                            "code": "PROJECT_METADATA_MISSING",
                            "message": f"Project {project_id!r} not found in store at {root_str}.",
                        })
            except Exception as exc:
                unavailable.append({
                    "project_id": project_id,
                    "root": root_str,
                    "code": "PROJECT_OPEN_FAILED",
                    "message": str(exc),
                })
        return projects, unavailable
