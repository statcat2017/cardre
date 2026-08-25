from __future__ import annotations

from pathlib import Path

from cardre.application.projects.list_projects import ListProjects
from cardre.domain.errors import CardreError, ErrorCode


class _Registry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_all(self) -> dict[str, str]:
        return {"project-1": str(self.root)}


class _UnitOfWorkFactory:
    def for_root_readonly(self, root: Path):
        raise CardreError(
            "Recreate the project to continue.",
            code=ErrorCode.STORE_VERSION_INCOMPATIBLE,
        )


def test_list_projects_preserves_store_version_error(tmp_path: Path) -> None:
    projects, unavailable = ListProjects(_Registry(tmp_path), _UnitOfWorkFactory())()

    assert projects == []
    assert unavailable[0]["code"] == ErrorCode.STORE_VERSION_INCOMPATIBLE
