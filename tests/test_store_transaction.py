from __future__ import annotations

import pytest

from cardre.domain.diagnostics import utc_now_iso


def test_transaction_rolls_back_on_error(store) -> None:
    project_id = "project-rollback"

    with pytest.raises(RuntimeError):
        with store.transaction():
            store.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                (project_id, "Project", utc_now_iso(), "0.2.0"),
            )
            raise RuntimeError("boom")

    row = store.execute(
        "SELECT project_id FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    assert row is None
