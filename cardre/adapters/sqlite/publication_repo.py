"""SQLite publication outbox repository.

Records filesystem publications (artifacts and manifests) that must be
finalized only after the DB mutation they belong to is durable. Rows are
written in the same transaction as the mutation; ``mark_published`` /
``mark_failed`` are called after the filesystem side effect, and
reconciliation retries ``pending``/``failed`` rows on startup.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.domain.diagnostics import JsonDict, utc_now_iso


def _row_to_publication(r: Any) -> dict[str, Any]:
    manifest_payload: JsonDict | None = None
    if r["manifest_payload_json"]:
        manifest_payload = json.loads(r["manifest_payload_json"])
    return {
        "outbox_id": r["outbox_id"],
        "run_id": r["run_id"],
        "plan_version_id": r["plan_version_id"],
        "run_step_id": r["run_step_id"],
        "kind": r["kind"],
        "artifact_id": r["artifact_id"],
        "physical_hash": r["physical_hash"],
        "storage_key": r["storage_key"],
        "staging_source": r["staging_source"],
        "manifest_payload": manifest_payload,
        "manifest_hash": r["manifest_hash"],
        "state": r["state"],
        "error": r["error"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


class PublicationRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def enqueue_artifact(
        self,
        run_id: str,
        plan_version_id: str,
        run_step_id: str,
        artifact_id: str,
        physical_hash: str,
        storage_key: str,
        staging_source: str,
    ) -> str:
        now = utc_now_iso()
        outbox_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO publication_outbox "
            "(outbox_id, run_id, plan_version_id, run_step_id, kind, artifact_id, "
            " physical_hash, storage_key, staging_source, state, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'artifact', ?, ?, ?, ?, 'pending', '', ?, ?)",
            (outbox_id, run_id or None, plan_version_id, run_step_id, artifact_id,
             physical_hash, storage_key, staging_source, now, now),
        )
        return outbox_id

    def enqueue_manifest(
        self,
        run_id: str,
        plan_version_id: str,
        payload: JsonDict,
        manifest_hash: str,
    ) -> str:
        now = utc_now_iso()
        outbox_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO publication_outbox "
            "(outbox_id, run_id, plan_version_id, kind, manifest_payload_json, "
            " manifest_hash, state, error, created_at, updated_at) "
            "VALUES (?, ?, ?, 'manifest', ?, ?, 'pending', '', ?, ?)",
            (outbox_id, run_id, plan_version_id,
             json.dumps(payload, sort_keys=True), manifest_hash, now, now),
        )
        return outbox_id

    def mark_published(self, outbox_id: str) -> None:
        self._conn.execute(
            "UPDATE publication_outbox SET state = 'published', updated_at = ? "
            "WHERE outbox_id = ?",
            (utc_now_iso(), outbox_id),
        )

    def mark_failed(self, outbox_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE publication_outbox SET state = 'failed', error = ?, updated_at = ? "
            "WHERE outbox_id = ?",
            (error, utc_now_iso(), outbox_id),
        )

    def get(self, outbox_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM publication_outbox WHERE outbox_id = ?", (outbox_id,)
        ).fetchone()
        return None if row is None else _row_to_publication(row)

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM publication_outbox WHERE run_id = ? "
            "ORDER BY created_at", (run_id,)
        ).fetchall()
        return [_row_to_publication(r) for r in rows]

    def list_pending(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Return unfinished publications: ``pending`` (finalize not yet run or
        crashed mid-way) and ``failed`` (previous finalize errored)."""
        rows = self._conn.execute(
            "SELECT * FROM publication_outbox WHERE state IN ('pending','failed') "
            "ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_publication(r) for r in rows]


__all__ = ["PublicationRepo"]
