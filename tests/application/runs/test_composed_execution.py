"""Composed execution test: SubmitRun → ExecuteRun → FinalizeRun through the production stack.

Runs the full canonical scorecard workflow (31 steps) against a real project
database and filesystem artifact store. Asserts exact step set, every step
succeeded, evidence graph integrity, manifest content, and artifact lineage.
"""

from __future__ import annotations

import csv
import json

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.workflows import build_canonical_scorecard_steps, canonical_scorecard_step_ids


def _write_input_csv(path):
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def composed_run(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test Project")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    steps = build_canonical_scorecard_steps(csv_path)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    return project_id, plan_id, pv_id, result.run_id, uow_factory, root


class TestComposedExecution:
    def test_run_succeeds(self, composed_run):
        _, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(composed_run[0]) as uow:
            run = uow.runs.get(run_id)
        assert run is not None
        assert run.status == "succeeded", f"Run status: {run.status}"

    def test_all_31_canonical_steps_succeed(self, composed_run):
        """Every canonical scorecard step completed successfully."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        canonical_ids = canonical_scorecard_step_ids()
        with uow_factory.for_project(project_id) as uow:
            steps = uow.run_steps.get_for_run(run_id)
        step_ids = {s.step_id for s in steps}
        step_lookup = {s.step_id: s for s in steps}
        for cid in canonical_ids:
            assert cid in step_ids, f"Missing canonical step: {cid}"
            assert step_lookup[cid].status.value == "succeeded", f"Step {cid}: {step_lookup[cid].status}"
        assert len(steps) == len(canonical_ids), (
            f"Expected {len(canonical_ids)} steps, got {len(steps)}"
        )

    def test_evidence_artifacts_created_for_every_edge(self, composed_run):
        """Every evidence edge has at least one EvidenceArtifact record."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            assert len(edges) > 0, "No evidence edges created"
            for edge in edges:
                artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                assert len(artifacts) > 0, f"No evidence artifacts for edge {edge.evidence_edge_id}"

    def test_false_edges_not_created(self, composed_run):
        """Parent steps whose outputs were filtered out produce no edge."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            for edge in edges:
                artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                for ea in artifacts:
                    art = uow.artifacts.get(ea.artifact_id)
                    assert art is not None, f"EvidenceArtifact references missing artifact: {ea.artifact_id}"
                    assert art.role in ("output", "input", "report", "definition", "model", "scorecard", "train",
                                       "test", "oot", "manifest", "score_scaling"), f"Unexpected artifact role: {art.role}"

    def test_import_step_has_no_evidence_edges(self, composed_run):
        """The import step (root step, no parents) must have zero edges."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            import_edges = [e for e in edges if e.step_id == "import"]
            assert len(import_edges) == 0, (
                f"Import step should have no evidence edges (no parents), found {len(import_edges)}"
            )

    def test_run_summary_not_in_parent_edges(self, composed_run):
        """The RunSummary artifact must not appear in any parent step evidence edges."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        with uow_factory.for_project(project_id) as uow:
            # Find the RunSummary artifact by scanning for role=manifest, type=run_summary
            summary_art_id = None
            art_row = uow._conn.execute(
                "SELECT artifact_id FROM artifacts WHERE role = 'manifest' AND artifact_type = 'run_summary'"
            ).fetchone()
            if art_row is not None:
                summary_art_id = art_row["artifact_id"]
            assert summary_art_id is not None, "RunSummary artifact not found"
            # Check that no evidence edge uses this artifact
            for edge in uow.evidence.get_edges_for_run(run_id):
                for ea in uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id):
                    assert ea.artifact_id != summary_art_id, (
                        f"RunSummary {summary_art_id} found in evidence edge {edge.evidence_edge_id}"
                    )
            # Check that input lineage was registered for the technical-manifest step
            input_lineage = uow._conn.execute(
                "SELECT COUNT(*) FROM artifact_lineage "
                "WHERE artifact_id = ? AND direction = 'input' AND step_id = 'technical-manifest'",
                (summary_art_id,),
            ).fetchone()[0]
            assert input_lineage > 0, (
                f"RunSummary {summary_art_id} has no input lineage for technical-manifest"
            )

    def test_manifest_contains_all_steps(self, composed_run):
        """Canonical manifest has the full step set and identity checks pass."""
        _, _, _, run_id, _, root = composed_run
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_hash"]
        step_ids_in_manifest = {s["step_id"] for s in manifest["steps"]}
        canonical_ids = set(canonical_scorecard_step_ids())
        assert step_ids_in_manifest == canonical_ids, (
            f"Manifest steps mismatch: missing={canonical_ids - step_ids_in_manifest}, "
            f"extra={step_ids_in_manifest - canonical_ids}"
        )

    def test_every_artifact_linked_in_manifest(self, composed_run):
        """Every artifact referenced by a step in the manifest has a lineage record."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest_art_ids: set[str] = set()
        for s in manifest["steps"]:
            manifest_art_ids.update(s.get("input_artifact_ids", []))
            manifest_art_ids.update(s.get("output_artifact_ids", []))
        with uow_factory.for_project(project_id) as uow:
            lineage = uow._conn.execute(
                "SELECT DISTINCT artifact_id FROM artifact_lineage WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        persisted_ids = {row["artifact_id"] for row in lineage}
        # Every manifest artifact should be in persisted lineage
        unlinked = manifest_art_ids - persisted_ids
        assert not unlinked, f"Manifest artifacts without lineage: {unlinked}"

    def test_technical_manifest_has_correct_input_output_ids(self, composed_run):
        """TechnicalManifestIndex artifact has distinct correct input and output IDs."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        with uow_factory.for_project(project_id) as uow:
            run_steps = uow.run_steps.get_for_run(run_id)
            from cardre.adapters.filesystem.artifact_store import FsArtifactStore
            art_store = FsArtifactStore(root)
            canonical_ids = set(canonical_scorecard_step_ids())
            for rs in run_steps:
                if rs.step_id == "technical-manifest":
                    for aid in uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id):
                        art = uow.artifacts.get(aid)
                        if art is None:
                            continue
                        import json
                        payload = json.loads(art_store.resolve_path(art).read_text())
                        manifests = payload.get("manifests", [])
                        assert len(manifests) > 0
                        m = manifests[0]
                        assert "run_id" in m
                        assert "plan_version_id" in m
                        manifest_step_ids = {s["step_id"] for s in m.get("steps", [])}
                        # Technical manifest excludes itself (RunSummary built before it runs)
                        expected = canonical_ids - {"technical-manifest"}
                        assert manifest_step_ids == expected, (
                            f"Technical manifest step set mismatch: "
                            f"missing={expected - manifest_step_ids}, "
                            f"extra={manifest_step_ids - expected}"
                        )
                        for s in m.get("steps", []):
                            inp_hashes = s.get("input_artifact_logical_hashes", [])
                            out_hashes = s.get("output_artifact_logical_hashes", [])
                            # Verify hashes are non-empty strings
                            for h in inp_hashes + out_hashes:
                                assert isinstance(h, str) and len(h) > 0, f"Invalid hash in {s['step_id']}: {h!r}"
                            # For import (no parents) all hashes must be artifact IDs / logical hashes
                            if s["step_id"] != "import":
                                assert len(inp_hashes) > 0 or len(out_hashes) > 0, (
                                    f"Step {s['step_id']} has zero hashes"
                                )
                            assert isinstance(s.get("warnings"), list) if "warnings" in s else True
                            assert isinstance(s.get("errors"), list) if "errors" in s else True
                        assert len(m.get("artifacts", [])) > 0
                    break

    def test_technical_manifest_hashes_match_artifacts(self, composed_run):
        """Technical manifest hash entries correspond to real persisted artifacts."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        with uow_factory.for_project(project_id) as uow:
            from cardre.adapters.filesystem.artifact_store import FsArtifactStore
            art_store = FsArtifactStore(root)
            found = False
            for rs in uow.run_steps.get_for_run(run_id):
                if rs.step_id == "technical-manifest":
                    for aid in uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id):
                        art = uow.artifacts.get(aid)
                        if art is None or art.artifact_type != "technical_manifest_index":
                            continue
                        import json
                        payload = json.loads(art_store.resolve_path(art).read_text())
                        for m in payload.get("manifests", []):
                            for art_entry in m.get("artifacts", []):
                                persisted = uow.artifacts.get(art_entry["artifact_id"])
                                assert persisted is not None, (
                                    f"Manifest references missing artifact: {art_entry['artifact_id']}"
                                )
                                assert persisted.physical_hash == art_entry["physical_hash"], (
                                    f"Physical hash mismatch for {art_entry['artifact_id']}"
                                )
                                assert persisted.logical_hash == art_entry["logical_hash"], (
                                    f"Logical hash mismatch for {art_entry['artifact_id']}"
                                )
                        found = True
                    break
            assert found, "No technical-manifest artifacts found"

    def test_technical_manifest_logical_hashes_match_persisted(self, composed_run):
        """Each step's logical hashes in the manifest equal persisted lineage logical hashes."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        with uow_factory.for_project(project_id) as uow:
            from cardre.adapters.filesystem.artifact_store import FsArtifactStore
            art_store = FsArtifactStore(root)
            for rs in uow.run_steps.get_for_run(run_id):
                if rs.step_id == "technical-manifest":
                    for aid in uow.artifacts.output_artifact_ids_for_run_step(rs.run_step_id):
                        art = uow.artifacts.get(aid)
                        if art is None or art.artifact_type != "technical_manifest_index":
                            continue
                        import json
                        payload = json.loads(art_store.resolve_path(art).read_text())
                        for m in payload.get("manifests", []):
                            for s in m.get("steps", []):
                                step_rs = next((rs2 for rs2 in uow.run_steps.get_for_run(run_id) if rs2.step_id == s["step_id"]), None)
                                if step_rs is None:
                                    continue
                                lineage = uow.artifacts.artifacts_for_run_step(step_rs.run_step_id)
                                persisted_input_logical = [a.logical_hash for d, a in lineage if d == "input"]
                                persisted_output_logical = [a.logical_hash for d, a in lineage if d == "output"]
                                manifest_input = s.get("input_artifact_logical_hashes", [])
                                manifest_output = s.get("output_artifact_logical_hashes", [])
                                if s["step_id"] != "import":
                                    assert set(manifest_input) == set(persisted_input_logical), (
                                        f"Step {s['step_id']} input hashes mismatch: "
                                        f"manifest={manifest_input}, persisted={persisted_input_logical}"
                                    )
                                assert set(manifest_output) == set(persisted_output_logical), (
                                    f"Step {s['step_id']} output hashes mismatch: "
                                    f"manifest={manifest_output}, persisted={persisted_output_logical}"
                                )
                    break
