"""FastAPI sidecar entry point for the Cardre desktop shell.

Usage:
    python -m sidecar.main [port]
"""

from __future__ import annotations

import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cardre.services import PlanValidationError
from sidecar.routes import artifacts, datasets, health, plans, projects, runs

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


@app.exception_handler(PlanValidationError)
def plan_validation_error_handler(_request: Request, exc: PlanValidationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(plans.router)
app.include_router(runs.router)
app.include_router(artifacts.router)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8752
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
