"""Immutable settings loaded once from environment at bootstrap."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    launch_mode: bool = True
    governance_enabled: bool = False
    stale_heartbeat_seconds: int = 300
    heartbeat_watchdog_interval_seconds: int = 75
    api_host: str = "127.0.0.1"
    api_port: int = 8752
    registry_path: Path = field(default_factory=lambda: Path.home() / ".cardre" / "projects.json")
    cors_origins: tuple[str, ...] = (
        "http://localhost:1420",
        "http://localhost:5173",
        "http://127.0.0.1:1420",
        "http://127.0.0.1:5173",
    )
    max_workers: int = 1

    @classmethod
    def from_env(cls) -> Settings:
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

        cors_raw = os.environ.get("CARDRE_CORS_ORIGINS", "").strip()
        if cors_raw:
            cors = tuple(o.strip() for o in cors_raw.split(",") if o.strip())
        else:
            cors = (
                "http://localhost:1420",
                "http://localhost:5173",
                "http://127.0.0.1:1420",
                "http://127.0.0.1:5173",
            )

        return cls(
            launch_mode=_env_bool("CARDRE_LAUNCH_MODE", True),
            governance_enabled=_env_bool("CARDRE_GOVERNANCE", False),
            stale_heartbeat_seconds=stale,
            heartbeat_watchdog_interval_seconds=watchdog,
            api_host=os.environ.get("CARDRE_API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("CARDRE_API_PORT", "8752")),
            registry_path=Path(os.environ.get("CARDRE_REGISTRY_PATH", str(Path.home() / ".cardre" / "projects.json"))),
            cors_origins=cors,
            max_workers=int(os.environ.get("CARDRE_MAX_WORKERS", "1")),
        )


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true")
