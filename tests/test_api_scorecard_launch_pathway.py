"""Full scorecard launch pathway acceptance test, driven through the project-scoped API.

This is the v2 Phase 5 DoD acceptance test: create project via POST /projects,
create plan via API, seed a committed plan version with all scorecard nodes
via PlanRepository, run synchronously through POST /projects/{project_id}/runs,
then verify steps, evidence, and store-level integrity.
"""
from __future__ import annotations

import csv
from pathlib import Path

from cardre.domain.step import StepSpec


def _write_input_csv(path: Path) -> Path:
    """Generate a small synthetic binary-classification dataset."""
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


# The 15-node scorecard DAG.  Topological order is computed at plan-build
# time by PlanRepository.create_version (which calls validate_topology).
# Node 5 (define-modelling-metadata) is required because fine-classing and
# many downstream nodes consume MODELLING_METADATA evidence, which only
# define-modelling-metadata produces.
#
# Parent references follow the rule: a step's parents MUST collectively
# provide every artifact role and evidence kind that the step's run()
# method actually consumes.
SCORECARD_STEPS = [
    # (step_id, node_type, parents, params)
    ("import-data",            "cardre.import_dataset",             [],
     {"source_path": "PLACEHOLDER"}),
    ("profile",                "cardre.profile_dataset",            ["import-data"],
     {}),
    ("validate-target",        "cardre.validate_binary_target",     ["import-data"],
     {}),
    ("split",                  "cardre.split_train_test_oot",       ["import-data"],
     {}),
    ("define-metadata",        "cardre.define_modelling_metadata",  ["import-data", "split"],
     {"target_column": "credit_risk_class", "good_values": ["good"], "bad_values": ["bad"]}),
    ("fine-classing",          "cardre.fine_classing",              ["split", "define-metadata"],
     {}),
    ("calculate-woe-iv",       "cardre.calculate_woe_iv",           ["split", "fine-classing", "define-metadata"],
     {}),
    ("variable-selection",     "cardre.variable_selection",         ["calculate-woe-iv"],
     {}),
    ("manual-binning",         "cardre.manual_binning",             ["fine-classing", "variable-selection"],
     {"accept_automated": True}),
    ("woe-transform",          "cardre.woe_transform_train",        ["split", "manual-binning",
                                                                     "calculate-woe-iv",
                                                                     "define-metadata",
                                                                     "variable-selection"],
     {}),
    ("logistic",               "cardre.logistic_regression",        ["woe-transform", "define-metadata",
                                                                     "variable-selection"],
     {}),
    ("score-scaling",          "cardre.score_scaling",              ["logistic", "fine-classing",
                                                                     "calculate-woe-iv"],
     {}),
    ("validation-metrics",     "cardre.validation_metrics",         ["split", "score-scaling",
                                                                     "define-metadata",
                                                                     "calculate-woe-iv"],
     {"fail_on_missing_score": False, "require_test": False, "require_oot": False}),
    ("cutoff-analysis",        "cardre.cutoff_analysis",            ["split", "validation-metrics"],
     {}),
    ("export",                 "cardre.technical_manifest_export",  ["cutoff-analysis",
                                                                     "validation-metrics"],
     {}),
]

EXPECTED_STEP_COUNT = len(SCORECARD_STEPS)


def _build_steps(csv_path: Path) -> list[StepSpec]:
    """Build StepSpec list from SCORECARD_STEPS, filling in source_path."""
    result = []
    for position, (step_id, node_type, parents, params) in enumerate(SCORECARD_STEPS):
        p = dict(params)
        if step_id == "import-data":
            p["source_path"] = str(csv_path)
        result.append(StepSpec(
            step_id=step_id,
            node_type=node_type,
            node_version="1",
            category="transform",
            params=p,
            params_hash=f"hash-{step_id}",
            parent_step_ids=list(parents),
            position=position,
        ))
    return result


def test_full_scorecard_launch_pathway_via_api(raw_project_path, api_client, tmp_path):
    """Full 15-node scorecard pathway through the project-scoped API.

    Phases:
      1. POST /projects (fresh store bootstrap)
      2. POST .../plans
      3. Seed committed plan version via PlanRepository (no add-step API route)
      4. POST .../runs with sync=True, force=True
      5. GET .../runs/{id}/steps — all 15 succeeded
      6. GET .../runs/{id}/evidence — ≥ 14 edges (every non-root step)
      7. Store-level integrity: every non-root run_step has evidence_edges,
         and every evidence_edge has at least one evidence_artifact.
    """
    # 1. Create project via POST /projects
    project_dir = tmp_path / "scorecard.cardre"
    resp = api_client.post("/projects", json={"name": "Scorecard", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]
    headers = {"X-Project-Path": str(project_dir)}

    # 2. Create input CSV
    csv_path = _write_input_csv(tmp_path / "input.csv")

    # 3. Create plan via API
    resp = api_client.post(
        f"/projects/{project_id}/plans",
        headers=headers,
        json={"name": "Scorecard Plan"},
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    # 4. Seed a committed plan version with the scorecard graph.
    #    There is no "add step" API route, so we open the store directly
    #    and use PlanRepository — acceptable for test setup.
    from cardre.store.db import ProjectStore
    from cardre.store.plan_repo import PlanRepository
    store = ProjectStore(project_dir)
    store.open()
    try:
        steps = _build_steps(csv_path)
        plan_version_id = PlanRepository(store).create_version(
            plan_id, steps=steps, is_committed=True,
        )
    finally:
        store.close()

    # 5. POST /projects/{project_id}/runs — create and execute synchronously
    resp = api_client.post(
        f"/projects/{project_id}/runs",
        headers=headers,
        json={"plan_version_id": plan_version_id, "sync": True, "force": True},
    )
    assert resp.status_code == 201, resp.text
    run_data = resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

    # 6. GET /projects/{project_id}/runs/{run_id}/steps — verify all succeeded
    resp = api_client.get(
        f"/projects/{project_id}/runs/{run_id}/steps",
        headers=headers,
    )
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == EXPECTED_STEP_COUNT
    for s in steps:
        assert s["status"] == "succeeded", f"Step {s['step_id']} failed: {s}"

    # 7. GET /projects/{project_id}/runs/{run_id}/evidence — verify edges
    resp = api_client.get(
        f"/projects/{project_id}/runs/{run_id}/evidence",
        headers=headers,
    )
    assert resp.status_code == 200
    evidence = resp.json()
    # import-data is root (no parents) => no edge; all others have >= 1 edge
    non_root = EXPECTED_STEP_COUNT - 1
    assert len(evidence) >= non_root, (
        f"Expected >= {non_root} evidence edges, got {len(evidence)}"
    )

    # 8. Open store directly for integrity assertions (Phase 5 abort criterion).
    store = ProjectStore(project_dir)
    store.open()
    try:
        # Every non-root run step has at least one evidence_edges row
        run_steps = store.execute(
            "SELECT step_id FROM run_steps WHERE run_id = ? AND step_id != 'import-data'",
            (run_id,),
        ).fetchall()
        for rs in run_steps:
            edges = store.execute(
                "SELECT COUNT(*) as cnt FROM evidence_edges WHERE run_id = ? AND step_id = ?",
                (run_id, rs["step_id"]),
            ).fetchone()
            assert edges["cnt"] >= 1, f"Step {rs['step_id']} has no evidence edges"

        # Every evidence_edge has at least one evidence_artifact
        empty_edges = store.execute(
            """SELECT ee.evidence_edge_id, ee.step_id
               FROM evidence_edges ee
               LEFT JOIN evidence_artifacts ea ON ea.evidence_edge_id = ee.evidence_edge_id
               WHERE ee.run_id = ? AND ea.evidence_artifact_id IS NULL""",
            (run_id,),
        ).fetchall()
        assert not empty_edges, (
            f"Edges with no artifacts: {[(e['step_id'], e['evidence_edge_id']) for e in empty_edges]}"
        )
    finally:
        store.close()
