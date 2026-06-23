"""FastAPI sidecar entry point for the Cardre desktop shell.

Usage:
    python -m sidecar.main [port]
"""

from __future__ import annotations

import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cardre.services import PlanValidationError
from cardre.services.project_registry import ProjectNotFoundError, ProjectPathMissingError
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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    print(f"[sidecar] {request.method} {request.url.path} {response.status_code} ({elapsed:.3f}s)", flush=True)
    return response


@app.exception_handler(PlanValidationError)
def plan_validation_error_handler(_request: Request, exc: PlanValidationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ProjectNotFoundError)
def project_not_found_handler(_request: Request, exc: ProjectNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": {"code": "PROJECT_NOT_FOUND", "message": str(exc)}})


@app.exception_handler(ProjectPathMissingError)
def project_path_missing_handler(_request: Request, exc: ProjectPathMissingError) -> JSONResponse:
    return JSONResponse(status_code=410, content={"detail": {"code": "PROJECT_PATH_MISSING", "message": str(exc)}})


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
