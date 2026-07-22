"""JSON-file-backed project registry adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cardre.domain.errors import CardreError


class JsonProjectRegistry:
    """Persist project-id to project-root mappings in a JSON file."""

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

    def list_all(self) -> dict[str, str]:
        return self._read()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            raise CardreError(
                f"Project registry at {self.path} is corrupted: {exc}",
                code="REGISTRY_CORRUPTED",
                context={"path": str(self.path)},
            ) from exc
        if not isinstance(payload, dict):
            raise CardreError(
                f"Project registry at {self.path} contains non-dict payload "
                f"(got {type(payload).__name__})",
                code="REGISTRY_CORRUPTED",
                context={"path": str(self.path), "type": type(payload).__name__},
            )
        return {str(key): str(value) for key, value in payload.items()}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.path.parent, encoding="utf-8") as tmp:
            json.dump(data, tmp, sort_keys=True)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)
