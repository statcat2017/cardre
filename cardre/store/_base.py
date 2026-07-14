"""Shared helpers for store repositories."""

from __future__ import annotations

from typing import Any


def _branch_filter(branch_id: str | None) -> tuple[str, list[Any]]:
    """Return SQL fragment and params for ``branch_id IS NULL`` / ``= ?``.

    Usage::

        clause, params = _branch_filter(branch_id)
        sql = f"SELECT ... WHERE ... {clause}"
        cursor.execute(sql, params)
    """
    if branch_id is None:
        return "AND branch_id IS NULL", []
    return "AND branch_id = ?", [branch_id]
