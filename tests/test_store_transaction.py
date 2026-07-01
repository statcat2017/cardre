"""Phase 1 — store transaction rollback on error."""

import pytest

from cardre.domain.errors import SchemaVersionError
from cardre.store.db import ProjectStore


def test_transaction_rollback_on_error(tmp_path):
    """Changes inside a transaction are rolled back on exception."""
    root = tmp_path / "txn.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    project_id = "test_proj"
    now = "2025-01-01T00:00:00"

    # Insert a project inside a transaction, then raise
    with pytest.raises(ValueError, match="rollback"):
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                (project_id, "Test", now, "0.2.0"),
            )
            raise ValueError("force rollback")

    # Project should NOT exist
    row = store.execute(
        "SELECT * FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()
    assert row is None, "Transaction was not rolled back"


def test_transaction_commit_success(tmp_path):
    """Changes inside a transaction are committed on success."""
    root = tmp_path / "txn2.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    project_id = "commit_test"
    now = "2025-01-01T00:00:00"

    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Committed", now, "0.2.0"),
        )

    row = store.execute(
        "SELECT * FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()
    assert row is not None
    assert row["name"] == "Committed"


def test_transaction_invalid_mode(tmp_path):
    """Invalid transaction mode raises ValueError."""
    root = tmp_path / "txn3.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    with pytest.raises(ValueError, match="Invalid transaction mode"):
        with store.transaction(mode="INVALID"):
            pass


def test_transaction_rollback_on_schema_error(tmp_path):
    """Even SchemaVersionError causes rollback."""
    root = tmp_path / "txn4.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    project_id = "schema_err"
    now = "2025-01-01T00:00:00"

    with pytest.raises(SchemaVersionError):
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                (project_id, "Fail", now, "0.2.0"),
            )
            raise SchemaVersionError("simulated schema error")

    row = store.execute(
        "SELECT * FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()
    assert row is None


def test_nested_transaction_sanity(tmp_path):
    """Nested transactions (via savepoint) work as expected."""
    root = tmp_path / "txn5.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    # Outer transaction succeeds
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            ("outer", "Outer", "now", "0.2.0"),
        )
        # Simulate savepoint via execute
        conn.execute("SAVEPOINT sp1")
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            ("inner", "Inner", "now", "0.2.0"),
        )
        conn.execute("RELEASE SAVEPOINT sp1")

    assert store.execute("SELECT * FROM projects WHERE project_id = 'outer'").fetchone() is not None
    assert store.execute("SELECT * FROM projects WHERE project_id = 'inner'").fetchone() is not None
