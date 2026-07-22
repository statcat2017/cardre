"""Cardre v2 sidecar entrypoint — run the FastAPI app via uvicorn."""

from __future__ import annotations

import uvicorn

from cardre.bootstrap.build_app import build_app


def main() -> None:
    app, _shutdown = build_app()
    settings = app.state.container.settings
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
