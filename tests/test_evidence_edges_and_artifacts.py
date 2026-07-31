from __future__ import annotations


def test_evidence_edges_and_artifacts_round_trip(store_with_evidence) -> None:
    project_id, uow_factory, _, pv_id, mb_step_id = store_with_evidence

    with uow_factory.for_project(project_id) as uow:
        edges = uow.evidence.get_edges_for_plan_step(pv_id, mb_step_id)
        assert len(edges) == 1

        edge = edges[0]
        artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
        assert len(artifacts) == 1
        assert artifacts[0].evidence_edge_id == edge.evidence_edge_id
        assert artifacts[0].role == "definition"

        run_step_artifacts = uow.evidence.get_artifacts_for_run_step(edge.run_step_id)
        assert [artifact.artifact_id for artifact in run_step_artifacts] == [
            artifacts[0].artifact_id,
        ]
