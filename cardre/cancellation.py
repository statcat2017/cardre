"""Cancellation token for live run cancellation."""

from __future__ import annotations

import threading


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            from cardre.errors import CancellationError
            raise CancellationError("Run was cancelled")


_tokens: dict[str, CancellationToken] = {}


def get_token(run_id: str) -> CancellationToken | None:
    return _tokens.get(run_id)


def register_token(run_id: str) -> CancellationToken:
    token = CancellationToken()
    _tokens[run_id] = token
    return token


def remove_token(run_id: str) -> None:
    _tokens.pop(run_id, None)


def cancel_run(run_id: str) -> None:
    token = get_token(run_id)
    if token is not None:
        token.cancel()
