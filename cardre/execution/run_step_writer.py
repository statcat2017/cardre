"""Run-step writer — IMMEDIATE-transaction body for run_step + evidence + lineage.

Extracted from ``PlanExecutor._record_run_step`` and
``PlanExecutor._reuse_run_step`` to own all raw INSERT SQL for:

- ``run_steps``
- ``evidence_edges`` + ``evidence_artifacts``
- ``artifact_lineage``

Uses ``INSERT OR IGNORE`` for lineage (de-duplication).  Transaction level
is always ``IMMEDIATE`` (caller's responsibility — the writer does NOT
manage transactions itself).
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

    from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
    from cardre.domain.run import RunStep
    from cardre.domain.step import StepSpec


def write_run_step(
    conn: sqlite3.Connection,
    run_step: RunStep,
    spec: StepSpec,
    parent_run_steps: list[RunStep],
    input_artifact_ids: list[str],
    output_artifact_ids: list[str],
    input_artifact_ids_by_parent: dict[str, list[str]] | None,
    run_branch_id: str | None,
) -> None:
    """Write a run_step row, its evidence_edges, evidence_artifacts, and artifact_lineage.

    Parameters
    ----------
    conn:
        Active ``IMMEDIATE`` transaction connection.
    run_step:
        Fully-constructed ``RunStep`` domain object (IDs, timestamps,
        fingerprint, warnings, errors already set by caller).
    spec:
        ``StepSpec`` for the current step.
    parent_run_steps:
        Parent ``RunStep`` records (used to build evidence edges).
    input_artifact_ids:
        Artifact IDs consumed by this step.
    output_artifact_ids:
        Artifact IDs produced by this step.
    input_artifact_ids_by_parent:
        Per-parent input artifact mapping for precise evidence attribution.
        Falls back to ``input_artifact_ids`` when ``None`` or when a parent
        has no entry.
    run_branch_id:
        Branch ID for lineage rows (may be ``None``).
    """
    now = run_step.started_at or ""
    plan_version_id = run_step.plan_version_id
    run_id = run_step.run_id
    rs_id = run_step.run_step_id
    step_id = run_step.step_id

    # 1. Write run_step
    conn.execute(
        "INSERT INTO run_steps "
        "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
        " execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rs_id,
            run_id,
            step_id,
            plan_version_id,
            run_step.status.value,
            run_step.started_at,
            run_step.finished_at,
            json.dumps(run_step.execution_fingerprint),
            json.dumps(run_step.warnings),
            json.dumps(run_step.errors),
        ),
    )

    # 2. Write evidence_edges + evidence_artifacts
    for idx, parent_rs in enumerate(parent_run_steps):
        ee_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ee_id,
                run_id,
                rs_id,
                plan_version_id,
                step_id,
                parent_rs.step_id,
                run_id,
                parent_rs.run_step_id,
                "exact",
                f"parent_{idx}",
                0,  # is_reused
                0,  # is_stale
                None,  # stale_reason
                now,
            ),
        )

        # Evidence artifacts for this parent edge — only that parent's artifacts
        parent_aids = (
            input_artifact_ids_by_parent.get(parent_rs.step_id, input_artifact_ids)
            if input_artifact_ids_by_parent is not None
            else input_artifact_ids
        )
        for aid in parent_aids:
            conn.execute(
                "INSERT INTO evidence_artifacts "
                "(evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), ee_id, aid, "input", now),
            )

    # 3. Write artifact_lineage for inputs (INSERT OR IGNORE for de-dup)
    for aid in input_artifact_ids:
        conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, "
            " artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                run_id,
                rs_id,
                plan_version_id,
                step_id,
                run_branch_id,
                aid,
                "input",
                now,
            ),
        )

    # 4. Write artifact_lineage for outputs (INSERT OR IGNORE for de-dup)
    for aid in output_artifact_ids:
        conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, "
            " artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                run_id,
                rs_id,
                plan_version_id,
                step_id,
                run_branch_id,
                aid,
                "output",
                now,
            ),
        )


def write_reused_run_step(
    conn: sqlite3.Connection,
    copied_rs: RunStep,
    edges: list[EvidenceEdge],
    all_artifacts: list[EvidenceArtifact],
    lineage_rows: list[dict[str, Any]],
    run_branch_id: str | None,
) -> None:
    """Write a carried-forward (reused) run_step row, copied evidence, and lineage.

    Parameters
    ----------
    conn:
        Active ``IMMEDIATE`` transaction connection.
    copied_rs:
        ``RunStep`` with a new ID but the original status/warnings/errors
        and a fingerprint annotated with ``cardre_step_carried_forward`` keys.
    edges:
        Original ``EvidenceEdge`` objects from the source run step (will be
        copied with ``is_reused=True``).
    all_artifacts:
        Original ``EvidenceArtifact`` objects from the source run step (will
        be copied keyed by ``evidence_edge_id``).
    lineage_rows:
        ``artifact_lineage`` rows from the source run step (``INSERT OR IGNORE``
        into the new run).
    run_branch_id:
        Branch ID for lineage rows (may be ``None``).
    """
    now = copied_rs.started_at or ""
    plan_version_id = copied_rs.plan_version_id
    run_id = copied_rs.run_id
    rs_id = copied_rs.run_step_id
    step_id = copied_rs.step_id

    # 1. Write run_step
    conn.execute(
        "INSERT INTO run_steps "
        "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
        " execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rs_id,
            run_id,
            step_id,
            plan_version_id,
            copied_rs.status.value,
            copied_rs.started_at,
            copied_rs.finished_at,
            json.dumps(copied_rs.execution_fingerprint),
            json.dumps(copied_rs.warnings),
            json.dumps(copied_rs.errors),
        ),
    )

    # 2. Copy evidence edges (is_reused=True, preserve source provenance)
    for edge in edges:
        reused_ee_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reused_ee_id,
                run_id,
                rs_id,
                plan_version_id,
                step_id,
                edge.parent_step_id,
                edge.source_run_id,
                edge.source_run_step_id,
                edge.policy,
                edge.source_label,
                1,  # is_reused
                1 if edge.is_stale else 0,
                edge.stale_reason,
                now,
            ),
        )

        # Copy evidence artifacts for this edge
        for art in (a for a in all_artifacts if a.evidence_edge_id == edge.evidence_edge_id):
            conn.execute(
                "INSERT INTO evidence_artifacts "
                "(evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), reused_ee_id, art.artifact_id, art.role, now),
            )

    # 3. Copy lineage (INSERT OR IGNORE for de-dup)
    for lineage_row in lineage_rows:
        conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, "
            " artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                run_id,
                rs_id,
                plan_version_id,
                step_id,
                run_branch_id,
                lineage_row["artifact_id"],
                lineage_row["direction"],
                now,
            ),
        )


__all__ = [
    "write_run_step",
    "write_reused_run_step",
]
