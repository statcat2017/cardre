"""SQLite connection management and transaction support for ProjectStore."""

from __future__ import annotations

import sqlite3
import types
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cardre._version import __version__
from cardre.domain.errors import SchemaVersionError

if TYPE_CHECKING:
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.run import RunStep
    from cardre.domain.step import StepSpec

from cardre.store.schema import (
    ALL_TABLES_SQL,
    V2_STORE_SCHEMA_FAMILY,
    V2_STORE_SCHEMA_VERSION,
)


class ProjectStore:
    """SQLite-backed metadata store for a single Cardre v2 project.

    The project root is a directory (e.g. ``example.cardre/``) containing:
      - cardre.sqlite
      - datasets/
      - artifacts/
      - exports/
      - logs/
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._db: sqlite3.Connection | None = None
        self._txn_depth = 0

    # ------------------------------------------------------------------
    # Initialization / open
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create a fresh project store with the v2 schema.

        Hard-errors if the SQLite file already exists (call ``open()`` instead).
        """
        db_path = self.root / "cardre.sqlite"
        if db_path.exists():
            raise SchemaVersionError(
                f"Store already exists at {db_path}. Use open() to connect."
            )
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (self.root / sub).mkdir(exist_ok=True)

        conn = self._connect()
        conn.executescript(ALL_TABLES_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_family', ?)",
            (V2_STORE_SCHEMA_FAMILY,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
            (str(V2_STORE_SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('created_by_cardre_version', ?)",
            (__version__,),
        )
        conn.commit()

    def open(self) -> None:
        """Open an existing store and verify version compatibility.

        Hard-errors on:
        - missing ``store_meta`` table
        - ``schema_family != cardre-v2``
        - ``schema_version != 100``
        """
        db_path = self.root / "cardre.sqlite"
        if not db_path.exists():
            raise SchemaVersionError(
                f"No store found at {db_path}."
            )
        conn = self._connect()
        self._check_schema_version(conn)

    def _ensure_store_meta_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

    def _check_schema_version(self, conn: sqlite3.Connection) -> None:
        self._ensure_store_meta_table(conn)
        try:
            rows = conn.execute(
                "SELECT key, value FROM store_meta WHERE key IN ('schema_family', 'schema_version')"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise SchemaVersionError(
                "Store schema metadata is missing or corrupt. "
                "Recreate this project with the current app."
            ) from exc

        meta = {row["key"]: row["value"] for row in rows}
        family = meta.get("schema_family")
        if family != V2_STORE_SCHEMA_FAMILY:
            raise SchemaVersionError(
                f"Store schema family {family!r} does not match app family "
                f"{V2_STORE_SCHEMA_FAMILY!r}. Recreate this project with the current app."
            )

        version_text = meta.get("schema_version")
        if version_text is None:
            raise SchemaVersionError(
                "Store schema version is missing. Recreate this project with the current app."
            )

        try:
            stored_version = int(version_text)
        except ValueError as exc:
            raise SchemaVersionError(
                f"Store schema version {version_text!r} is invalid. "
                "Recreate this project with the current app."
            ) from exc

        if stored_version != V2_STORE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Store schema version {stored_version} does not match app version "
                f"{V2_STORE_SCHEMA_VERSION}. Recreate this project with the current app."
            )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        db_path = self.root / "cardre.sqlite"
        conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        self._db = conn
        return conn

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> ProjectStore:
        self.open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: types.TracebackType | None) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------

    VALID_TXN_MODES = frozenset({"DEFERRED", "IMMEDIATE", "EXCLUSIVE"})

    @contextmanager
    def transaction(self, mode: str = "DEFERRED") -> Iterator[sqlite3.Connection]:
        """Context manager that yields a connection in an active transaction.

        Commits on success, rolls back on any exception.
        """
        if mode not in self.VALID_TXN_MODES:
            raise ValueError(
                f"Invalid transaction mode {mode!r}; "
                f"expected one of {sorted(self.VALID_TXN_MODES)}"
            )
        if self._txn_depth > 0:
            raise RuntimeError("nested transaction attempts are not supported")
        conn = self._connect()
        self._txn_depth += 1
        conn.execute(f"BEGIN {mode}")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._txn_depth -= 1

    # ------------------------------------------------------------------
    # Raw SQL helpers (for repos)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        return self._connect().execute(sql, params)

    def artifact_path(self, artifact: Any) -> Path:
        """Resolve a stored artifact reference to an on-disk path."""
        if isinstance(artifact, str):
            path = Path(artifact)
        elif isinstance(artifact, dict):
            path = Path(artifact["path"])
        else:
            path = Path(artifact.path)
        return path if path.is_absolute() else self.root / path

    def execute_script(self, sql: str) -> None:
        self._connect().executescript(sql)

    def executemany(self, sql: str, seq: Iterable[tuple[Any, ...] | dict[str, Any]]) -> sqlite3.Cursor:
        return self._connect().executemany(sql, seq)

    # ------------------------------------------------------------------
    # Convenience delegates over the repository classes
    # ------------------------------------------------------------------

    def get_branch(self, branch_id: str) -> dict[str, Any] | None:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self).get_branch(branch_id)

    def get_branch_step_map(self, branch_id: str, plan_version_id: str) -> list[dict[str, Any]]:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self).get_step_map(branch_id, plan_version_id)

    def get_plan_version(self, plan_version_id: str) -> dict[str, Any] | None:
        from cardre.store.plan_repo import PlanRepository
        return PlanRepository(self).get_version(plan_version_id)

    def get_plan_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        from cardre.store.plan_repo import PlanRepository
        return PlanRepository(self).get_version_steps(plan_version_id)

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        from cardre.store.plan_repo import PlanRepository
        return PlanRepository(self).get_plan(plan_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        from cardre.store.run_repo import RunRepository
        return RunRepository(self).get(run_id)

    def get_run_steps(self, run_id: str) -> list[RunStep]:
        from cardre.store.run_step_repo import RunStepRepository
        return RunStepRepository(self).get_for_run(run_id)

    def get_artifact(self, artifact_id: str) -> ArtifactRef | None:
        from cardre.store.artifact_repo import ArtifactRepository
        return ArtifactRepository(self).get(artifact_id)

    def get_latest_successful_run_id(self, plan_version_id: str, branch_id: str | None = None) -> str | None:
        from cardre.store.run_repo import RunRepository
        return RunRepository(self).get_latest_successful_id(plan_version_id, branch_id=branch_id)

    def get_latest_successful_run_id_for_plan(self, plan_id: str) -> str | None:
        from cardre.store.run_repo import RunRepository
        return RunRepository(self).get_latest_successful_id_for_plan(plan_id)

    def get_latest_successful_run_step(self, plan_version_id: str, step_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
        from cardre.store.run_repo import RunRepository
        return RunRepository(self).get_latest_successful_step(plan_version_id, step_id, branch_id=branch_id)

    def get_latest_successful_run_step_for_step(self, plan_version_id: str, step_id: str, branch_id: str | None = None) -> dict[str, Any] | None:
        return self.get_latest_successful_run_step(plan_version_id, step_id, branch_id=branch_id)

    def get_any_successful_run_id_for_plan(self, plan_id: str) -> str | None:
        return self.get_latest_successful_run_id_for_plan(plan_id)

    def get_plan_id_for_version(self, plan_version_id: str) -> str | None:
        from cardre.store.plan_repo import PlanRepository
        return PlanRepository(self).get_plan_id_for_version(plan_version_id)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        from cardre.store.project_repo import ProjectRepository
        return ProjectRepository(self).get(project_id)

    def get_comparison_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self).get_comparison_snapshot(snapshot_id)

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> dict[str, Any] | None:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self).get_champion_assignment(plan_id, champion_branch_id)

    def get_champion_assignment_by_branch(self, branch_id: str) -> dict[str, Any] | None:
        from cardre.store.branch_repo import BranchRepository
        return BranchRepository(self).get_champion_assignment_by_branch(branch_id)
