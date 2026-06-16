from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType, json_logical_hash
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind


class TechnicalManifestExportNode(NodeType):
    node_type = "cardre.technical_manifest_export"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["definition", "report"]
    output_roles: list[str] = ["manifest"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        run_id = context.run_id
        plan_version_id = context.plan_version_id

        run = store.get_run(run_id)
        plan_version = store.get_plan_version(plan_version_id)
        plan = None
        project = None
        if plan_version:
            plan_id = store.get_plan_id_for_version(plan_version_id)
            if plan_id:
                plan = store.get_plan(plan_id)
                if plan:
                    project = store.get_project(plan["project_id"])

        all_run_steps = store.get_run_steps(run_id)

        steps_evidence = []
        artifacts_evidence = []
        all_warnings: list[dict] = []
        all_errors: list[dict] = []

        seen_artifact_ids: set[str] = set()
        for rs in all_run_steps:
            step_info = {
                "step_id": rs.step_id,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "status": rs.status,
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "input_artifact_logical_hashes": rs.execution_fingerprint.get("input_artifact_logical_hashes", []),
                "output_artifact_logical_hashes": rs.execution_fingerprint.get("output_artifact_logical_hashes", []),
            }
            steps_evidence.append(step_info)

            for aid in rs.output_artifact_ids:
                if aid in seen_artifact_ids:
                    continue
                seen_artifact_ids.add(aid)
                art = store.get_artifact(aid)
                if art:
                    artifacts_evidence.append({
                        "artifact_id": art.artifact_id,
                        "artifact_type": art.artifact_type,
                        "role": art.role,
                        "physical_hash": art.physical_hash,
                        "logical_hash": art.logical_hash,
                        "media_type": art.media_type,
                    })
            for w in rs.warnings:
                all_warnings.append(dict(w))
            for e in rs.errors:
                all_errors.append(dict(e))

        modelling_metadata = {}
        selected_variables = []
        model_artifact_data: dict = {}
        scorecard_artifact_data: dict = {}
        validation_metrics_data: dict = {}
        cutoff_data: dict = {}

        for rs in all_run_steps:
            node_type = rs.execution_fingerprint.get("node_type", "")
            for aid in rs.output_artifact_ids:
                art = store.get_artifact(aid)
                if art is None:
                    continue
                try:
                    if node_type == "cardre.define_modelling_metadata":
                        modelling_metadata = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.variable_selection":
                        sel = json.loads(store.artifact_path(art).read_text())
                        selected_variables = sel.get("selected", [])
                    elif node_type == "cardre.logistic_regression" and art.artifact_type == "model":
                        model_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.decision_tree_classifier" and art.artifact_type == "model":
                        model_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.score_scaling" and art.artifact_type == "scorecard":
                        scorecard_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.validation_metrics" and art.artifact_type == "report":
                        validation_metrics_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.cutoff_analysis" and art.artifact_type == "report":
                        cutoff_data = json.loads(store.artifact_path(art).read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    pass

        manifest = {
            "project": {
                "project_id": project["project_id"] if project else "",
                "name": project["name"] if project else "",
            } if project else {},
            "run": {
                "run_id": run_id,
                "plan_version_id": plan_version_id,
            },
            "steps": steps_evidence,
            "artifacts": artifacts_evidence,
            "modelling_metadata": modelling_metadata,
            "selected_variables": selected_variables,
            "model": model_artifact_data,
            "scorecard": scorecard_artifact_data,
            "validation_metrics": validation_metrics_data,
            "cutoff_analysis": cutoff_data,
            "warnings": all_warnings,
            "errors": all_errors,
        }

        artifact = write_json_artifact(
            store, artifact_type="manifest", role="manifest",
            stem=f"technical-manifest-{context.step_spec.step_id}",
            payload=manifest,
            metadata={"run_id": run_id, "plan_version_id": plan_version_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"step_count": len(steps_evidence), "artifact_count": len(artifacts_evidence)})
