from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.evidence_repo import EvidenceRepository


def test_bulk_evidence_queries_preserve_order_and_grouping(store) -> None:
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )

    base = datetime(2026, 7, 5, tzinfo=UTC)
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )

    step_ids: list[str] = []
    run_step_ids: list[str] = []
    edge_ids: list[str] = []

    for idx in range(4):
        step_id = f"step-{idx}"
        run_step_id = f"rs-{idx}"
        step_ids.append(step_id)
        run_step_ids.append(run_step_id)
        started_at = (base + timedelta(seconds=idx)).isoformat().replace("+00:00", "Z")
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', ?, '', ?, ?)",
            (step_id, pv_id, f"hash-{idx}", idx, step_id),
        )
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (run_step_id, run_id, step_id, pv_id, started_at, started_at),
        )
        if idx == 0:
            continue
        edge_id = f"ee-{idx}"
        edge_ids.append(edge_id)
        store.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
            (
                edge_id,
                run_id,
                run_step_id,
                pv_id,
                step_id,
                step_ids[idx - 1],
                run_id,
                run_step_ids[idx - 1],
                "exact",
                f"label-{idx}",
                started_at,
            ),
        )
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"art-{idx}-z", "dataset", "zeta", f"/tmp/{idx}-z.csv", "ph-z", "lh-z", "text/csv", started_at),
        )
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"art-{idx}-a", "dataset", "alpha", f"/tmp/{idx}-a.csv", "ph-a", "lh-a", "text/csv", started_at),
        )
        store.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"ea-{idx}-z", edge_id, f"art-{idx}-z", "zeta", started_at),
        )
        store.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"ea-{idx}-a", edge_id, f"art-{idx}-a", "alpha", started_at),
        )

    repo = EvidenceRepository(store)
    edges = repo.get_edges_for_run(run_id)
    artifacts = repo.get_artifacts_for_run(run_id)

    assert [edge.run_step_id for edge in edges] == run_step_ids[1:]
    assert [edge.step_id for edge in edges] == step_ids[1:]

    grouped: dict[str, list[str]] = {}
    for artifact in artifacts:
        grouped.setdefault(artifact.evidence_edge_id, []).append(artifact.role)

    assert list(grouped) == edge_ids
    assert grouped[edge_ids[0]] == ["alpha", "zeta"]
    assert grouped[edge_ids[-1]] == ["alpha", "zeta"]
