"""CreateProject use case — bootstrap a new project."""

from __future__ import annotations

import contextlib
from pathlib import Path

from cardre.application.ports.project_provisioner import ProjectProvisionerPort
from cardre.application.ports.project_registry import ProjectRegistryPort
from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.errors import CardreError
from cardre.domain.project import Project


def _remove_provisioned_artifacts(root: Path) -> None:
    """Remove only the files and directories created by ``SqliteProjectProvisioner``.

    Safe to call on a pre-existing directory that contains unrelated files:
    only the known Cardre artifacts are removed, and the root directory is
    removed only if it becomes empty.
    """
    db_path = root / "project.sqlite"
    db_path.unlink(missing_ok=True)
    # WAL and SHM files created by SQLite during initialization
    (root / "project.sqlite-wal").unlink(missing_ok=True)
    (root / "project.sqlite-shm").unlink(missing_ok=True)

    for sub in ("objects", "manifests", "exports"):
        sub_path = root / sub
        if sub_path.is_dir():
            import shutil
            shutil.rmtree(sub_path, ignore_errors=True)

    # Remove root if it is now empty (wasn't there before provisioning).
    with contextlib.suppress(OSError):
        root.rmdir()


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
            # Compensation: registry write failed — remove only the Cardre-created
            # resources so the project directory is not left undiscoverable.
            # Does NOT remove unrelated files that may have existed in the
            # directory before provisioning.
            _remove_provisioned_artifacts(root)
            raise

        with self._uow_factory.for_root(root) as uow:
            project = uow.projects.get(project_id)
            assert project is not None
            return project
