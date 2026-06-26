"""Centralised configuration from environment variables.

All env-var parsing lives here.  Import ``CardreConfig`` and use its
properties instead of reading ``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CardreConfig:
    launch_mode: bool = True
    governance_enabled: bool = False
    stale_heartbeat_seconds: int = 300
    api_host: str = "127.0.0.1"
    api_port: int = 8752
    registry_path: Path = field(default_factory=lambda: Path.home() / ".cardre" / "projects.json")

    @classmethod
    def from_env(cls) -> CardreConfig:
        return cls(
            launch_mode=_env_bool("CARDRE_LAUNCH_MODE", True),
            governance_enabled=_env_bool("CARDRE_GOVERNANCE", False),
            stale_heartbeat_seconds=int(os.environ.get("CARDRE_STALE_HEARTBEAT_SECONDS", "300")),
            api_host=os.environ.get("CARDRE_API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("CARDRE_API_PORT", "8752")),
            registry_path=Path(os.environ.get("CARDRE_REGISTRY_PATH", str(Path.home() / ".cardre" / "projects.json"))),
        )


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true")
