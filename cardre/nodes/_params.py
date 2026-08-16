"""Typed node-params accessor.

Nodes receive params as a plain dict.  ``NodeParams`` is a drop-in
``Mapping`` that adds typed getters, so a node can parse each key once
instead of re-reading ``params.get(...)`` with casts in ``run()``,
``validate_params()`` and worker helpers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from cardre.domain.diagnostics import JsonDict


class NodeParams(Mapping[str, Any]):
    """Read-only view over a node's params with typed accessors.

    Dict-style access (``params["key"]``, ``params.get(...)``) still works,
    so existing call sites are unaffected.
    """

    def __init__(self, raw: JsonDict) -> None:
        self._raw = dict(raw)

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    def str(self, key: str, default: str = "") -> str:
        return str(self._raw.get(key, default))

    def int(self, key: str, default: int = 0) -> int:
        return int(self._raw.get(key, default))

    def float(self, key: str, default: float = 0.0) -> float:
        return float(self._raw.get(key, default))

    def bool(self, key: str, default: bool = False) -> bool:
        return bool(self._raw.get(key, default))

    def choice(self, key: str, options: tuple[str, ...], default: str) -> str:
        value = self._raw.get(key, default)
        if value not in options:
            raise ValueError(
                f"{key} must be one of {sorted(options)}, got {value!r}"
            )
        return value
