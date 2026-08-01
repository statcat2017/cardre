"""Build the FastAPI application from the composition root."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings


def build_app() -> tuple[FastAPI, Callable[[], None]]:
    """Build the application: read settings, wire container, create FastAPI app.

    On startup, incomplete filesystem publications (artifacts staged but not
    finalized, manifests not yet published) are reconciled from the durable
    outbox, so a crash between a DB commit and its filesystem side effect is
    repaired.

    Returns (app, shutdown_callable).
    """
    settings = Settings.from_env()
    container = build_container(settings)
    container.reconcile_publications_factory()()
    app = create_app(container)
    shutdown = container.async_dispatcher.shutdown
    return app, shutdown
