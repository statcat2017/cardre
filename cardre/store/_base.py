"""Shared repository base class and helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class Repository:
    """Minimal base for store repositories.

    Subclasses set ``table`` and ``pk``. Override ``_row_to_obj``
    where they hydrate typed domain objects. Override ``get``/``list``
    where SQL differs (joins, custom WHERE clauses).
    """

    table: str
    pk: str

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def get(self, id: str) -> dict[str, Any] | None:
        row = self._store.execute(
            f"SELECT * FROM {self.table} WHERE {self.pk} = ?", (id,)
        ).fetchone()
        return None if row is None else self._row_to_obj(row)

    def list(self, *, order_by: str | None = None) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {self.table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        rows = self._store.execute(sql).fetchall()
        return [self._row_to_obj(r) for r in rows]

    def _row_to_obj(self, row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)


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
