"""Centralised configuration from environment variables.

All env-var parsing lives here.  Import ``CardreConfig`` and use its
properties instead of reading ``os.environ`` directly.

Environment variables
---------------------
CARDRE_LAUNCH_MODE : bool, default True
    If True, deferred nodes raise ``NodeNotAvailableForLaunch``.
CARDRE_GOVERNANCE : bool, default False
    If True, governance features (branching, comparison, champion) are enabled.
CARDRE_STALE_HEARTBEAT_SECONDS : int, default 300
    Seconds after which a run with no heartbeat is considered stale.
CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS : int, optional
    Overrides the interval used by the executor watchdog to refresh the run
    ``heartbeat_at`` while a node is executing.  Must be positive and less
    than ``CARDRE_STALE_HEARTBEAT_SECONDS``.  Defaults to
    ``max(1, CARDRE_STALE_HEARTBEAT_SECONDS // 4)``.
CARDRE_API_HOST : str, default 127.0.0.1
CARDRE_API_PORT : int, default 8752
CARDRE_REGISTRY_PATH : str, default ~/.cardre/projects.json
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
    heartbeat_watchdog_interval_seconds: int = 75
    api_host: str = "127.0.0.1"
    api_port: int = 8752
    registry_path: Path = field(default_factory=lambda: Path.home() / ".cardre" / "projects.json")

    @classmethod
    def from_env(cls) -> CardreConfig:
        stale = int(os.environ.get("CARDRE_STALE_HEARTBEAT_SECONDS", "300"))
        watchdog_override = os.environ.get("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS")
        if watchdog_override is not None:
            watchdog = int(watchdog_override)
            if watchdog < 1:
                raise ValueError(
                    f"CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS={watchdog_override!r} "
                    "must be positive"
                )
            if watchdog >= stale:
                raise ValueError(
                    f"CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS={watchdog_override!r} "
                    f"must be less than CARDRE_STALE_HEARTBEAT_SECONDS={stale}"
                )
        else:
            watchdog = max(1, stale // 4)
        return cls(
            launch_mode=_env_bool("CARDRE_LAUNCH_MODE", True),
            governance_enabled=_env_bool("CARDRE_GOVERNANCE", False),
            stale_heartbeat_seconds=stale,
            heartbeat_watchdog_interval_seconds=watchdog,
            api_host=os.environ.get("CARDRE_API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("CARDRE_API_PORT", "8752")),
            registry_path=Path(os.environ.get("CARDRE_REGISTRY_PATH", str(Path.home() / ".cardre" / "projects.json"))),
        )


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true")
