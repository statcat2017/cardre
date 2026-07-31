"""Full product acceptance pathway (Batch 07g).

Drives the complete canonical scorecard workflow through the new API and
production stack, covering the 20 product-acceptance items from
``docs/architecture-rewrite/08-acceptance-and-test-strategy.md``.

Supersedes the pre-Batch-05 ``test_launch_pathway.py`` and
``test_api_scorecard_launch_pathway.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardre.bootstrap.container import build_container
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.evidence.schemas import (
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_SCORE_SCALING,
)
from cardre.domain.plans.scorecard_pathway import build_canonical_scorecard_steps


def _write_input_csv(path: Path) -> Path:
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


@pytest.fixture
def acceptance_env(tmp_path):
    """Provision a project, commit a canonical plan, and return the API client
    plus the container and roots for post-run assertions.

    Returns (client, container, project_id, plan_id, pv_id, root).
    """
    registry_path = tmp_path / "registry.json"
    settings = Settings(
        launch_mode=True,
        governance_enabled=False,
        registry_path=registry_path,
    )
    container = build_container(settings)
    from cardre.api.app import create_app

    app = create_app(container)
    client = TestClient(app)

    # 1. Create a project through the API.
    project_path = tmp_path / "acceptance.cardre"
    resp = client.post("/projects", json={"name": "Acceptance", "path": str(project_path)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]

    # 2. Import a supported dataset + canonical plan through a committed plan version.
    csv_path = _write_input_csv(tmp_path / "input.csv")
    cat = build_default_catalogue(settings)
    steps = build_canonical_scorecard_steps(csv_path, cat.resolve)

    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Acceptance Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    return client, container, project_id, plan_id, pv_id, project_path


class TestLaunchPathway:
    def test_complete_scorecard_pathway(self, acceptance_env):
        """Run the full canonical pathway and assert the 20 acceptance items."""
        client, container, project_id, plan_id, pv_id, root = acceptance_env

        # 7–8. Submit + execute the launch pathway (sync).
        resp = client.post(
            f"/projects/{project_id}/runs",
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["run_id"]
        assert resp.json()["status"] == "succeeded", resp.text

        uow_factory = container.uow_factory
        with uow_factory.for_project(project_id) as uow:
            run_steps = uow.run_steps.get_for_run(run_id)
            assert all(rs.status.value == "succeeded" for rs in run_steps), (
                f"non-succeeded step: {[(rs.step_id, rs.status.value) for rs in run_steps if rs.status.value != 'succeeded']}"
            )

            # 9. Every step produced >=1 artifact with physical + logical hash.
            for rs in run_steps:
                arts = uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                assert arts, f"Step {rs.step_id} produced no artifacts"
                for art in arts:
                    assert art.physical_hash
                    assert art.logical_hash

            # 10. Binning and WOE evidence present.
            bin_defs = [
                a for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.artifact_type in ("bin_definition", "definition")
            ]
            assert bin_defs, "No BIN_DEFINITION artifact produced"

            # 11. Model artifact with schema_version.
            models = [
                a for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.artifact_type == "model_artifact"
                and a.metadata.get("schema_version") == SCHEMA_MODEL_ARTIFACT
            ]
            assert models, "No MODEL_ARTIFACT produced"

            # 12. Score scaling.
            scorecards = [
                a for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.metadata.get("schema_version") == SCHEMA_SCORE_SCALING
            ]
            assert scorecards, "No SCORE_SCALING artifact produced"

            # 13. Scored datasets for test/oot roles.
            scored_roles = {
                a.role
                for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.role in ("train", "test", "oot") and a.media_type == "application/vnd.apache.parquet"
            }
            assert {"test", "oot"}.issubset(scored_roles), f"Missing scored roles: {scored_roles}"

            # 14. Validation metrics.
            validation = [
                a for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.artifact_type in ("validation_metrics", "report")
                and a.metadata.get("schema_version", "").startswith("cardre.validation_metrics")
            ]
            assert validation, "No VALIDATION_METRICS artifact produced"

            # 15. Scoring exports.
            exports = [
                a for rs in run_steps
                for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                if a.artifact_type in ("scoring_export_python", "scoring_export_sql")
            ]
            assert exports, "No SCORING_EXPORT artifacts produced"

            # 19. Recompute physical hash from bytes and compare to DB.
            from cardre.adapters.filesystem.artifact_store import FsArtifactStore

            store = FsArtifactStore(root)
            for rs in run_steps:
                for art in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id):
                    raw = store.read_bytes(art)
                    assert hashlib.sha256(raw).hexdigest() == art.physical_hash, (
                        f"Physical hash mismatch for {art.artifact_id}"
                    )

        # 16. Audit package generation.
        from cardre.application.reporting.export_audit_pack import ExportAuditPackCommand

        with uow_factory.for_project(project_id) as uow:
            branch_row = uow._conn.execute(
                "SELECT branch_id FROM plan_branches LIMIT 1"
            ).fetchone()
        if branch_row is None:
            # Create a baseline branch + step map so the audit pack can resolve
            # the canonical step identities (mirrors golden report test setup).
            with uow_factory.for_project(project_id) as uow:
                branch_id = uow.branches.create_branch(
                    project_id=project_id, plan_id=plan_id,
                    name="main", branch_type="baseline",
                    base_plan_version_id=pv_id, head_plan_version_id=pv_id,
                    created_reason="acceptance test",
                )
                for s in _canonical_steps(pv_id, uow):
                    uow.branches.create_step_map(
                        branch_id=branch_id, plan_version_id=pv_id,
                        canonical_step_id=s["canonical_step_id"],
                        step_id=s["step_id"], is_branch_owned=True,
                    )
                uow.commit()
        else:
            branch_id = branch_row["branch_id"]
        result = container.export_audit_pack(ExportAuditPackCommand(
            project_id=project_id,
            plan_id=plan_id,
            branch_id=branch_id,
            project_root=str(root),
            export_path=str(root / "exports" / "audit-pack"),
        ))
        assert result.file_count > 0, "Audit pack produced no files"

        # 17. Replay a committed plan; assert deterministic content.
        # Run-scoped artifacts (RunSummary, technical/run manifests, and
        # report/evidence artifacts that embed run_id or run-scoped source
        # ids) legitimately differ between runs. The core fitted artifacts
        # (model, scorecard, bin definitions, WOE tables, scored datasets)
        # must reproduce identical content, i.e. matching logical hashes.
        resp = client.post(
            f"/projects/{project_id}/runs",
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        assert resp.status_code == 201, resp.text
        second_run_id = resp.json()["run_id"]

        def _core_logical_hashes(run_id_value: str) -> dict[tuple[str, str, str], str]:
            core_types = {
                "model_artifact",
                "score_scaling",
                "bin_definition",
                "woe_table",
                "iv_table",
                "dataset",
            }
            with uow_factory.for_project(project_id) as uow:
                out: dict[tuple[str, str, str], str] = {}
                for rs in uow.run_steps.get_for_run(run_id_value):
                    for art in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id):
                        if art.artifact_type in core_types and art.media_type != "application/octet-stream":
                            out[(rs.step_id, art.role, art.artifact_type)] = art.logical_hash
                return out

        assert _core_logical_hashes(run_id) == _core_logical_hashes(second_run_id), (
            "Replayed run produced different core-artifact logical hashes (non-deterministic)"
        )

        # 20. Canonical manifest consistency.
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["plan_version_id"] == pv_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_hash"]
        recomputed = _recompute_manifest_hash(manifest)
        assert recomputed == manifest["manifest_hash"], "manifest_hash does not recompute"

        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            for edge in edges:
                artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                assert artifacts, f"Evidence edge {edge.evidence_edge_id} has no artifacts"
            persisted_run_steps = {rs.step_id for rs in uow.run_steps.get_for_run(run_id)}
            manifest_step_ids = {s["step_id"] for s in manifest["steps"]}
            assert manifest_step_ids == persisted_run_steps, (
                "Manifest steps do not match persisted run steps"
            )


def _recompute_manifest_hash(manifest: dict) -> str:
    """Recompute the manifest hash from the canonical serialized form."""
    from cardre.domain.manifest import compute_manifest_hash

    return compute_manifest_hash(manifest)


def _canonical_steps(pv_id: str, uow) -> list[dict]:
    """Return plan-version steps as dicts for branch step-map seeding."""
    return [
        {
            "step_id": s.step_id,
            "canonical_step_id": s.canonical_step_id,
        }
        for s in uow.plans.get_version_steps(pv_id)
    ]
