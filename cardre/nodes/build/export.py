from __future__ import annotations

import json  # noqa: F401 — imported for monkeypatch/patch compatibility in tests
from dataclasses import asdict
from typing import Any, cast

from cardre._evidence.kinds import AmbiguousEvidenceError, EvidenceKind, EvidenceNotFoundError
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_TECHNICAL_MANIFEST_INDEX
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.plan_repo import PlanRepository
from cardre.store.project_repo import ProjectRepository
from cardre.store.run_step_repo import RunStepRepository


class TechnicalManifestExportNode(NodeType):
    node_type = "cardre.technical_manifest_export"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["definition", "report"]
    output_roles: list[str] = ["manifest"]

    def _read_single_step_evidence(
        self,
        store: Any,
        reader: ArtifactEvidenceReader,
        run_step: Any,
        kinds: tuple[EvidenceKind, ...],
    ) -> tuple[Any, Any]:
        matches: dict[str, tuple[Any, Any]] = {}
        output_artifact_ids = ArtifactRepository(store).output_artifact_ids_for_run_step(
            getattr(run_step, "run_step_id", ""),
        )
        for kind in kinds:
            for artifact_id in output_artifact_ids:
                if artifact_id in matches:
                    continue
                evidence = reader.read_optional(artifact_id, kind)
                if evidence is None:
                    continue
                artifact = ArtifactRepository(store).get(artifact_id)
                if artifact is not None:
                    matches[artifact_id] = (evidence, artifact)

        if not matches:
            raise EvidenceNotFoundError(
                kinds[0],
                step_id=getattr(run_step, "step_id", None),
                candidate_artifact_ids=output_artifact_ids,
            )
        if len(matches) > 1:
            raise AmbiguousEvidenceError(
                kinds[0],
                [artifact for _, artifact in matches.values()],
                step_id=getattr(run_step, "step_id", None),
            )
        return next(iter(matches.values()))

    def _evidence_payload(self, evidence: Any) -> dict[str, Any]:
        if hasattr(evidence, "to_dict"):
            return cast(dict[str, Any], evidence.to_dict())
        if hasattr(evidence, "__dataclass_fields__"):
            return asdict(evidence)
        return cast(dict[str, Any], evidence.to_model_dict())

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        run_id = context.run_id
        plan_version_id = context.plan_version_id

        plan_version = PlanRepository(store).get_version(plan_version_id)
        plan = None
        project = None
        if plan_version:
            plan_id = PlanRepository(store).get_plan_id_for_version(plan_version_id)
            if plan_id:
                plan = PlanRepository(store).get_plan(plan_id)
                if plan:
                    project = ProjectRepository(store).get(plan["project_id"])

        all_run_steps = RunStepRepository(store).get_for_run(run_id)

        steps_evidence: list[dict[str, Any]] = []
        artifacts_evidence: list[dict[str, Any]] = []
        all_warnings: list[dict[str, Any]] = []
        all_errors: list[dict[str, Any]] = []

        seen_artifact_ids: set[str] = set()
        for rs in all_run_steps:
            output_artifact_ids = ArtifactRepository(store).output_artifact_ids_for_run_step(rs.run_step_id)
            step_info = {
                "step_id": rs.step_id,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "status": rs.status.value if hasattr(rs.status, "value") else rs.status,
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "input_artifact_logical_hashes": rs.execution_fingerprint.get("input_artifact_logical_hashes", []),
                "output_artifact_logical_hashes": rs.execution_fingerprint.get("output_artifact_logical_hashes", []),
            }
            steps_evidence.append(step_info)

            for aid in output_artifact_ids:
                if aid in seen_artifact_ids:
                    continue
                seen_artifact_ids.add(aid)
                art = ArtifactRepository(store).get(aid)
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

        modelling_metadata: dict[str, Any] = {}
        selected_variables: list[str] = []
        model_artifact_data: dict[str, Any] = {}
        scorecard_artifact_data: dict[str, Any] = {}
        validation_metrics_data: dict[str, Any] = {}
        cutoff_data: dict[str, Any] = {}
        found_modelling_metadata = None
        found_selection = None
        found_model = None
        found_scorecard = None
        found_validation = None
        found_cutoff = None

        for rs in all_run_steps:
            node_type = rs.execution_fingerprint.get("node_type", "")
            if node_type == "cardre.define_modelling_metadata":
                evidence, art = self._read_single_step_evidence(
                    store, reader, rs, (EvidenceKind.MODELLING_METADATA,),
                )
                if found_modelling_metadata is not None and found_modelling_metadata.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.MODELLING_METADATA,
                        [found_modelling_metadata, art],
                        step_id=rs.step_id,
                    )
                found_modelling_metadata = art
                modelling_metadata = self._evidence_payload(evidence)
            elif node_type == "cardre.variable_selection":
                evidence, art = self._read_single_step_evidence(
                    store, reader, rs, (EvidenceKind.SELECTION_DEFINITION,),
                )
                if found_selection is not None and found_selection.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.SELECTION_DEFINITION,
                        [found_selection, art],
                        step_id=rs.step_id,
                    )
                found_selection = art
                selection_data = self._evidence_payload(evidence)
                selected_variables = list(selection_data.get("selected", []))
            elif node_type in ("cardre.logistic_regression", "cardre.decision_tree_classifier"):
                evidence, art = self._read_single_step_evidence(
                    store, reader, rs, (EvidenceKind.MODEL_ARTIFACT,),
                )
                if found_model is not None and found_model.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.MODEL_ARTIFACT,
                        [found_model, art],
                        step_id=rs.step_id,
                    )
                found_model = art
                model_artifact_data = self._evidence_payload(evidence)
            elif node_type == "cardre.score_scaling":
                evidence, art = self._read_single_step_evidence(
                    store, reader, rs, (EvidenceKind.SCORE_SCALING,),
                )
                if found_scorecard is not None and found_scorecard.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.SCORE_SCALING,
                        [found_scorecard, art],
                        step_id=rs.step_id,
                    )
                found_scorecard = art
                scorecard_artifact_data = self._evidence_payload(evidence)
            elif node_type == "cardre.validation_metrics":
                evidence, art = self._read_single_step_evidence(
                    store,
                    reader,
                    rs,
                    (EvidenceKind.VALIDATION_EVIDENCE, EvidenceKind.VALIDATION_METRICS),
                )
                if found_validation is not None and found_validation.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.VALIDATION_EVIDENCE,
                        [found_validation, art],
                        step_id=rs.step_id,
                    )
                found_validation = art
                validation_metrics_data = self._evidence_payload(evidence)
            elif node_type == "cardre.cutoff_analysis":
                evidence, art = self._read_single_step_evidence(
                    store, reader, rs, (EvidenceKind.CUTOFF_ANALYSIS,),
                )
                if found_cutoff is not None and found_cutoff.artifact_id != art.artifact_id:
                    raise AmbiguousEvidenceError(
                        EvidenceKind.CUTOFF_ANALYSIS,
                        [found_cutoff, art],
                        step_id=rs.step_id,
                    )
                found_cutoff = art
                cutoff_data = self._evidence_payload(evidence)

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
            metadata={"run_id": run_id, "plan_version_id": plan_version_id, "schema_version": SCHEMA_TECHNICAL_MANIFEST_INDEX},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"step_count": len(steps_evidence), "artifact_count": len(artifacts_evidence)})
