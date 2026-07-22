"""Project provisioner port — initializes a new project on disk."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProjectProvisionerPort(Protocol):
    """Initialize a new project at the given root path.

    Creates the SQLite database, subdirectories, and schema.
    Raises STORE_ALREADY_EXISTS if the project already exists.
    """

    def initialize(self, root: Path) -> None: ...
