from __future__ import annotations

from cardre.bootstrap.settings import Settings


def launch_mode() -> bool:
    return Settings.from_env().launch_mode


def governance_enabled() -> bool:
    return Settings.from_env().governance_enabled


__all__ = ["governance_enabled", "launch_mode"]
