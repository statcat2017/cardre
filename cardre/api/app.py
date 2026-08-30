"""FastAPI application for the Cardre hexagonal architecture.

Created by bootstrap/build_app.py with a Container. All routes are registered
here. The app lifespan owns process-level resources (e.g. the async run
dispatcher) so they are drained when uvicorn shuts down.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cardre._version import __version__
from cardre.api.errors import (
    CardreApiError,
    cardre_api_error_handler,
    cardre_error_handler,
    unexpected_error_handler,
)
from cardre.api.routes import (
    artifacts,
    evidence,
    exports,
    health,
    node_types,
    plans,
    projects,
    reports,
    runs,
)
from cardre.domain.errors import CardreError


def _lifespan_factory(container: object):
    @asynccontextmanager
    async def _inner(app: FastAPI) -> AsyncIterator[None]:
        watchdog = getattr(container, "stale_run_recovery_watchdog", None)
        if watchdog is not None and hasattr(watchdog, "start"):
            watchdog.start()
        try:
            yield
        finally:
            dispatcher = getattr(container, "async_dispatcher", None)
            if dispatcher is not None and hasattr(dispatcher, "shutdown"):
                dispatcher.shutdown()
            if watchdog is not None and hasattr(watchdog, "stop"):
                watchdog.stop()

    return _inner


def create_app(container: object) -> FastAPI:
    """Create and configure the Cardre FastAPI application with the given container."""
    app = FastAPI(
        title="Cardre v2 API",
        version=__version__,
        description="Auditable open-source credit scorecard builder — v2.",
        lifespan=_lifespan_factory(container),
    )

    app.state.container = container

    settings = getattr(container, "settings", None)
    if settings is not None:
        cors_origins = list(getattr(settings, "cors_origins", [
            "http://localhost:1420",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
            "http://127.0.0.1:5173",
        ]))
    else:
        cors_origins = [
            "http://localhost:1420",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
            "http://127.0.0.1:5173",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    app.add_exception_handler(CardreError, cardre_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(CardreApiError, cardre_api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error_handler)  # type: ignore[arg-type]

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(plans.router)
    app.include_router(runs.router)
    app.include_router(evidence.router)
    app.include_router(artifacts.router)
    app.include_router(node_types.router)
    app.include_router(exports.router)
    app.include_router(reports.router)

    return app
