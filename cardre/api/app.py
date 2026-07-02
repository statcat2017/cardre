"""Full FastAPI application for Cardre v2 — Phase 4 surface.

All routers are mounted unconditionally. Governance-gated routes return
``GOVERNANCE_DISABLED`` (403) when ``CARDRE_GOVERNANCE=0`` (handled
via the ``require_governance`` dependency on those routers).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cardre.api.errors import CardreApiError, cardre_api_error_handler, cardre_error_handler
from cardre.domain.errors import CardreError
from cardre.api.routes import (
    health,
    projects,
    plans,
    runs,
    evidence,
    artifacts,
    manual_binning,
    branches,
    comparisons,
    champion,
    exports,
    reports,
    node_types,
)


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
