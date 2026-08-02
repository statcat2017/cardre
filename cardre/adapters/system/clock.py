"""System clock — concrete ClockPort using utc_now_iso."""

from __future__ import annotations

from cardre.domain.diagnostics import utc_now_iso


class SystemClock:
    """Concrete ClockPort that delegates to ``utc_now_iso``."""

    def now_iso(self) -> str:
        return utc_now_iso()
