"""Cardre v2 sidecar entrypoint — run the FastAPI app via uvicorn."""

from __future__ import annotations

import sys

import uvicorn

from cardre.api.app import app
from cardre.config import CardreConfig


def main(argv: list[str] | None = None) -> None:
    args = sys.argv if argv is None else argv
    config = CardreConfig.from_env()
    port = config.api_port
    if len(args) > 1:
        try:
            port = int(args[1])
        except ValueError as exc:
            raise SystemExit(f"Invalid port argument: {args[1]!r}") from exc
    uvicorn.run(
        app,
        host=config.api_host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
