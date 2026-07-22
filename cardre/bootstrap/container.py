"""Composition root — wires adapters to ports and builds use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.projects.create_project import CreateProject
from cardre.application.projects.get_project import GetProject
from cardre.application.projects.list_projects import ListProjects
from cardre.bootstrap.settings import Settings


@dataclass
class Container:
    settings: Settings
    project_registry: Any = None
    project_provisioner: Any = None
    uow_factory: Any = None
    create_project: Any = None
    list_projects: Any = None
    get_project: Any = None


def build_container(settings: Settings) -> Container:
    registry = JsonProjectRegistry(settings.registry_path)
    provisioner = SqliteProjectProvisioner()
    uow_factory = SqliteUnitOfWorkFactory(registry)

    return Container(
        settings=settings,
        project_registry=registry,
        project_provisioner=provisioner,
        uow_factory=uow_factory,
        create_project=CreateProject(provisioner, registry, uow_factory),
        list_projects=ListProjects(registry, uow_factory),
        get_project=GetProject(registry, uow_factory),
    )
