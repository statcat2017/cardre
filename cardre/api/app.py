"""Minimal FastAPI application for Cardre v2.

Phase 2 skeleton — only the routes needed for the manual-binning spike.
Phase 4 expands this with the full API surface.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cardre.api.errors import CardreApiError, cardre_api_error_handler, cardre_error_handler
from cardre.domain.errors import CardreError
from cardre.api.routes import health, manual_binning, projects


def create_app() -> FastAPI:
    """Create and configure the Cardre v2 FastAPI application."""
    app = FastAPI(
        title="Cardre v2 API",
        version="0.2.0",
        description="Auditable open-source credit scorecard builder — v2.",
    )

    # CORS: allow all origins for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handlers
    app.add_exception_handler(CardreError, cardre_error_handler)
    app.add_exception_handler(CardreApiError, cardre_api_error_handler)

    # Routes
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(manual_binning.router)

    return app


app = create_app()
