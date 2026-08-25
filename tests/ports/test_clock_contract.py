"""Clock port contract tests (Batch 2A).

Covers the real ``SystemClock`` and a deterministic fake
(``DeterministicClock`` in ``tests/ports/_fakes``). ``now_iso`` must return a
parseable UTC ISO-8601 string, and successive calls must be nondecreasing.
"""

from __future__ import annotations

from datetime import datetime

from cardre.adapters.system.clock import SystemClock
from tests.ports._fakes import DeterministicClock


class TestSystemClockContract:
    def test_now_iso_is_parseable_utc_iso(self):
        value = SystemClock().now_iso()
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None, "SystemClock must return a timezone-aware UTC timestamp"
        assert parsed.utcoffset().total_seconds() == 0

    def test_now_iso_is_nondecreasing(self):
        clock = SystemClock()
        first = clock.now_iso()
        second = clock.now_iso()
        assert second >= first


class TestDeterministicClockContract:
    def test_now_iso_is_parseable_utc_iso(self):
        value = DeterministicClock().now_iso()
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_now_iso_advances_monotonically(self):
        clock = DeterministicClock()
        samples = [clock.now_iso() for _ in range(5)]
        assert samples == sorted(samples)
        assert len(set(samples)) == 5

    def test_now_iso_is_deterministic_given_start(self):
        from datetime import UTC, datetime

        start = datetime(2026, 1, 1, tzinfo=UTC)
        a = DeterministicClock(start)
        b = DeterministicClock(start)
        assert [a.now_iso() for _ in range(3)] == [b.now_iso() for _ in range(3)]
