"""Tests for the sidecar console entrypoint."""

from __future__ import annotations

from types import SimpleNamespace


class TestSidecarEntrypoint:
    def test_main_uses_config_port(self, monkeypatch):
        from sidecar import __main__ as sidecar_main

        captured: dict[str, object] = {}
        settings = SimpleNamespace(api_host="127.0.0.1", api_port=8752)
        container = SimpleNamespace(settings=settings)
        app = SimpleNamespace(state=SimpleNamespace(container=container))

        def fake_run(app_arg, host, port, log_level):
            captured["app"] = app_arg
            captured["host"] = host
            captured["port"] = port
            captured["log_level"] = log_level

        def fake_build_app():
            return app, lambda: None

        monkeypatch.setattr(sidecar_main.uvicorn, "run", fake_run)
        monkeypatch.setattr(sidecar_main, "build_app", fake_build_app)

        sidecar_main.main()

        assert captured["app"] is app
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 8752
        assert captured["log_level"] == "info"
