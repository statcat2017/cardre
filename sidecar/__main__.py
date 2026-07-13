"""Cardre v2 sidecar entrypoint — run the FastAPI app via uvicorn."""

from __future__ import annotations

import uvicorn

from cardre.api.app import app
from cardre.config import CardreConfig


def main() -> None:
    config = CardreConfig.from_env()
    uvicorn.run(
        app,
        host=config.api_host,
        port=config.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
