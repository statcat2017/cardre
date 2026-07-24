"""SQLite evidence repository — query object for evidence_edges and evidence_artifacts."""

from __future__ import annotations

from typing import Any

from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge


class EvidenceRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert_edge(self, edge: EvidenceEdge) -> None:
        self._conn.execute(
            "INSERT INTO evidence_edges (evidence_edge_id, run_id, run_step_id, plan_version_id, "
            "step_id, parent_step_id, source_run_id, source_run_step_id, "
            "policy, source_label, is_reused, is_stale, stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (edge.evidence_edge_id, edge.run_id, edge.run_step_id, edge.plan_version_id,
             edge.step_id, edge.parent_step_id, edge.source_run_id, edge.source_run_step_id,
             edge.policy, edge.source_label, int(edge.is_reused), int(edge.is_stale),
             edge.stale_reason, edge.created_at),
        )

    def insert_artifact(self, artifact: EvidenceArtifact) -> None:
        self._conn.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (artifact.evidence_artifact_id, artifact.evidence_edge_id, artifact.artifact_id, artifact.role, artifact.created_at),
        )

    def get_edges_for_run_step(self, run_step_id: str) -> list[EvidenceEdge]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_edges WHERE run_step_id = ?", (run_step_id,)
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_run(self, run_id: str) -> list[EvidenceEdge]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_edges WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_plan_step(self, plan_version_id: str, step_id: str) -> list[EvidenceEdge]:
        rows = self._conn.execute(
            "SELECT e.* FROM evidence_edges e "
            "JOIN run_steps rs ON e.source_run_step_id = rs.run_step_id "
            "WHERE e.plan_version_id = ? AND e.step_id = ? AND rs.status = 'succeeded'",
            (plan_version_id, step_id),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_for_plan_step_branch(self, plan_version_id: str, step_id: str, branch_id: str | None) -> list[EvidenceEdge]:
        clause = "AND r.branch_id = ?" if branch_id is not None else "AND r.branch_id IS NULL"
        params: list[str] = [plan_version_id, step_id]
        if branch_id is not None:
            params.append(branch_id)
        rows = self._conn.execute(
            f"SELECT e.* FROM evidence_edges e "
            f"JOIN run_steps rs ON e.source_run_step_id = rs.run_step_id "
            f"JOIN runs r ON e.run_id = r.run_id "
            f"WHERE e.plan_version_id = ? AND e.step_id = ? AND rs.status = 'succeeded' "
            f"AND r.status = 'succeeded' AND e.is_stale = 0 {clause} "
            f"ORDER BY r.finished_at DESC, e.created_at DESC, e.evidence_edge_id DESC",
            params,
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edge_for_child_parent(self, run_step_id: str, parent_step_id: str) -> EvidenceEdge | None:
        row = self._conn.execute(
            "SELECT * FROM evidence_edges WHERE run_step_id = ? AND parent_step_id = ?",
            (run_step_id, parent_step_id),
        ).fetchone()
        return self._row_to_edge(row) if row is not None else None

    def get_artifacts_for_edge(self, evidence_edge_id: str) -> list[EvidenceArtifact]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_edge_id = ?", (evidence_edge_id,)
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def get_artifacts_for_run_step(self, run_step_id: str) -> list[EvidenceArtifact]:
        rows = self._conn.execute(
            "SELECT ea.* FROM evidence_artifacts ea "
            "JOIN evidence_edges ee ON ea.evidence_edge_id = ee.evidence_edge_id "
            "WHERE ee.run_step_id = ?", (run_step_id,)
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def list_for_run_ordered(self, run_id: str) -> list[tuple[EvidenceEdge, list[EvidenceArtifact]]]:
        edges = self.get_edges_for_run(run_id)
        result: list[tuple[EvidenceEdge, list[EvidenceArtifact]]] = []
        for edge in edges:
            artifacts = self.get_artifacts_for_edge(edge.evidence_edge_id)
            result.append((edge, artifacts))
        return result

    @staticmethod
    def _row_to_edge(r: Any) -> EvidenceEdge:
        return EvidenceEdge(
            evidence_edge_id=r["evidence_edge_id"], run_id=r["run_id"],
            run_step_id=r["run_step_id"], plan_version_id=r["plan_version_id"],
            step_id=r["step_id"], parent_step_id=r["parent_step_id"],
            source_run_id=r["source_run_id"], source_run_step_id=r["source_run_step_id"],
            policy=r["policy"], source_label=r["source_label"],
            is_reused=bool(r["is_reused"]), is_stale=bool(r["is_stale"]),
            stale_reason=r["stale_reason"] if "stale_reason" in r.keys() else None,  # noqa: F841, SIM118
            created_at=r["created_at"],
        )

    @staticmethod
    def _row_to_artifact(r: Any) -> EvidenceArtifact:
        return EvidenceArtifact(
            evidence_artifact_id=r["evidence_artifact_id"],
            evidence_edge_id=r["evidence_edge_id"],
            artifact_id=r["artifact_id"], role=r["role"], created_at=r["created_at"],
        )
