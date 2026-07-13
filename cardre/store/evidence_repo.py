"""Evidence repository — CRUD for evidence_edges and evidence_artifacts."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.store._base import _branch_filter

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class EvidenceRepository:
    """Repository for the two-level evidence model."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _exec(self, conn: sqlite3.Connection | None, sql: str, params: tuple[Any, ...]) -> None:
        if conn is not None:
            conn.execute(sql, params)
        else:
            self._store.execute(sql, params)

    def insert_edge(self, edge: EvidenceEdge, conn: sqlite3.Connection | None = None) -> str:
        self._exec(conn,
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge.evidence_edge_id,
                edge.run_id,
                edge.run_step_id,
                edge.plan_version_id,
                edge.step_id,
                edge.parent_step_id,
                edge.source_run_id,
                edge.source_run_step_id,
                edge.policy,
                edge.source_label,
                1 if edge.is_reused else 0,
                1 if edge.is_stale else 0,
                edge.stale_reason,
                edge.created_at or utc_now_iso(),
            ),
        )
        return edge.evidence_edge_id

    def insert_artifact(self, artifact: EvidenceArtifact, conn: sqlite3.Connection | None = None) -> str:
        self._exec(conn,
            "INSERT INTO evidence_artifacts "
            "(evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                artifact.evidence_artifact_id,
                artifact.evidence_edge_id,
                artifact.artifact_id,
                artifact.role,
                artifact.created_at or utc_now_iso(),
            ),
        )
        return artifact.evidence_artifact_id

    def get_edges_for_run_step(self, run_step_id: str) -> list[EvidenceEdge]:
        rows = self._store.execute(
            "SELECT * FROM evidence_edges WHERE run_step_id = ? ORDER BY created_at",
            (run_step_id,),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_run(self, run_id: str) -> list[EvidenceEdge]:
        rows = self._store.execute(
            "SELECT * FROM evidence_edges WHERE run_id = ? "
            "ORDER BY created_at, evidence_edge_id",
            (run_id,),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_plan_step(
        self,
        plan_version_id: str,
        step_id: str,
    ) -> list[EvidenceEdge]:
        rows = self._store.execute(
            "SELECT * FROM evidence_edges WHERE plan_version_id = ? AND step_id = ? ORDER BY created_at",
            (plan_version_id, step_id),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_plan_step_branch(
        self,
        plan_version_id: str,
        step_id: str,
        branch_id: str | None,
    ) -> list[EvidenceEdge]:
        """Edges for a plan step, filtered by the run's branch_id and
        successful run/run-step status.

        ``branch_id=None`` matches runs where ``branch_id IS NULL`` (the
        full-plan / baseline runs).  Only edges from succeeded runs whose
        target run-step also succeeded are returned — failed/cancelled
        run-steps are excluded even if a newer edge exists.
        """
        clause, params = _branch_filter(branch_id)
        sql = (
            "SELECT ee.* FROM evidence_edges ee "
            "JOIN runs r ON ee.run_id = r.run_id "
            "JOIN run_steps rs ON ee.run_step_id = rs.run_step_id "
            "WHERE ee.plan_version_id = ? AND ee.step_id = ? "
            "AND r.status = 'succeeded' AND rs.status = 'succeeded'"
        )
        params = [plan_version_id, step_id] + params
        sql += f" {clause} ORDER BY ee.created_at, ee.evidence_edge_id"
        rows = self._store.execute(sql, tuple(params)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edge_for_child_parent(
        self,
        plan_version_id: str,
        child_step_id: str,
        parent_step_id: str,
    ) -> EvidenceEdge | None:
        row = self._store.execute(
            "SELECT * FROM evidence_edges WHERE plan_version_id = ? AND step_id = ? AND parent_step_id = ? ORDER BY created_at DESC LIMIT 1",
            (plan_version_id, child_step_id, parent_step_id),
        ).fetchone()
        return self._row_to_edge(row) if row else None

    def get_artifacts_for_edge(self, evidence_edge_id: str) -> list[EvidenceArtifact]:
        rows = self._store.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_edge_id = ? ORDER BY role",
            (evidence_edge_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def get_artifacts_for_run_step(self, run_step_id: str) -> list[EvidenceArtifact]:
        rows = self._store.execute(
            "SELECT ea.* FROM evidence_artifacts ea "
            "JOIN evidence_edges ee ON ea.evidence_edge_id = ee.evidence_edge_id "
            "WHERE ee.run_step_id = ? ORDER BY ea.role",
            (run_step_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def get_artifacts_for_run(self, run_id: str) -> list[EvidenceArtifact]:
        rows = self._store.execute(
            "SELECT ea.* FROM evidence_artifacts ea "
            "JOIN evidence_edges ee ON ea.evidence_edge_id = ee.evidence_edge_id "
            "WHERE ee.run_id = ? "
            "ORDER BY ee.evidence_edge_id, ea.role, ea.created_at, ea.evidence_artifact_id",
            (run_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def list_for_run_ordered(self, run_id: str) -> list[tuple[EvidenceEdge, list[EvidenceArtifact]]]:
        """Return evidence edges + artifacts ordered by run_step_id.

        Groups artifacts by edge and orders edges by the run's step order.
        """
        from cardre.store.run_step_repo import RunStepRepository

        rs_repo = RunStepRepository(self._store)
        run_step_ids = [rs.run_step_id for rs in rs_repo.get_for_run(run_id)]

        edges = self.get_edges_for_run(run_id)
        artifacts = self.get_artifacts_for_run(run_id)

        artifacts_by_edge_id: dict[str, list[EvidenceArtifact]] = {}
        for artifact in artifacts:
            artifacts_by_edge_id.setdefault(artifact.evidence_edge_id, []).append(artifact)

        edges_by_step: dict[str, list[EvidenceEdge]] = {}
        for edge in edges:
            edges_by_step.setdefault(edge.run_step_id, []).append(edge)

        result: list[tuple[EvidenceEdge, list[EvidenceArtifact]]] = []
        for run_step_id in run_step_ids:
            for edge in edges_by_step.get(run_step_id, []):
                result.append((edge, artifacts_by_edge_id.get(edge.evidence_edge_id, [])))
        return result

    @staticmethod
    def _row_to_edge(row: dict[str, Any]) -> EvidenceEdge:
        d = dict(row)
        return EvidenceEdge(
            evidence_edge_id=d["evidence_edge_id"],
            run_id=d["run_id"],
            run_step_id=d["run_step_id"],
            plan_version_id=d["plan_version_id"],
            step_id=d["step_id"],
            parent_step_id=d["parent_step_id"],
            source_run_id=d["source_run_id"],
            source_run_step_id=d["source_run_step_id"],
            policy=d["policy"],
            source_label=d["source_label"],
            is_reused=bool(d["is_reused"]),
            is_stale=bool(d["is_stale"]),
            stale_reason=d.get("stale_reason"),
            created_at=d["created_at"],
        )

    @staticmethod
    def _row_to_artifact(row: dict[str, Any]) -> EvidenceArtifact:
        return EvidenceArtifact(
            evidence_artifact_id=row["evidence_artifact_id"],
            evidence_edge_id=row["evidence_edge_id"],
            artifact_id=row["artifact_id"],
            role=row["role"],
            created_at=row["created_at"],
        )
