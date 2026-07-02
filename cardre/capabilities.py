"""Derived capabilities from CardreConfig.

Two booleans — launch_mode and governance_enabled — routed through one
place so tests never read env vars directly.
"""

from __future__ import annotations

from cardre.config import CardreConfig


def launch_mode() -> bool:
    """Whether the app is in launch mode (deferred nodes unavailable)."""
    return CardreConfig.from_env().launch_mode


def governance_enabled() -> bool:
    """Whether governance features (branches, comparisons, champion) are on."""
    return CardreConfig.from_env().governance_enabled


__all__ = ["governance_enabled", "launch_mode"]
