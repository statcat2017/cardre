"""Build the FastAPI application from the composition root."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings


def build_app() -> tuple[FastAPI, Callable[[], None]]:
    """Build the application: read settings, wire container, create FastAPI app.

    Returns (app, shutdown_callable).
    """
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return app, lambda: None
