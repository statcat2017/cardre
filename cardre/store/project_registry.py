"""Project registry storage for mapping project ids to roots."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


class ProjectRegistry:
    """Persist project-id to project-root mappings."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def register(self, project_id: str, root: str | Path) -> None:
        data = self._read()
        data[project_id] = str(Path(root).resolve())
        self._write(data)

    def resolve_root(self, project_id: str) -> Path | None:
        data = self._read()
        root = data.get(project_id)
        if root is None:
            return None
        return Path(root).resolve()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.path.parent, encoding="utf-8") as tmp:
            json.dump(data, tmp, sort_keys=True)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)
