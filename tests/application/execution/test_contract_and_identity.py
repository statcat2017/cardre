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
from cardre.application.execution.contract_validation import (
    validate_input_contract,
    validate_output_contract,
)
from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import ArtifactRef, json_logical_hash
from cardre.domain.errors import CardreError, ErrorCode
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


def test_same_role_type_different_schema_two_descriptors(tmp_path):
    """Identical bytes with the same role/type but different schema version
    must produce two distinct descriptors (finding 3 / review P1-1)."""
    from cardre.domain.artifacts import descriptor_id

    project_id, uow_factory, root = _provision(tmp_path)

    id_v1 = descriptor_id(
        artifact_type="profile_summary", role="report", media_type="application/json",
        kind="profile_summary", schema_version="profile_summary.v1",
        logical_hash="lh", physical_hash="phys-shared",
    )
    id_v2 = descriptor_id(
        artifact_type="profile_summary", role="report", media_type="application/json",
        kind="profile_summary", schema_version="profile_summary.v2",
        logical_hash="lh", physical_hash="phys-shared",
    )
    assert id_v1 != id_v2, "schema version must be identity-bearing"

    from cardre.domain.artifacts import ArtifactRef

    ref_v1 = ArtifactRef(
        artifact_id=id_v1, artifact_type="profile_summary", role="report",
        path="/objects/x", physical_hash="phys-shared", logical_hash="lh",
        media_type="application/json", metadata={"schema_version": "profile_summary.v1"},
    )
    ref_v2 = ArtifactRef(
        artifact_id=id_v2, artifact_type="profile_summary", role="report",
        path="/objects/x", physical_hash="phys-shared", logical_hash="lh",
        media_type="application/json", metadata={"schema_version": "profile_summary.v2"},
    )

    with uow_factory.for_project(project_id) as uow:
        got_v1 = uow.artifacts.register(ref_v1)
        got_v2 = uow.artifacts.register(ref_v2)
        assert got_v1 == id_v1
        assert got_v2 == id_v2
        assert got_v1 != got_v2
        d1 = uow.artifacts.get(id_v1)
        d2 = uow.artifacts.get(id_v2)
        assert d1 is not None and d2 is not None
        assert d1.metadata["schema_version"] == "profile_summary.v1"
        assert d2.metadata["schema_version"] == "profile_summary.v2"
        assert uow.artifacts.get_blob("phys-shared") is not None, "one shared blob"


def test_same_role_type_different_metadata_two_descriptors(tmp_path):
    """Metadata-only semantic difference is identity-bearing (review P1-B).

    All existing ID fields (type, role, media, kind, schema, logical, physical
    hash) are held constant; only the semantic metadata (e.g. ``exclude_key``,
    which the evidence reader uses to match bin definitions) differs. Two such
    descriptors must be distinct rather than collapsing onto the first.
    """
    from cardre.domain.artifacts import ArtifactRef, descriptor_id

    project_id, uow_factory, root = _provision(tmp_path)
    id_a = descriptor_id(
        artifact_type="bin_definition", role="definition", media_type="application/json",
        kind="bin_definition", schema_version="bin_definition.v1",
        logical_hash="lh", physical_hash="ph",
        metadata={"exclude_key": "selected"},
    )
    id_b = descriptor_id(
        artifact_type="bin_definition", role="definition", media_type="application/json",
        kind="bin_definition", schema_version="bin_definition.v1",
        logical_hash="lh", physical_hash="ph",
        metadata={"exclude_key": "all"},
    )
    assert id_a != id_b, "semantic metadata difference must be identity-bearing"

    with uow_factory.for_project(project_id) as uow:
        a = uow.artifacts.register(ArtifactRef(
            artifact_id=id_a, artifact_type="bin_definition", role="definition", path="/o",
            physical_hash="ph", logical_hash="lh", media_type="application/json",
            metadata={"schema_version": "bin_definition.v1", "exclude_key": "selected"},
        ))
        b = uow.artifacts.register(ArtifactRef(
            artifact_id=id_b, artifact_type="bin_definition", role="definition", path="/o",
            physical_hash="ph", logical_hash="lh", media_type="application/json",
            metadata={"schema_version": "bin_definition.v1", "exclude_key": "all"},
        ))
        assert a != b
        assert uow.artifacts.get_blob("ph") is not None
        rows = uow._conn.execute(
            "SELECT artifact_id FROM artifacts WHERE physical_hash = ?", ("ph",)
        ).fetchall()
        assert len(rows) == 2


def test_provenance_metadata_not_identity_bearing(tmp_path):
    """Run-provenance metadata (creating_run_id, source_artifact_id) must NOT
    change descriptor identity: the same deterministic artifact from a
    different run is the same descriptor."""
    from cardre.domain.artifacts import descriptor_id

    id_1 = descriptor_id(
        artifact_type="model_artifact", role="model", media_type="application/octet-stream",
        kind="model_artifact", schema_version="", logical_hash="lh", physical_hash="ph",
        metadata={
            "creating_run_id": "run-1", "creating_run_step_id": "step-1",
            "source_artifact_id": "art-1", "model_family": "logistic_regression",
        },
    )
    id_2 = descriptor_id(
        artifact_type="model_artifact", role="model", media_type="application/octet-stream",
        kind="model_artifact", schema_version="", logical_hash="lh", physical_hash="ph",
        metadata={
            "creating_run_id": "run-2", "creating_run_step_id": "step-2",
            "source_artifact_id": "art-2", "model_family": "logistic_regression",
        },
    )
    assert id_1 == id_2, "provenance metadata must not affect descriptor identity"


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
    with pytest.raises(CardreError, match="kind"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_wrong_media_type_is_rejected(tmp_path):
    """A role emitted with the wrong media type fails validation."""
    contract = _contract(ArtifactRoleSpec("report", media_types=("application/json",)))
    staged = _staged_artifact(tmp_path, role="report", kind="k",
                              media_type="application/vnd.apache.parquet")
    with pytest.raises(CardreError, match="media type"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_undeclared_role_is_rejected(tmp_path):
    """A node with an explicit contract cannot emit an undeclared role."""
    contract = _contract(ArtifactRoleSpec("report", required=True))
    staged = _staged_artifact(tmp_path, role="rogue", kind="k")
    with pytest.raises(CardreError, match="undeclared"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_missing_required_role_is_rejected(tmp_path):
    contract = _contract(
        ArtifactRoleSpec("report", required=True),
        ArtifactRoleSpec("model", required=True),
    )
    staged = _staged_artifact(tmp_path, role="report", kind="k")
    with pytest.raises(CardreError, match="missing required"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_valid_multi_role_contract_passes(tmp_path):
    """A valid multi-role node publishes all descriptors."""
    contract = _contract(
        ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.PROFILE_SUMMARY,)),
        ArtifactRoleSpec("model", required=True, kinds=(EvidenceKind.MODEL_ARTIFACT,)),
    )
    report = _staged_artifact(tmp_path, role="report", kind=EvidenceKind.PROFILE_SUMMARY.value)
    report = StagedArtifact(
        staging_path=report.staging_path, provisional_artifact_id=report.provisional_artifact_id,
        physical_hash=report.physical_hash, logical_hash=report.logical_hash,
        media_type=report.media_type, schema_version=report.schema_version,
        role="report", artifact_type="profile_summary",
        metadata={"schema_version": "cardre.profile_summary.v1"},
    )
    model = _staged_artifact(tmp_path, role="model", kind=EvidenceKind.MODEL_ARTIFACT.value)
    model = StagedArtifact(
        staging_path=model.staging_path, provisional_artifact_id=model.provisional_artifact_id,
        physical_hash=model.physical_hash, logical_hash=model.logical_hash,
        media_type=model.media_type, schema_version=model.schema_version,
        role="model", artifact_type="model_artifact",
        metadata={"schema_version": "cardre.model_artifact.v1"},
    )
    validate_output_contract(contract, [report, model], node_type="test", step_id="s1")  # no raise


def test_empty_contract_is_only_opt_out(tmp_path):
    """An empty contract remains the only opt-out."""
    staged = _staged_artifact(tmp_path, role="anything", kind="k")
    validate_output_contract(ArtifactContract(), [staged], node_type="test", step_id="s1")


def test_loose_string_kind_is_rejected(tmp_path):
    """A contract declaring a loose string kind is a configuration error (P2-1)."""
    from cardre.domain.evidence.kinds import EvidenceKind

    contract = _contract(ArtifactRoleSpec("report", kinds=("dataset",)))
    staged = _staged_artifact(tmp_path, role="report", kind=EvidenceKind.MODELLING_METADATA.value)
    with pytest.raises(CardreError, match="typed"):
        validate_output_contract(contract, [staged], node_type="test", step_id="s1")


def test_role_kind_expands_to_evidence_kinds(tmp_path):
    """RoleKind tokens expand to concrete EvidenceKind values."""
    from cardre.domain.evidence.kinds import EvidenceKind, RoleKind

    contract = _contract(ArtifactRoleSpec("report", kinds=(RoleKind.REPORT,)))
    staged = _staged_artifact(tmp_path, role="report", kind=EvidenceKind.PROFILE_SUMMARY.value)
    staged = StagedArtifact(
        staging_path=staged.staging_path, provisional_artifact_id=staged.provisional_artifact_id,
        physical_hash=staged.physical_hash, logical_hash=staged.logical_hash,
        media_type=staged.media_type, schema_version=staged.schema_version,
        role="report", artifact_type="profile_summary",
        metadata={"schema_version": "cardre.profile_summary.v1"},
    )
    validate_output_contract(contract, [staged], node_type="test", step_id="s1")  # no raise

    bad = _staged_artifact(tmp_path, role="report", kind="not_a_kind")
    with pytest.raises(CardreError, match="kind"):
        validate_output_contract(contract, [bad], node_type="test", step_id="s1")


def test_schema_version_enforced_from_metadata(tmp_path):
    """The versioned evidence schema (metadata) is enforced separately from kind."""
    from cardre.domain.evidence.kinds import EvidenceKind

    contract = _contract(ArtifactRoleSpec(
        "report", kinds=(EvidenceKind.PROFILE_SUMMARY,), schema_versions=("cardre.profile_summary.v1",),
    ))
    ok = _stage(tmp_path, b'{"a":1}', role="report", artifact_type="profile_summary")
    ok_artifact = StagedArtifact(
        staging_path=ok.staging_path, provisional_artifact_id=ok.provisional_artifact_id,
        physical_hash=ok.physical_hash, logical_hash=ok.logical_hash,
        media_type=ok.media_type, schema_version=EvidenceKind.PROFILE_SUMMARY.value,
        role="report", artifact_type="profile_summary",
        metadata={"schema_version": "cardre.profile_summary.v1"},
    )
    validate_output_contract(contract, [ok_artifact], node_type="test", step_id="s1")

    bad = StagedArtifact(
        staging_path=ok.staging_path, provisional_artifact_id=ok.provisional_artifact_id,
        physical_hash=ok.physical_hash, logical_hash=ok.logical_hash,
        media_type=ok.media_type, schema_version=EvidenceKind.PROFILE_SUMMARY.value,
        role="report", artifact_type="profile_summary",
        metadata={"schema_version": "cardre.profile_summary.v9"},
    )
    with pytest.raises(CardreError, match="schema version"):
        validate_output_contract(contract, [bad], node_type="test", step_id="s1")


def test_catalogue_contracts_are_machine_checkable():
    """Every node in the catalogue declares typed, machine-checkable contracts
    (P2-1/P2-B). Roles are tuples, every kind is an EvidenceKind or RoleKind,
    and every launch-tier output contract role with declared kinds also
    declares its versioned schemas and media types, so a wrong-kind/wrong-
    schema/wrong-media artifact cannot pass. Module import or definition
    failures fail the audit rather than being skipped.
    """
    import importlib
    import inspect
    import pkgutil

    import cardre.nodes as nodes_pkg
    from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
    from cardre.nodes.contracts import NodeType

    problems = []
    for mod in pkgutil.walk_packages(nodes_pkg.__path__, nodes_pkg.__name__ + "."):
        try:
            m = importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001 — an import failure must fail the audit
            problems.append(f"module import failed: {mod.name}: {exc}")
            continue
        for _, obj in inspect.getmembers(m, inspect.isclass):
            if not (inspect.isclass(obj) and issubclass(obj, NodeType) and obj is not NodeType):
                continue
            if getattr(obj, "__module__", "") != m.__name__:
                continue
            if not getattr(obj, "node_type", ""):
                # Abstract base classes (no node_type) are not catalogue nodes.
                continue
            try:
                defn = obj.__definition__
            except Exception as exc:  # noqa: BLE001 — a definition failure must fail the audit
                problems.append(f"{obj.node_type} __definition__ failed: {exc}")
                continue
            if defn is None:
                continue
            tier = "deferred" if getattr(obj, "_deferred", False) else getattr(obj, "tier", "launch")
            for which in ("input_contract", "output_contract"):
                contract = getattr(defn, which, None)
                if contract is None:
                    continue
                roles = getattr(contract, "roles", ())
                if not isinstance(roles, tuple):
                    problems.append(f"{obj.node_type} {which}.roles is {type(roles).__name__}")
                    continue
                for spec in roles:
                    kinds = list(getattr(spec, "kinds", ()) or ())
                    for k in kinds:
                        if not isinstance(k, (EvidenceKind, RoleKind)):
                            problems.append(
                                f"{obj.node_type} {which} role={spec.role} kind={k!r} untyped"
                            )
                    if which == "output_contract" and tier == "launch" and kinds:
                        if getattr(spec, "schema_versions", None) is None:
                            problems.append(
                                f"{obj.node_type} {which} role={spec.role} (launch) "
                                "declares kinds but no schema_versions"
                            )
                        if not getattr(spec, "media_types", ()):
                            problems.append(
                                f"{obj.node_type} {which} role={spec.role} (launch) "
                                "declares kinds but no media_types"
                            )
    assert problems == [], "non-machine-checkable contracts:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# Typed input-contract enforcement (Batch 3)
# ---------------------------------------------------------------------------


def _input_ref(*, role: str, media_type: str = "application/json",
               schema_version: str = "") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"art-{role}", artifact_type="report", role=role,
        path="objects/x", physical_hash="p", logical_hash="l",
        media_type=media_type, metadata={"schema_version": schema_version},
    )


def test_input_wrong_media_type_is_rejected():
    """A supplied input whose media type violates its role spec fails before
    the node runs."""
    contract = ArtifactContract(roles=(
        ArtifactRoleSpec("model", required=True, media_types=("application/json",)),
    ))
    bad = _input_ref(role="model", media_type="application/vnd.apache.parquet")
    with pytest.raises(CardreError, match="media type") as exc:
        validate_input_contract(contract, [bad], node_type="test", step_id="s1")
    assert exc.value.code == ErrorCode.INPUT_CONTRACT_VIOLATION


def test_input_wrong_schema_version_is_rejected():
    """A supplied input with a wrong versioned schema fails before the node."""
    contract = ArtifactContract(roles=(
        ArtifactRoleSpec("model", required=True,
                         schema_versions=("cardre.model_artifact.v1",)),
    ))
    bad = _input_ref(role="model", schema_version="cardre.model_artifact.v9")
    with pytest.raises(CardreError, match="schema version") as exc:
        validate_input_contract(contract, [bad], node_type="test", step_id="s1")
    assert exc.value.code == ErrorCode.INPUT_CONTRACT_VIOLATION


def test_input_valid_media_and_schema_passes():
    contract = ArtifactContract(roles=(
        ArtifactRoleSpec("model", required=True,
                         media_types=("application/json",),
                         schema_versions=("cardre.model_artifact.v1",)),
        ArtifactRoleSpec("test", required=False),
    ))
    ok = _input_ref(role="model", schema_version="cardre.model_artifact.v1")
    validate_input_contract(contract, [ok], node_type="test", step_id="s1")  # no raise


def test_input_missing_required_role_is_rejected():
    contract = ArtifactContract(roles=(
        ArtifactRoleSpec("model", required=True),
    ))
    with pytest.raises(CardreError, match="missing required input") as exc:
        validate_input_contract(contract, [], node_type="test", step_id="s1")
    assert exc.value.code == ErrorCode.INPUT_CONTRACT_VIOLATION
