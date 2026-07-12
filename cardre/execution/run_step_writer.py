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

from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge

if TYPE_CHECKING:
    import sqlite3

    from cardre.domain.run import RunStep
    from cardre.domain.step import StepSpec
    from cardre.store.evidence_repo import EvidenceRepository


def write_run_step(
    conn: sqlite3.Connection,
    run_step: RunStep,
    spec: StepSpec,
    parent_run_steps: list[RunStep],
    input_artifact_ids: list[str],
    output_artifact_ids: list[str],
    input_artifact_ids_by_parent: dict[str, list[str]] | None,
    run_branch_id: str | None,
    evidence_repo: EvidenceRepository,
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
        ``StepSpec`` for the current step.  Used only for a defensive
        consistency check: ``assert run_step.step_id == spec.step_id``.
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
    evidence_repo:
        ``EvidenceRepository`` instance for transaction-scoped edge/artifact
        inserts (avoids duplicating the insert SQL owned by the repo).
    """
    if run_step.step_id != spec.step_id:
        raise ValueError(
            f"Step ID mismatch: run_step.step_id={run_step.step_id!r} != spec.step_id={spec.step_id!r}"
        )
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

    # 2. Write evidence_edges + evidence_artifacts via the repo
    for idx, parent_rs in enumerate(parent_run_steps):
        parent_aids = (
            input_artifact_ids_by_parent.get(parent_rs.step_id, input_artifact_ids)
            if input_artifact_ids_by_parent is not None
            else input_artifact_ids
        )
        if not parent_aids:
            continue
        edge = EvidenceEdge(
            evidence_edge_id=str(uuid.uuid4()),
            run_id=run_id,
            run_step_id=rs_id,
            plan_version_id=plan_version_id,
            step_id=step_id,
            parent_step_id=parent_rs.step_id,
            source_run_id=run_id,
            source_run_step_id=parent_rs.run_step_id,
            policy="exact",
            source_label=f"parent_{idx}",
            is_reused=False,
            is_stale=False,
            stale_reason=None,
            created_at=now,
        )
        evidence_repo.insert_edge(edge, conn)

        for aid in parent_aids:
            art = EvidenceArtifact(
                evidence_artifact_id=str(uuid.uuid4()),
                evidence_edge_id=edge.evidence_edge_id,
                artifact_id=aid,
                role="input",
                created_at=now,
            )
            evidence_repo.insert_artifact(art, conn)

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
    evidence_repo: EvidenceRepository,
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
    evidence_repo:
        ``EvidenceRepository`` instance for transaction-scoped edge/artifact
        inserts (avoids duplicating the insert SQL owned by the repo).
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

    # 2. Copy evidence edges via the repo (is_reused=True, preserve source provenance)
    for edge in edges:
        reused_edge = EvidenceEdge(
            evidence_edge_id=str(uuid.uuid4()),
            run_id=run_id,
            run_step_id=rs_id,
            plan_version_id=plan_version_id,
            step_id=step_id,
            parent_step_id=edge.parent_step_id,
            source_run_id=edge.source_run_id,
            source_run_step_id=edge.source_run_step_id,
            policy=edge.policy,
            source_label=edge.source_label,
            is_reused=True,
            is_stale=edge.is_stale,
            stale_reason=edge.stale_reason,
            created_at=now,
        )
        evidence_repo.insert_edge(reused_edge, conn)

        for art in (a for a in all_artifacts if a.evidence_edge_id == edge.evidence_edge_id):
            reused_art = EvidenceArtifact(
                evidence_artifact_id=str(uuid.uuid4()),
                evidence_edge_id=reused_edge.evidence_edge_id,
                artifact_id=art.artifact_id,
                role=art.role,
                created_at=now,
            )
            evidence_repo.insert_artifact(reused_art, conn)

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
