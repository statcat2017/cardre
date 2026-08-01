"""Output contract validation — shared pure validator.

Enforces the full declared output contract before any artifact is published:
every staged output must match the role's declared kinds and media types, and
a node with an explicit output contract may not emit undeclared roles. An
empty contract remains the only opt-out.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import ArtifactContract


def _kind_value(kind: Any) -> str:
    return kind.value if isinstance(kind, EvidenceKind) else str(kind)


def _is_evidence_kind(kind: Any) -> bool:
    return isinstance(kind, EvidenceKind)


def _allowed_kinds(spec: Any) -> set[str]:
    """Return the machine-checkable kind constraints.

    Only actual ``EvidenceKind`` values are enforced; loose string labels
    (e.g. ``("dataset",)``) are documentation and are not a checkable kind
    constraint.
    """
    return {_kind_value(k) for k in getattr(spec, "kinds", ()) or () if _is_evidence_kind(k)}


def _declares_checkable_kinds(spec: Any) -> bool:
    return any(_is_evidence_kind(k) for k in getattr(spec, "kinds", ()) or ())


def _allowed_media_types(spec: Any) -> set[str]:
    return set(getattr(spec, "media_types", ()) or ())


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
            if _declares_checkable_kinds(role_spec):
                allowed = _allowed_kinds(role_spec)
                if staged_artifact.schema_version not in allowed:
                    raise ValueError(
                        f"Step {step_id or '-'} ({node_type or '-'}) output role "
                        f"{staged_artifact.role!r} has kind "
                        f"{staged_artifact.schema_version!r}, but the contract allows "
                        f"{sorted(allowed)}"
                    )
            allowed_media = _allowed_media_types(role_spec)
            if allowed_media and staged_artifact.media_type not in allowed_media:
                raise ValueError(
                    f"Step {step_id or '-'} ({node_type or '-'}) output role "
                    f"{staged_artifact.role!r} has media type "
                    f"{staged_artifact.media_type!r}, but the contract allows "
                    f"{sorted(allowed_media)}"
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
