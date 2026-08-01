"""Output contract validation — shared pure validator.

Enforces the full declared output contract before any artifact is published:
every staged output must match the role's declared kinds (an ``EvidenceKind``
or ``RoleKind`` token), media types, and expected versioned schema, and a node
with an explicit output contract may not emit undeclared roles. Loose string
kind labels are invalid — a contract that declares a non-typed kind is a
configuration error. An empty contract remains the only opt-out.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.evidence.kinds import EvidenceKind, RoleKind, expand_role_kind
from cardre.nodes.contracts import ArtifactContract


def _kind_value(kind: Any) -> str:
    if isinstance(kind, EvidenceKind):
        return kind.value
    if isinstance(kind, RoleKind):
        return kind.label
    raise TypeError(f"contract kinds must be EvidenceKind or RoleKind, got {kind!r}")


def _declared_kinds(spec: Any) -> set[str]:
    """Return the concrete evidence-kind values a role spec permits.

    ``EvidenceKind`` members map to themselves; ``RoleKind`` tokens expand to
    their declared set. Any other value (e.g. a loose string) is rejected —
    contracts must be machine-checkable.
    """
    allowed: set[str] = set()
    for kind in getattr(spec, "kinds", ()) or ():
        if isinstance(kind, EvidenceKind):
            allowed.add(kind.value)
        elif isinstance(kind, RoleKind):
            allowed.update(k.value for k in expand_role_kind(kind))
        else:
            raise TypeError(
                f"contract kind {kind!r} is not a typed EvidenceKind/RoleKind; "
                "loose string kinds are no longer valid"
            )
    return allowed


def _allowed_media_types(spec: Any) -> set[str]:
    return set(getattr(spec, "media_types", ()) or ())


def _allowed_schema_versions(spec: Any) -> set[str]:
    return set(getattr(spec, "schema_versions", ()) or ())


def _staged_schema_version(staged_artifact: StagedArtifact) -> str:
    """Return the versioned evidence schema carried by a staged artifact.

    The staged ``schema_version`` field holds the evidence kind string; the
    actual versioned schema (e.g. ``cardre.profile_summary.v1``) lives in
    ``metadata["schema_version"]``.
    """
    return str(staged_artifact.metadata.get("schema_version", ""))


def validate_output_contract(
    contract: ArtifactContract,
    staged: Sequence[StagedArtifact],
    *,
    node_type: str = "",
    step_id: str = "",
) -> None:
    """Validate every staged output against the declared output contract.

    Raises ``ValueError`` with a stable, node-agnostic message on the first
    violation. Called before publication, so a failed contract produces no
    artifact object and no DB row.
    """
    specs_by_role = {spec.role: spec for spec in contract.roles}

    # An empty contract is the only opt-out (backward-compat legacy output_roles
    # behave like declared roles without kinds/media constraints).
    declared_roles = set(specs_by_role) | set(contract.output_roles_list)
    if not declared_roles:
        return

    for staged_artifact in staged:
        role_spec = specs_by_role.get(staged_artifact.role)
        if role_spec is None and staged_artifact.role not in contract.output_roles_list:
            raise ValueError(
                f"Step {step_id or '-'} ({node_type or '-'}) emitted undeclared output "
                f"role {staged_artifact.role!r}; declared roles: {sorted(declared_roles)}"
            )

        if role_spec is not None:
            allowed = _declared_kinds(role_spec)
            if allowed and staged_artifact.schema_version not in allowed:
                raise ValueError(
                    f"Step {step_id or '-'} ({node_type or '-'}) output role "
                    f"{staged_artifact.role!r} has kind "
                    f"{staged_artifact.schema_version!r}, but the contract allows "
                    f"{sorted(allowed)}"
                )

            # Media type: enforced when the contract explicitly declares it.
            allowed_media = _allowed_media_types(role_spec)
            if allowed_media and staged_artifact.media_type not in allowed_media:
                raise ValueError(
                    f"Step {step_id or '-'} ({node_type or '-'}) output role "
                    f"{staged_artifact.role!r} has media type "
                    f"{staged_artifact.media_type!r}, but the contract allows "
                    f"{sorted(allowed_media)}"
                )

            # Schema version: enforced when the contract explicitly declares it.
            allowed_schemas = _allowed_schema_versions(role_spec)
            if allowed_schemas and _staged_schema_version(staged_artifact) not in allowed_schemas:
                raise ValueError(
                    f"Step {step_id or '-'} ({node_type or '-'}) output role "
                    f"{staged_artifact.role!r} has schema version "
                    f"{_staged_schema_version(staged_artifact)!r}, but the contract "
                    f"allows {sorted(allowed_schemas)}"
                )

    # Required roles must all be present (legacy required-role enforcement).
    required_roles = {spec.role for spec in contract.roles if spec.required}
    produced_roles = {s.role for s in staged}
    missing = required_roles - produced_roles
    if missing:
        raise ValueError(
            f"Step {step_id or '-'} ({node_type or '-'}) missing required output "
            f"roles: {sorted(missing)}"
        )


__all__ = ["validate_output_contract"]
