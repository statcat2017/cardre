"""Node contracts: NodeType interface, ArtifactContract, RolePolicy.

``NodeType`` is an executable plugin interface with registry/param-schema
coupling.  It lives here, **not** in ``cardre/domain/``, because domain
must have no plugin-registry dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cardre.execution.context import ExecutionContext, NodeOutput
    from cardre.node_parameters import NodeParameterSchema


@dataclass(frozen=True)
class ArtifactContract:
    """Declares what artifact types and roles a node expects/produces."""
    input_roles: list[str] = field(default_factory=list)
    output_roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RolePolicy:
    """Policy for how a role is treated during evidence resolution."""
    role: str
    allow_reuse: bool = True
    require_fresh: bool = False
    max_age_seconds: int | None = None


class NodeType(ABC):
    """Abstract base for all node types (executable plugin interface)."""

    node_type: str = ""
    version: str = ""
    category: str = ""
    description: str = ""
    optional_dependencies: list[str] | None = None
    _deferred: bool = False

    @abstractmethod
    def run(self, context: ExecutionContext) -> NodeOutput:
        """Execute this node and return its output."""
        ...

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Override for cross-parameter or runtime checks."""
        return []

    @classmethod
    def contract(cls) -> ArtifactContract:
        """Return the artifact contract for this node type."""
        return ArtifactContract(
            input_roles=getattr(cls, "input_roles", []),
            output_roles=getattr(cls, "output_roles", []),
        )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema | None:
        """Return the parameter schema for this node type, or ``None``.

        Nodes that declare a schema benefit from central validation
        (defaults, type coercion, bounds, enums, unknown-key rejection).
        Nodes without a schema fall back to their own ``validate_params``.
        """
        return None


__all__ = ["ArtifactContract", "NodeType", "RolePolicy"]
