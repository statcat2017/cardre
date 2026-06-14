"""Project registry management — the singleton ~/.cardre/projects.json.

Owns the registry CRUD so that route handlers stay thin.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cardre.store import ProjectStore

_DEFAULT_REGISTRY_PATH = Path.home() / ".cardre" / "projects.json"


def _registry_path() -> Path:
    return Path(os.environ.get("CARDRE_REGISTRY_PATH", _DEFAULT_REGISTRY_PATH))


class ProjectNotFoundError(KeyError):
    """Raised when a project ID is not found in the registry."""


def load_registry() -> dict:
    path = _registry_path()
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_registry(registry: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2))
    with tmp.open() as f:
        os.fsync(f.fileno())
    tmp.rename(path)


def get_store_for_project(project_id: str) -> ProjectStore:
    registry = load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise ProjectNotFoundError(f"PROJECT_NOT_FOUND: No project with ID {project_id}")
    return ProjectStore(Path(entry["path"]))


def get_entry(project_id: str) -> dict | None:
    registry = load_registry()
    return registry.get(project_id)


def project_path_exists(project_id: str) -> bool:
    entry = get_entry(project_id)
    if entry is None:
        return False
    return (Path(entry["path"]) / "cardre.sqlite").exists()


def validate_project_path(path: Path) -> None:
    """Validate a project path before creation. Raises ValueError with code and message."""
    if path.is_symlink():
        raise ValueError("SYMLINK: Project path must not be a symlink")

    blocked_prefixes = Path("/etc"), Path("/proc"), Path("/sys"), Path("/dev"), Path("/boot"), Path("/var")
    if any(str(path).startswith(str(p)) for p in blocked_prefixes):
        raise ValueError("BLOCKED_PATH: Project path must not be under system directories")

    if path.exists():
        if (path / "cardre.sqlite").exists():
            raise ValueError(f"PROJECT_EXISTS: A Cardre project already exists at {path}")
        raise ValueError(f"DIR_EXISTS: Directory {path} exists but is not a Cardre project")


def create_project_registry_entry(project_id: str, path: Path, name: str) -> None:
    registry = load_registry()
    registry[project_id] = {"path": str(path.resolve()), "name": name}
    save_registry(registry)
