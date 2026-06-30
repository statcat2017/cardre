"""Role enforcement, leakage protection, and input artifact file validation.

Pure validation helpers extracted from PlanExecutor.
"""
from __future__ import annotations

from cardre.audit import ArtifactRef, NodeType, StepSpec, physical_hash
from cardre.errors import ArtifactReadError, CardreError
from cardre.store import ProjectStore

LEAKAGE_SENSITIVE_CATEGORIES = {"fit", "selection", "refinement"}


class RoleAccessError(CardreError):
    code = "ROLE_ACCESS_ERROR"
    status_code = 400


class LeakageProtectionError(CardreError):
    code = "LEAKAGE_PROTECTION_ERROR"
    status_code = 400


def filter_inputs_by_role(node: NodeType, artifacts: list[ArtifactRef]) -> list[ArtifactRef]:
    if not node.input_roles:
        return artifacts
    permitted = set(node.input_roles)
    return [a for a in artifacts if a.role in permitted]


def validate_role_access(
    node: NodeType,
    spec: StepSpec,
    filtered_artifacts: list[ArtifactRef],
    raw_inputs: list[ArtifactRef],
) -> None:
    if not node.input_roles:
        return
    if spec.parent_step_ids and not filtered_artifacts:
        raw_roles = sorted({a.role for a in raw_inputs})
        raise RoleAccessError(
            f"Node {node.node_type!r} declares input roles "
            f"{node.input_roles} but receives no matching artifacts. "
            f"Raw parent roles: {raw_roles}. "
            f"Check plan wiring: step {spec.step_id!r} parents "
            f"{spec.parent_step_ids!r}."
        )
    permitted = set(node.input_roles)
    for artifact in filtered_artifacts:
        if artifact.role not in permitted:
            raise RoleAccessError(
                f"Node {node.node_type!r} declares input roles "
                f"{sorted(permitted)} but cannot consume artifact "
                f"role {artifact.role!r}."
            )


def validate_node_input_roles(node: NodeType, artifacts: list[ArtifactRef]) -> None:
    if not node.input_roles:
        return
    if not artifacts:
        raise RoleAccessError(
            f"Node {node.node_type!r} declares input roles "
            f"{node.input_roles} but received no artifacts."
        )
    actual_roles = {a.role for a in artifacts}
    matching = set(node.input_roles) & actual_roles
    if not matching:
        raise RoleAccessError(
            f"Node {node.node_type!r} permits input roles "
            f"{node.input_roles} but receives only "
            f"{sorted(actual_roles)}. No permitted role matched."
        )


def validate_leakage_rules(node: NodeType, artifacts: list[ArtifactRef]) -> None:
    if node.category not in LEAKAGE_SENSITIVE_CATEGORIES:
        return
    for a in artifacts:
        if a.role in ("test", "oot") and a.artifact_type == "dataset":
            if hasattr(node, "allows_leakage_artifact") and node.allows_leakage_artifact(a):
                continue
            raise LeakageProtectionError(
                f"Node {node.node_type!r} (category={node.category!r}) "
                f"cannot consume {a.role!r} dataset artifact. "
                f"Leakage-sensitive nodes must not consume test or OOT "
                f"tabular data. Artifact ID: {a.artifact_id}"
            )


def validate_input_artifact_files(store: ProjectStore, artifacts: list[ArtifactRef]) -> None:
    for artifact in artifacts:
        path = store.artifact_path(artifact)  # cardre-allow-artifact-read: low-level-evidence-parser
        if not path.exists():
            raise ArtifactReadError(
                f"Artifact {artifact.artifact_id!r} metadata points to missing file {artifact.path!r}"
            )
        current_hash = physical_hash(path)
        if current_hash != artifact.physical_hash:
            raise ArtifactReadError(
                f"Artifact {artifact.artifact_id!r} physical hash mismatch for {artifact.path!r}: "
                f"metadata has {artifact.physical_hash}, file has {current_hash}. "
                "The artifact file was modified after registration."
            )
