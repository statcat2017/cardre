from __future__ import annotations

from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.build._automatic_params import (
    automatic_binning_parameter_schema,
    validate_automatic_binning_params,
)
from cardre.nodes.build._fine_classing import run_fine_classing
from cardre.nodes.build._optbinning import _run_optbinning
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)
from cardre.nodes.parameters import NodeParameterSchema


class AutomaticBinningNode(NodeType):
    node_type = "cardre.automatic_binning"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]

    __definition__ = NodeDefinition(
        node_type="cardre.automatic_binning",
        version="1",
        category="fit",
        description="Automatic binning using fine classing or optbinning",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train", kinds=(EvidenceKind.MODELLING_METADATA,)),
                ArtifactRoleSpec("definition", kinds=(EvidenceKind.BIN_DEFINITION,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("definition", kinds=(EvidenceKind.BIN_DEFINITION,)),
                ArtifactRoleSpec("report", required=False),
            ),
        ),
        parameter_schema=automatic_binning_parameter_schema("cardre.automatic_binning", "1"),
    )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return automatic_binning_parameter_schema(cls.node_type, cls.version)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return validate_automatic_binning_params(params)

    def run(self, context: NodeContext) -> NodeResult:
        method = context.params.get("method", "fine_classing")
        if method == "fine_classing":
            return run_fine_classing(context)
        elif method == "optbinning":
            return _run_optbinning(context)
        raise ValueError(f"Unknown binning method: {method!r}")
