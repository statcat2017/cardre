"""CreateProject use case — bootstrap a new project."""

from __future__ import annotations

from pathlib import Path

from cardre.application.ports.project_provisioner import ProjectProvisionerPort
from cardre.application.ports.project_registry import ProjectRegistryPort
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.errors import CardreError
from cardre.domain.project import Project


class CreateProject:
    """Create a new project: provision filesystem + sqlite, insert project row, register."""

    def __init__(
        self,
        provisioner: ProjectProvisionerPort,
        registry: ProjectRegistryPort,
        uow_factory: UnitOfWorkFactory,
    ) -> None:
        self._provisioner = provisioner
        self._registry = registry
        self._uow_factory = uow_factory

    def __call__(self, name: str, path: str) -> Project:
        root = Path(path)
        if not root.is_absolute():
            raise CardreError(
                f"Project path must be absolute, got {path!r}.",
                code="INVALID_PROJECT_PATH",
                context={"path": path},
            )
        if ".." in root.parts:
            raise CardreError(
                f"Project path must not contain '..' traversal, got {path!r}.",
                code="INVALID_PROJECT_PATH",
                context={"path": path},
            )

        self._provisioner.initialize(root)

        with self._uow_factory.for_root(root) as uow:
            project_id = uow.projects.create(name)

        try:
            self._registry.register(project_id, root)
        except Exception:
            # Compensation: registry write failed — remove the orphan project
            # directory that is now undiscoverable.
            import shutil
            shutil.rmtree(root, ignore_errors=True)
            raise

        with self._uow_factory.for_root(root) as uow:
            project = uow.projects.get(project_id)
            assert project is not None
            return project
