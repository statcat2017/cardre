"""Full FastAPI application for Cardre v2 — Phase 4 surface.

All routers are mounted unconditionally. Governance-gated routes return
``GOVERNANCE_DISABLED`` (403) when ``CARDRE_GOVERNANCE=0`` (handled
via the ``require_governance`` dependency on those routers).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cardre._version import __version__
from cardre.api.errors import CardreApiError, cardre_api_error_handler, cardre_error_handler
from cardre.api.routes import (
    artifacts,
    branches,
    champion,
    comparisons,
    evidence,
    exports,
    health,
    manual_binning,
    node_types,
    plans,
    projects,
    reports,
    runs,
)
from cardre.domain.errors import CardreError


def create_app() -> FastAPI:
    """Create and configure the Cardre v2 FastAPI application."""
    app = FastAPI(
        title="Cardre v2 API",
        version=__version__,
        description="Auditable open-source credit scorecard builder — v2.",
    )

    # CORS: explicit local development origins instead of wildcard (per #219)
    import os
    dev_origins = os.environ.get("CARDRE_CORS_ORIGINS", "").strip()
    if dev_origins:
        allowed_origins = [o.strip() for o in dev_origins.split(",") if o.strip()]
    else:
        allowed_origins = [
            "http://localhost:1420",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
            "http://127.0.0.1:5173",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Project-Id", "X-Project-Path"],
    )

    # Error handlers
    app.add_exception_handler(CardreError, cardre_error_handler)  # type: ignore[arg-type]  # FastAPI exception handler typing accepts Exception but we use specific subclasses
    app.add_exception_handler(CardreApiError, cardre_api_error_handler)  # type: ignore[arg-type]  # FastAPI exception handler typing accepts Exception but we use specific subclasses

    # Routes — all mounted unconditionally
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(plans.router)
    app.include_router(runs.router)
    app.include_router(evidence.router)
    app.include_router(artifacts.router)
    app.include_router(manual_binning.router)
    app.include_router(branches.router)
    app.include_router(comparisons.router)
    app.include_router(champion.router)
    app.include_router(exports.router)
    app.include_router(reports.router)
    app.include_router(node_types.router)

    return app


app = create_app()
