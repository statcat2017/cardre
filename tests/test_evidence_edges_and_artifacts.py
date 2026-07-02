from __future__ import annotations

from cardre.store.evidence_repo import EvidenceRepository


def test_evidence_edges_and_artifacts_round_trip(store_with_evidence) -> None:
    store, _, _, pv_id, step_id = store_with_evidence
    repo = EvidenceRepository(store)

    edges = repo.get_edges_for_plan_step(pv_id, step_id)
    assert len(edges) == 1

    edge = edges[0]
    artifacts = repo.get_artifacts_for_edge(edge.evidence_edge_id)
    assert len(artifacts) == 1
    assert artifacts[0].evidence_edge_id == edge.evidence_edge_id
    assert artifacts[0].role == "bin_definition"

    run_step_artifacts = repo.get_artifacts_for_run_step(edge.run_step_id)
    assert [artifact.artifact_id for artifact in run_step_artifacts] == [
        artifacts[0].artifact_id,
    ]
