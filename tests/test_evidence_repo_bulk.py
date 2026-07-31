from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge


def test_bulk_evidence_queries_preserve_order_and_grouping(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project
    now = utc_now_iso()

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)

        base = datetime(2026, 7, 5, tzinfo=UTC)
        run_id = str(uuid4())
        uow._conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', 'full_plan', ?, ?, ?)",
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
            uow._conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'test', '1', 'fit', '{}', ?, '', ?, ?)",
                (step_id, pv_id, f"hash-{idx}", idx, step_id),
            )
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                (run_step_id, run_id, step_id, pv_id, started_at, started_at),
            )
            if idx == 0:
                continue
            edge_id = f"ee-{idx}"
            edge_ids.append(edge_id)
            uow.evidence.insert_edge(EvidenceEdge(
                evidence_edge_id=edge_id,
                run_id=run_id,
                run_step_id=run_step_id,
                plan_version_id=pv_id,
                step_id=step_id,
                parent_step_id=step_ids[idx - 1],
                source_run_id=run_id,
                source_run_step_id=run_step_ids[idx - 1],
                policy="exact",
                source_label=f"label-{idx}",
                is_reused=False,
                is_stale=False,
                stale_reason=None,
                created_at=started_at,
            ))
            uow._conn.execute(
                "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, physical_hash, logical_hash, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"art-{idx}-z", "dataset", "zeta", f"/tmp/{idx}-z.csv", f"ph-{idx}-z", f"lh-{idx}-z", "text/csv", started_at),
            )
            uow._conn.execute(
                "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, physical_hash, logical_hash, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"art-{idx}-a", "dataset", "alpha", f"/tmp/{idx}-a.csv", f"ph-{idx}-a", f"lh-{idx}-a", "text/csv", started_at),
            )
            uow.evidence.insert_artifact(EvidenceArtifact(
                evidence_artifact_id=f"ea-{idx}-z", evidence_edge_id=edge_id,
                artifact_id=f"art-{idx}-z", role="zeta", created_at=started_at,
            ))
            uow.evidence.insert_artifact(EvidenceArtifact(
                evidence_artifact_id=f"ea-{idx}-a", evidence_edge_id=edge_id,
                artifact_id=f"art-{idx}-a", role="alpha", created_at=started_at,
            ))

        edges = uow.evidence.get_edges_for_run(run_id)
        grouped: dict[str, list[str]] = {}
        for edge, artifacts in uow.evidence.list_for_run_ordered(run_id):
            grouped.setdefault(edge.evidence_edge_id, []).extend(a.role for a in artifacts)

        assert [edge.run_step_id for edge in edges] == run_step_ids[1:]
        assert [edge.step_id for edge in edges] == step_ids[1:]

        assert list(grouped) == edge_ids
        assert sorted(grouped[edge_ids[0]]) == ["alpha", "zeta"]
        assert sorted(grouped[edge_ids[-1]]) == ["alpha", "zeta"]
