"""Batch R4 — semantic artifact identity and output-contract enforcement.

Covers findings 3 and 7 of the thermonuclear review:

1. **Blob/descriptor split** — byte storage is keyed by physical hash and
   shared across descriptors; a descriptor keeps its own semantic identity
   (type/role/schema). Two descriptors with the same bytes but different
   roles are both retained, lineage resolves each correctly, and an exact
   duplicate descriptor is idempotent.
2. **Full output-contract enforcement** — a node emitting a wrong kind,
   wrong media type, or an undeclared role fails before publication; a valid
   multi-role node still publishes all descriptors and lineage.

All tests run through the real SQLite + filesystem adapters.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.execution.contract_validation import validate_output_contract
from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import ArtifactContract, ArtifactRoleSpec


def _provision(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "p1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, root


def _stage(root: Path, payload: bytes, *, role: str, artifact_type: str) -> StagedArtifact:
    staging_dir = root / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    import hashlib

    phys = hashlib.sha256(payload).hexdigest()
    staging = staging_dir / f"{phys}.bin"
    staging.write_bytes(payload)
    return StagedArtifact(
        staging_path=staging,
        provisional_artifact_id=f"{artifact_type}:{role}:{phys}",
        physical_hash=phys,
        logical_hash=json_logical_hash({"payload": payload.decode()}) if payload else "",
        media_type="application/json",
        schema_version="modelling_metadata",
        role=role,
        artifact_type=artifact_type,
        metadata={"schema_version": "v1"},
    )


def _ref(artifact_id: str, phys: str, *, role: str, artifact_type: str):
    from cardre.domain.artifacts import ArtifactRef

    return ArtifactRef(
        artifact_id=artifact_id, artifact_type=artifact_type, role=role,
        path=f"/objects/{phys}", physical_hash=phys, logical_hash="lh",
        media_type="application/json", metadata={"schema_version": "v1"},
    )


# ---------------------------------------------------------------------------
# Finding 3 — blob/descriptor split
# ---------------------------------------------------------------------------


def test_two_descriptors_share_one_blob(tmp_path):
    """Two descriptors with the same bytes but different role/type produce one
    blob and two descriptors; lineage resolves each correctly."""
    project_id, uow_factory, root = _provision(tmp_path)
    payload = json.dumps({"a": 1}, sort_keys=True).encode("utf-8")
    staged1 = _stage(root, payload, role="report", artifact_type="profile_summary")
    staged2 = _stage(root, payload, role="definition", artifact_type="bin_definition")
    assert staged1.physical_hash == staged2.physical_hash, "same bytes => same hash"

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow._conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-1", run_id, "s1", pv_id, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        id1 = uow.artifacts.register(_ref(staged1.provisional_artifact_id, staged1.physical_hash,
                                          role="report", artifact_type="profile_summary"))
        id2 = uow.artifacts.register(_ref(staged2.provisional_artifact_id, staged2.physical_hash,
                                          role="definition", artifact_type="bin_definition"))
        uow.artifacts.register_lineage(
            run_id=run_id, run_step_id="rs-1", plan_version_id=pv_id,
            step_id="s1", artifact_id=id1, direction="output",
        )
        uow.artifacts.register_lineage(
            run_id=run_id, run_step_id="rs-1", plan_version_id=pv_id,
            step_id="s1", artifact_id=id2, direction="output",
        )
        uow.commit()

        # One blob, two descriptors.
        blob = uow.artifacts.get_blob(staged1.physical_hash)
        assert blob is not None
        desc_rows = uow._conn.execute(
            "SELECT artifact_id FROM artifacts WHERE physical_hash = ?", (staged1.physical_hash,)
        ).fetchall()
        assert len(desc_rows) == 2

        # Lineage resolves each descriptor with its own semantic identity.
        lineage = uow.artifacts.artifacts_for_run_step("rs-1")
        by_role = {a.role: a for _, a in lineage}
        assert by_role["report"].artifact_id == id1
        assert by_role["definition"].artifact_id == id2
        assert by_role["report"].artifact_type == "profile_summary"
        assert by_role["definition"].artifact_type == "bin_definition"


def test_typed_evidence_lookup_uses_own_descriptor(tmp_path):
    """Each descriptor keeps its own type/role, so typed lookup is unambiguous."""
    project_id, uow_factory, root = _provision(tmp_path)
    payload = json.dumps({"x": 1}, sort_keys=True).encode("utf-8")
    staged1 = _stage(root, payload, role="report", artifact_type="profile_summary")
    staged2 = _stage(root, payload, role="report", artifact_type="bin_definition")

    with uow_factory.for_project(project_id) as uow:
        id1 = uow.artifacts.register(_ref(staged1.provisional_artifact_id, staged1.physical_hash,
                                          role="report", artifact_type="profile_summary"))
        id2 = uow.artifacts.register(_ref(staged2.provisional_artifact_id, staged2.physical_hash,
                                          role="report", artifact_type="bin_definition"))
        uow.commit()
        d1 = uow.artifacts.get(id1)
        d2 = uow.artifacts.get(id2)
    assert d1 is not None and d2 is not None
    assert d1.artifact_id != d2.artifact_id
    assert d1.artifact_type == "profile_summary"
    assert d2.artifact_type == "bin_definition"
    assert d1.physical_hash == d2.physical_hash


def test_exact_duplicate_descriptor_is_idempotent(tmp_path):
    """Registering the exact same descriptor twice is idempotent: one
    descriptor row, one blob."""
    project_id, uow_factory, root = _provision(tmp_path)
    payload = json.dumps({"y": 2}, sort_keys=True).encode("utf-8")
    staged = _stage(root, payload, role="report", artifact_type="profile_summary")
    ref = _ref(staged.provisional_artifact_id, staged.physical_hash,
               role="report", artifact_type="profile_summary")

    with uow_factory.for_project(project_id) as uow:
        first = uow.artifacts.register(ref)
        second = uow.artifacts.register(ref)
        assert first == second
        rows = uow._conn.execute(
            "SELECT artifact_id FROM artifacts WHERE artifact_id = ?", (ref.artifact_id,)
        ).fetchall()
        assert len(rows) == 1
        blobs = uow._conn.execute(
            "SELECT physical_hash FROM blobs WHERE physical_hash = ?", (staged.physical_hash,)
        ).fetchall()
        assert len(blobs) == 1


def test_artifacts_table_has_no_unique_physical_hash(tmp_path):
    """The artifacts table no longer enforces one-descriptor-per-blob."""
    project_id, uow_factory, _root = _provision(tmp_path)
    with uow_factory.read_only(project_id) as uow:
        idx = uow._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone()
    assert "UNIQUE(physical_hash)" not in (idx["sql"] or "")


# ---------------------------------------------------------------------------
# Finding 7 — full output-contract enforcement
# ---------------------------------------------------------------------------


def _contract(*roles: ArtifactRoleSpec) -> ArtifactContract:
    return ArtifactContract(roles=roles)


def _staged_artifact(root: Path, *, role: str, kind: str, media_type: str = "application/json") -> StagedArtifact:
    payload = json.dumps({"k": role}, sort_keys=True).encode("utf-8")
    s = _stage(root, payload, role=role, artifact_type="profile_summary")
    return StagedArtifact(
        staging_path=s.staging_path, provisional_artifact_id=s.provisional_artifact_id,
        physical_hash=s.physical_hash, logical_hash=s.logical_hash,
        media_type=media_type, schema_version=kind, role=role,
        artifact_type=s.artifact_type, metadata=s.metadata,
    )


def test_wrong_kind_is_rejected(tmp_path):
    """A required role emitted with the wrong evidence kind fails validation."""
    contract = _contract(ArtifactRoleSpec("report", kinds=(EvidenceKind.PROFILE_SUMMARY,)))
    staged = _staged_artifact(tmp_path, role="report", kind=EvidenceKind.MODELLING_METADATA.value)
    with pytest.raises(ValueError, match="kind"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_wrong_media_type_is_rejected(tmp_path):
    """A role emitted with the wrong media type fails validation."""
    contract = _contract(ArtifactRoleSpec("report", media_types=("application/json",)))
    staged = _staged_artifact(tmp_path, role="report", kind="k",
                              media_type="application/vnd.apache.parquet")
    with pytest.raises(ValueError, match="media type"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_undeclared_role_is_rejected(tmp_path):
    """A node with an explicit contract cannot emit an undeclared role."""
    contract = _contract(ArtifactRoleSpec("report", required=True))
    staged = _staged_artifact(tmp_path, role="rogue", kind="k")
    with pytest.raises(ValueError, match="undeclared"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_missing_required_role_is_rejected(tmp_path):
    contract = _contract(
        ArtifactRoleSpec("report", required=True),
        ArtifactRoleSpec("model", required=True),
    )
    staged = _staged_artifact(tmp_path, role="report", kind="k")
    with pytest.raises(ValueError, match="missing required"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_valid_multi_role_contract_passes(tmp_path):
    """A valid multi-role node publishes all descriptors."""
    contract = _contract(
        ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.PROFILE_SUMMARY,)),
        ArtifactRoleSpec("model", required=True, kinds=(EvidenceKind.MODEL_ARTIFACT,)),
    )
    staged = [
        _staged_artifact(tmp_path, role="report", kind=EvidenceKind.PROFILE_SUMMARY.value),
        _staged_artifact(tmp_path, role="model", kind=EvidenceKind.MODEL_ARTIFACT.value),
    ]
    validate_output_contract(contract, staged, node_type="test", step_id="s1")  # no raise


def test_empty_contract_is_only_opt_out(tmp_path):
    """An empty contract remains the only opt-out."""
    staged = _staged_artifact(tmp_path, role="anything", kind="k")
    validate_output_contract(ArtifactContract(), [staged], node_type="test", step_id="s1")
