"""FastAPI sidecar entry point for the Cardre desktop shell.

Usage:
    python -m sidecar.main [port]
"""

from __future__ import annotations

import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from cardre.errors import CardreError
from sidecar.error_handling import (
    RequestContextMiddleware,
    cardre_error_handler,
    http_exception_handler,
    request_validation_error_handler,
    generic_exception_handler,
)
from sidecar.routes import artifacts, binning, branches, champion, comparisons, datasets, evidence, exports, health, method_summary, node_types, plans, projects, reports, runs

app = FastAPI(title="cardre-api", version="0.1.0")

TAURI_DEV_ORIGINS = [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "tauri://localhost",
    "https://tauri.localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=TAURI_DEV_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestContextMiddleware)

app.add_exception_handler(CardreError, cardre_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(health.router)
app.include_router(binning.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(evidence.router)
app.include_router(plans.router)
app.include_router(runs.router)
app.include_router(exports.router)
app.include_router(artifacts.router)
app.include_router(reports.router)
app.include_router(node_types.router)
app.include_router(method_summary.router)

# Governance features are gated behind CARDRE_GOVERNANCE=1
import os
if os.environ.get("CARDRE_GOVERNANCE", "0") in ("1", "true", "True"):
    app.include_router(branches.router)
    app.include_router(comparisons.router)
    app.include_router(champion.router)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8752
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
