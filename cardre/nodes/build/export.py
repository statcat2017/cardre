"""TechnicalManifestExportNode — deferred from Batch 04, ported in Batch 05.

Reads a ``RunSummary`` input artifact produced by ``ExecuteRun`` and
assembles the technical manifest from its step/artifact data.
"""
from __future__ import annotations

from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_TECHNICAL_MANIFEST_INDEX
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class TechnicalManifestExportNode(NodeType):
    node_type = "cardre.technical_manifest_export"
    version = "1"
    category = "transform"

    __definition__ = NodeDefinition(
        node_type="cardre.technical_manifest_export",
        version="1",
        category="transform",
        description="Export technical manifest from run summary",
        input_contract=ArtifactContract(roles=(
            ArtifactRoleSpec("manifest", required=True, kinds=(RoleKind.RUN_SUMMARY,)),
        )),
        output_contract=ArtifactContract(roles=(
            ArtifactRoleSpec("manifest", required=True, kinds=(EvidenceKind.TECHNICAL_MANIFEST_INDEX,), schema_versions=(SCHEMA_TECHNICAL_MANIFEST_INDEX,)),
        )),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        manifest_art = context.inputs.require("manifest", self.node_type)
        summary: dict[str, Any] = context.inputs.read(
            manifest_art, EvidenceKind.RUN_SUMMARY,
        )

        run_id = summary.get("run_id", context.runtime.run_id)
        plan_version_id = summary.get("plan_version_id", context.runtime.plan_version_id)

        raw_steps: list[dict[str, Any]] = summary.get("steps", [])
        raw_artifacts: list[dict[str, Any]] = summary.get("artifacts", [])

        steps_out: list[dict[str, Any]] = []
        for s in raw_steps:
            steps_out.append({
                "step_id": s.get("step_id", ""),
                "node_type": s.get("node_type", ""),
                "node_version": s.get("node_version", ""),
                "status": s.get("status", ""),
                "params_hash": s.get("params_hash", ""),
                "input_artifact_logical_hashes": s.get("input_artifact_logical_hashes", []),
                "output_artifact_logical_hashes": s.get("output_artifact_logical_hashes", []),
            })

        artifacts_out: list[dict[str, Any]] = [
            {
                "artifact_id": a.get("artifact_id", ""),
                "artifact_type": a.get("artifact_type", ""),
                "role": a.get("role", ""),
                "physical_hash": a.get("physical_hash", ""),
                "logical_hash": a.get("logical_hash", ""),
                "media_type": a.get("media_type", ""),
            }
            for a in raw_artifacts
        ]
        # Include the RunSummary input artifact itself. It is a genuinely
        # persisted, run-linked artifact, but it did not exist when the
        # summary payload was assembled (``ExecuteRun._publish_run_summary``
        # registers it after building the summary), so it cannot appear in
        # ``raw_artifacts``. Record it explicitly so the manifest documents
        # every run artifact except the manifest index's own output.
        artifacts_out.append({
            "artifact_id": getattr(manifest_art, "artifact_id", ""),
            "artifact_type": getattr(manifest_art, "artifact_type", ""),
            "role": getattr(manifest_art, "role", ""),
            "physical_hash": getattr(manifest_art, "physical_hash", ""),
            "logical_hash": getattr(manifest_art, "logical_hash", ""),
            "media_type": getattr(manifest_art, "media_type", ""),
        })

        all_warnings: list[dict[str, Any]] = []
        all_errors: list[dict[str, Any]] = []
        for s in raw_steps:
            all_warnings.extend(s.get("warnings", []))
            all_errors.extend(s.get("errors", []))

        manifest_data: dict[str, Any] = {
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "steps": steps_out,
            "artifacts": artifacts_out,
            "warnings": all_warnings,
            "errors": all_errors,
        }

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_TECHNICAL_MANIFEST_INDEX,
            "manifests": [manifest_data],
        }

        context.outputs.publish_json(
            role="manifest",
            kind=EvidenceKind.TECHNICAL_MANIFEST_INDEX,
            payload=payload,
            metadata={"schema_version": SCHEMA_TECHNICAL_MANIFEST_INDEX},
        )

        context.outputs.add_metric("step_count", len(steps_out))
        context.outputs.add_metric("artifact_count", len(artifacts_out))
        return context.outputs.build_result()
