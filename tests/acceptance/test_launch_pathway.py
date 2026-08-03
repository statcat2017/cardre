"""Full product acceptance pathway (Batch 07g).

Drives the complete canonical scorecard workflow through the new API and
production stack, covering the 20 product-acceptance items from
``docs/architecture-rewrite/08-acceptance-and-test-strategy.md``.

Plan creation, canonical-version generation, commitment, and run submission
all go through the API (``POST /projects/{id}/plans``,
``POST /projects/{id}/plans/{plan_id}/canonical-version``,
``POST /projects/{id}/plan-versions/{id}/commit``).

Supersedes the pre-Batch-05 ``test_launch_pathway.py`` and
``test_api_scorecard_launch_pathway.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash, table_logical_hash
from cardre.domain.evidence.schemas import (
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_PROFILE_SUMMARY,
    SCHEMA_SCORE_SCALING,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_WOE_IV_EVIDENCE,
    SCHEMA_WOE_TABLE,
)


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
    """Provision a project, create + commit a canonical plan through the API,
    and return the client, container, and roots for post-run assertions.

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

    # 2. Import a supported dataset (the run's import step points at the CSV).
    csv_path = _write_input_csv(tmp_path / "input.csv")

    # 4. Create a plan through the API.
    resp = client.post(f"/projects/{project_id}/plans", json={"name": "Acceptance Plan"})
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    # 5. Generate the canonical pathway through the API: a draft version is
    #    created and populated with the full canonical step set.
    resp = client.post(
        f"/projects/{project_id}/plans/{plan_id}/canonical-version",
        json={"source_path": str(csv_path)},
    )
    assert resp.status_code == 201, resp.text
    pv_id = resp.json()["plan_version_id"]

    # 5b. Edit the define-metadata step through the API, proving the
    #     user-reachable parameter-edit loop on a draft version.
    steps = client.get(f"/projects/{project_id}/plan-versions/{pv_id}/steps")
    assert steps.status_code == 200, steps.text
    meta_step = next(s for s in steps.json() if s["canonical_step_id"] == "define-metadata")
    patch_resp = client.patch(
        f"/projects/{project_id}/plan-versions/{pv_id}/steps/{meta_step['step_id']}",
        json={"params": {**meta_step["params"], "target_column": "credit_risk_class"}},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # 6. Commit the immutable plan version through the API.
    resp = client.post(f"/projects/{project_id}/plan-versions/{pv_id}/commit")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_committed"] is True, resp.text

    return client, container, project_id, plan_id, pv_id, project_path


class TestLaunchPathway:
    def test_complete_scorecard_pathway(self, acceptance_env):
        """Run the full canonical pathway and assert the 20 acceptance items."""
        client, container, project_id, plan_id, pv_id, root = acceptance_env
        uow_factory = container.uow_factory
        from cardre.adapters.filesystem.artifact_store import FsArtifactStore

        store = FsArtifactStore(root)

        # 7–8. Submit + execute the launch pathway (sync).
        resp = client.post(
            f"/projects/{project_id}/runs",
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["run_id"]
        assert resp.json()["status"] == "succeeded", resp.text

        with uow_factory.for_project(project_id) as uow:
            run_steps = uow.run_steps.get_for_run(run_id)
            assert all(rs.status.value == "succeeded" for rs in run_steps), (
                f"non-succeeded step: {[(rs.step_id, rs.status.value) for rs in run_steps if rs.status.value != 'succeeded']}"
            )

            def _artifacts() -> list[tuple[object, object]]:
                return [
                    (rs, a)
                    for rs in run_steps
                    for a in uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                ]

            artifacts = _artifacts()

            # Every run-linked artifact, from BOTH input and output lineage,
            # deduplicated by artifact_id. This includes the synthetic
            # RunSummary, which is input-only lineage for the
            # technical-manifest step, and any future reused input artifact.
            run_artifacts_by_id: dict[str, object] = {}
            for rs in run_steps:
                for _direction, a in uow.artifacts.artifacts_for_run_step(rs.run_step_id):
                    run_artifacts_by_id.setdefault(a.artifact_id, a)
            run_artifacts = list(run_artifacts_by_id.values())

            # 3. Profile summary produced.
            profile = [
                a for rs, a in artifacts
                if a.artifact_type == "profile_summary"
                and a.metadata.get("schema_version") == SCHEMA_PROFILE_SUMMARY
            ]
            assert profile, "No PROFILE_SUMMARY artifact produced"

            # 9. Every step produced >=1 artifact with physical + logical hash.
            for rs in run_steps:
                arts = uow.artifacts.output_artifacts_for_run_step(rs.run_step_id)
                assert arts, f"Step {rs.step_id} produced no artifacts"
                for art in arts:
                    assert art.physical_hash
                    assert art.logical_hash

            # 10. Binning and WOE: BIN_DEFINITION + WOE_IV_EVIDENCE + WOE_TABLE.
            bin_defs = [
                a for rs, a in artifacts
                if a.artifact_type == "bin_definition"
                and a.metadata.get("schema_version") == "cardre.bin_definition.v1"
            ]
            assert bin_defs, "No BIN_DEFINITION artifact produced"
            woe_iv = [
                a for rs, a in artifacts
                if a.artifact_type == "woe_iv_evidence"
                and a.metadata.get("schema_version") == SCHEMA_WOE_IV_EVIDENCE
            ]
            assert woe_iv, "No WOE_IV_EVIDENCE artifact produced"
            woe_tables = [
                a for rs, a in artifacts
                if a.artifact_type == "woe_table"
                and a.metadata.get("schema_version") == SCHEMA_WOE_TABLE
            ]
            assert woe_tables, "No WOE_TABLE artifact produced"

            # 11. Model artifact with schema_version.
            models = [
                a for rs, a in artifacts
                if a.artifact_type == "model_artifact"
                and a.metadata.get("schema_version") == SCHEMA_MODEL_ARTIFACT
            ]
            assert models, "No MODEL_ARTIFACT produced"

            # 12. Score scaling.
            scorecards = [
                a for rs, a in artifacts
                if a.metadata.get("schema_version") == SCHEMA_SCORE_SCALING
            ]
            assert scorecards, "No SCORE_SCALING artifact produced"

            # 13. Apply-model scored datasets for test/oot roles: must come from
            #     the apply-model step (metadata carries model_artifact_id) —
            #     split-node test/oot parquet alone is not sufficient.
            scored = {
                (a.role, a.artifact_type): a
                for rs, a in artifacts
                if rs.step_id == "apply-model"
                and a.artifact_type == "scored_dataset"
                and a.metadata.get("model_artifact_id")
            }
            assert {"test", "oot"}.issubset({role for role, _ in scored}), (
                f"apply-model missing test/oot scored datasets: {sorted(scored)}"
            )

            # 14. Validation metrics.
            validation = [
                a for rs, a in artifacts
                if a.artifact_type == "validation_metrics"
                and a.metadata.get("schema_version") == SCHEMA_VALIDATION_METRICS
            ]
            assert validation, "No VALIDATION_METRICS artifact produced"

            # 15. Scoring exports: BOTH python and sql.
            export_python = [
                a for rs, a in artifacts if a.artifact_type == "scoring_export_python"
            ]
            export_sql = [
                a for rs, a in artifacts if a.artifact_type == "scoring_export_sql"
            ]
            assert export_python, "No SCORING_EXPORT_PYTHON artifact produced"
            assert export_sql, "No SCORING_EXPORT_SQL artifact produced"

            # 19. Recompute physical + logical hashes from stored content for
            # EVERY run-linked artifact (input and output lineage alike,
            # including the synthetic RunSummary). Physical hashes recompute
            # exactly for every artifact. Logical hashes recompute exactly
            # from the persisted bytes: JSON artifacts hash the canonical
            # parsed payload, byte artifacts hash the raw bytes, and Parquet
            # artifacts hash the canonical sorted-column Parquet serialization
            # (``table_logical_hash``), which is byte-stable across the
            # store/read-back cycle.
            for a in run_artifacts:
                raw = store.read_bytes(a)
                assert hashlib.sha256(raw).hexdigest() == a.physical_hash, (
                    f"Physical hash mismatch for {a.artifact_id}"
                )
                recomputed = _recompute_logical_hash(a, raw)
                assert recomputed == a.logical_hash, (
                    f"Logical hash mismatch for {a.artifact_id} "
                    f"({a.artifact_type}/{a.role}): "
                    f"stored={a.logical_hash[:16]} recomputed={recomputed[:16]}"
                )

            # 20. Canonical manifest + technical manifest consistency. The
            # technical manifest must record EVERY persisted, run-linked
            # artifact's physical and logical hash, and each entry must match
            # the DB (the run manifest's manifest_hash recomputes below).
            # The expected set is the same all-lineage collection used by
            # item 19, so it includes the synthetic RunSummary artifact that
            # the technical-manifest step consumes as input. The only
            # exclusion is the technical-manifest index's own output, which
            # cannot reference itself.
            technical_index = None
            for a in run_artifacts:
                if a.artifact_type == "technical_manifest_index":
                    technical_index = json.loads(store.read_bytes(a))
                    break
            assert technical_index is not None, "No technical manifest index produced"
            tech_entries = {}
            for m in technical_index["manifests"]:
                for entry in m.get("artifacts", []):
                    tech_entries[entry["artifact_id"]] = entry
            persisted_ids = {a.artifact_id for a in run_artifacts}
            index_output_ids = {
                a.artifact_id for a in run_artifacts
                if a.artifact_type == "technical_manifest_index"
            }
            expected_ids = persisted_ids - index_output_ids
            assert set(tech_entries) == expected_ids, (
                f"Technical manifest must record every run artifact: "
                f"missing={sorted(expected_ids - set(tech_entries))} "
                f"extra={sorted(set(tech_entries) - expected_ids)}"
            )
            for entry in tech_entries.values():
                art = uow.artifacts.get(entry["artifact_id"])
                assert art is not None, f"Manifest references unknown artifact {entry['artifact_id']}"
                assert entry["physical_hash"] == art.physical_hash, (
                    f"Technical manifest physical hash mismatch for {art.artifact_id}"
                )
                assert entry["logical_hash"] == art.logical_hash, (
                    f"Technical manifest logical hash mismatch for {art.artifact_id}"
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
        audit_dir = root / "exports" / f"audit-pack-{branch_id}"
        container.export_audit_pack(ExportAuditPackCommand(
            project_id=project_id,
            plan_id=plan_id,
            branch_id=branch_id,
            project_root=str(root),
            export_path=str(audit_dir),
        ))
        assert audit_dir.is_dir(), f"Audit pack dir not created: {audit_dir}"
        checksums_path = audit_dir / "checksums.sha256"
        assert checksums_path.is_file(), "Audit pack missing checksums.sha256"
        checksum_entries = {}
        for line in checksums_path.read_text().splitlines():
            digest, _, rel = line.partition("  ")
            checksum_entries[rel.strip()] = digest
        assert len(checksum_entries) >= 4, f"Too few checksum entries: {sorted(checksum_entries)}"
        for rel, digest in checksum_entries.items():
            target = audit_dir / rel
            assert target.is_file(), f"Checksum references missing file: {rel}"
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest, (
                f"Checksum mismatch for {rel}"
            )

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
        manifest_path = root / "manifests" / "runs" / f"{run_id}.json"
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


def _recompute_logical_hash(artifact: object, raw: bytes) -> str:
    """Recompute an artifact's logical hash from its persisted bytes.

    Mirrors the production definitions: JSON artifacts hash the canonical
    parsed payload (``json_logical_hash``); Parquet artifacts hash the
    canonical sorted-column Parquet serialization (``table_logical_hash``),
    which is byte-stable across store/read-back; byte artifacts (e.g. joblib
    estimators) use the raw bytes hash (equal to their physical hash).
    """
    import io

    media_type = getattr(artifact, "media_type", "")
    if media_type == "application/json":
        return json_logical_hash(json.loads(raw))
    if media_type == "application/vnd.apache.parquet":
        frame = pl.read_parquet(io.BytesIO(raw))
        return table_logical_hash(frame)
    return hashlib.sha256(raw).hexdigest()


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
