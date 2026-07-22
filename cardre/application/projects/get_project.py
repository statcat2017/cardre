"""GetProject use case — get a single project by ID."""

from __future__ import annotations

from cardre.application.ports.project_registry import ProjectRegistryPort
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.errors import CardreError
from cardre.domain.project import Project


class GetProject:
    """Get a single project by ID, resolved via the registry."""

    def __init__(
        self,
        registry: ProjectRegistryPort,
        uow_factory: UnitOfWorkFactory,
    ) -> None:
        self._registry = registry
        self._uow_factory = uow_factory

    def __call__(self, project_id: str) -> Project:
        with self._uow_factory.read_only(project_id) as uow:
            project = uow.projects.get(project_id)
            if project is None:
                raise CardreError(
                    f"Project {project_id!r} not found.",
                    code="PROJECT_NOT_FOUND",
                    context={"project_id": project_id},
                )
            return project
