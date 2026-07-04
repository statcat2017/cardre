"""Tests for CardreConfig — env-var parsing, defaults, and validation."""

from __future__ import annotations

import pytest

from cardre.config import CardreConfig


class TestHeartbeatWatchdogInterval:
    """heartbeat_watchdog_interval_seconds derivation and override."""

    def test_defaults_to_stale_divided_by_four(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "120")
        monkeypatch.delenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", raising=False)
        cfg = CardreConfig.from_env()
        assert cfg.stale_heartbeat_seconds == 120
        assert cfg.heartbeat_watchdog_interval_seconds == 30

    def test_defaults_to_at_least_one(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
        monkeypatch.delenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", raising=False)
        cfg = CardreConfig.from_env()
        assert cfg.heartbeat_watchdog_interval_seconds == 1

    def test_override_is_accepted(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "120")
        monkeypatch.setenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", "7")
        cfg = CardreConfig.from_env()
        assert cfg.heartbeat_watchdog_interval_seconds == 7

    def test_override_must_be_positive(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "120")
        monkeypatch.setenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", "0")
        with pytest.raises(ValueError, match="must be positive"):
            CardreConfig.from_env()

    def test_override_must_be_less_than_stale(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "120")
        monkeypatch.setenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", "120")
        with pytest.raises(ValueError, match="must be less than"):
            CardreConfig.from_env()

    def test_override_greater_than_stale_rejected(self, monkeypatch):
        monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "120")
        monkeypatch.setenv("CARDRE_HEARTBEAT_WATCHDOG_INTERVAL_SECONDS", "300")
        with pytest.raises(ValueError, match="must be less than"):
            CardreConfig.from_env()

    def test_original_defaults_preserved(self):
        """With no env overrides, defaults match the original hardcoded values."""
        cfg = CardreConfig.from_env()
        assert cfg.stale_heartbeat_seconds == 300
        assert cfg.heartbeat_watchdog_interval_seconds == 75
