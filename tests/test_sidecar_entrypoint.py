"""Tests for the sidecar console entrypoint."""

from __future__ import annotations


class TestSidecarEntrypoint:
    def test_main_uses_config_port(self, monkeypatch):
        from sidecar import __main__ as sidecar_main

        captured: dict[str, object] = {}

        def fake_run(app, host, port, log_level):
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["log_level"] = log_level

        monkeypatch.setattr(sidecar_main.uvicorn, "run", fake_run)
        monkeypatch.setattr(
            sidecar_main.CardreConfig,
            "from_env",
            classmethod(lambda cls: cls(api_host="127.0.0.1", api_port=8752)),
        )

        sidecar_main.main()

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8752
        assert captured["log_level"] == "info"
