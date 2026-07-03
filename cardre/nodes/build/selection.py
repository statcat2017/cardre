from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_SELECTION_DEFINITION
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes.build.selection_policy import (
    ClusterPolicy,
    ManualOverridePolicy,
    NoClusterPolicy,
    RepresentativePolicy,
)
from cardre.nodes.contracts import NodeType


class VariableSelectionNode(NodeType):
    node_type = "cardre.variable_selection"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["report"]
    output_roles: list[str] = ["definition"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Variable Selection",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="min_iv", label="Minimum IV",
                            kind="float", default=0.02,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Minimum Information Value threshold for variable inclusion",
                        ),
                        ParameterDefinition(
                            name="max_variables", label="Max Variables",
                            kind="integer", default=15,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of variables to select",
                        ),
                        ParameterDefinition(
                            name="manual_includes", label="Manual Includes",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'variable' and 'reason' keys for forced inclusions",
                        ),
                        ParameterDefinition(
                            name="manual_excludes", label="Manual Excludes",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'variable' and 'reason' keys for forced exclusions",
                        ),
                        ParameterDefinition(
                            name="cluster_representative_rule", label="Cluster Representative Rule",
                            kind="enum", default="none",
                            constraint=ParameterConstraint(
                                enum_values=[
                                    "none",
                                    "one_per_cluster_highest_iv",
                                    "one_per_cluster_lowest_missing",
                                    "manual_override",
                                ],
                            ),
                            help_text="How to use variable clustering evidence for representative selection",
                        ),
                        ParameterDefinition(
                            name="cluster_representative_overrides", label="Cluster Representative Overrides",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'cluster_id', 'variable', and 'reason' keys for manual override of cluster representatives",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        cluster_rule = params.get("cluster_representative_rule", "none")
        valid_rules = {"none", "one_per_cluster_highest_iv", "one_per_cluster_lowest_missing", "manual_override"}
        if cluster_rule not in valid_rules:
            errors.append(
                f"Unknown cluster_representative_rule {cluster_rule!r}; "
                f"valid values: {', '.join(sorted(valid_rules))}"
            )

        for key in ("manual_includes", "manual_excludes"):
            for entry in list(params.get(key, [])):
                if not isinstance(entry, dict):
                    errors.append(f"Each entry in {key} must be a dict with 'variable' and 'reason'")
                    continue
                if not entry.get("variable"):
                    errors.append(f"Entry in {key} missing 'variable'")
                if not entry.get("reason"):
                    errors.append(f"Entry in {key} for '{entry.get('variable', '')}' missing 'reason'")

        overrides = list(params.get("cluster_representative_overrides", []))
        for entry in overrides:
            if not isinstance(entry, dict):
                errors.append("Each cluster_representative_override must be a dict")
                continue
            if not entry.get("cluster_id"):
                errors.append("cluster_representative_override missing 'cluster_id'")
            if not entry.get("variable"):
                errors.append("cluster_representative_override missing 'variable'")
            if not entry.get("reason"):
                errors.append(f"cluster_representative_override for '{entry.get('variable', '')}' missing 'reason'")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_variables = int(params.get("max_variables", 15))
        manual_entries_raw = list(params.get("manual_includes", []))
        manual_excludes_raw = list(params.get("manual_excludes", []))
        cluster_rule = params.get("cluster_representative_rule", "none")
        cluster_overrides_raw = list(params.get("cluster_representative_overrides", []))

        for entry in manual_entries_raw + manual_excludes_raw:
            if isinstance(entry, str):
                raise ValueError(
                    f"Manual include/exclude entry {entry!r} must be a dict "
                    f"with 'variable' and 'reason' keys"
                )
            if not entry.get("variable"):
                raise ValueError("Manual include/exclude entry missing 'variable'")
            if not entry.get("reason"):
                raise ValueError(
                    f"Manual include/exclude for variable {entry.get('variable')!r} "
                    f"requires a non-empty 'reason'"
                )
        manual_includes = {v["variable"]: v["reason"] for v in manual_entries_raw}
        manual_excludes = {v["variable"]: v["reason"] for v in manual_excludes_raw}

        iv_table = reader.find(context.input_artifacts, EvidenceKind.IV_TABLE)
        iv_map: dict[str, float] = {}
        iv_df = iv_table.dataframe.collect()
        for row in iv_df.iter_rows():
            iv_map[str(row[0])] = float(row[1])

        clustering_evidence = reader.find_optional(context.input_artifacts, EvidenceKind.VARIABLE_CLUSTERING)
        clusters: list[dict[str, Any]] = []
        if clustering_evidence is not None:
            for cl in clustering_evidence.clusters:
                clusters.append({
                    "cluster_id": cl.cluster_id,
                    "variables": [str(member.variable) for member in cl.variables],
                })

        cluster_map: dict[str, str] = {}
        cluster_member_metrics: dict[tuple[str, str], dict[str, float | None]] = {}
        for cl in clusters:
            for var in cl.get("variables", []):
                cluster_map[var] = cl["cluster_id"]
            if clustering_evidence is not None:
                for ev_cl in clustering_evidence.clusters:
                    if ev_cl.cluster_id == cl["cluster_id"]:
                        for m in ev_cl.variables:
                            cluster_member_metrics[(cl["cluster_id"], m.variable)] = {
                                "iv": m.iv,
                                "missing_rate": m.missing_rate,
                            }
                        break

        cluster_vars: dict[str, list[str]] = {}
        for cl in clusters:
            cid = cl["cluster_id"]
            vars_in_cluster = list(cl.get("variables", []))
            vars_in_cluster.sort(key=lambda v: iv_map.get(v, 0.0), reverse=True)
            cluster_vars[cid] = vars_in_cluster

        cluster_overrides: dict[str, dict[str, str]] = {}
        for entry in cluster_overrides_raw:
            cid = entry["cluster_id"]
            cluster_overrides.setdefault(cid, {})[entry["variable"]] = entry["reason"]

        candidates = sorted(iv_map.keys(), key=lambda v: iv_map[v], reverse=True)
        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen_clusters: set[str] = set()
        cluster_decisions: list[dict[str, Any]] = []

        for var in candidates:
            if var in manual_excludes:
                rejected.append({"variable": var, "reason": manual_excludes[var]})

        # Select the cluster policy for this run
        policy_map = {
            "none": NoClusterPolicy(),
            "one_per_cluster_highest_iv": RepresentativePolicy("one_per_cluster_highest_iv"),
            "one_per_cluster_lowest_missing": RepresentativePolicy("one_per_cluster_lowest_missing"),
            "manual_override": ManualOverridePolicy(),
        }
        policy: ClusterPolicy = policy_map.get(cluster_rule, NoClusterPolicy())  # type: ignore[assignment]  # dict.get returns Optional, but we have a default

        # Cluster preselection: run policy per cluster
        for cl in clusters:
            cid = cl["cluster_id"]
            vars_in_cluster = cluster_vars.get(cid, [])
            eligible = [v for v in vars_in_cluster if v not in manual_excludes]
            preselect = policy.preselect(
                cid, vars_in_cluster, eligible,
                cluster_overrides, iv_map, cluster_member_metrics, seen_clusters,
            )
            if preselect is not None and preselect.variable not in seen_clusters:
                entry = {"variable": preselect.variable, "reason": preselect.reason}
                selected.append(entry)
                seen_clusters.add(cid)
                cluster_decisions.append({
                    "cluster_id": cid,
                    "selected_variable": preselect.variable,
                    "reason": preselect.reason,
                    "candidate_variables": preselect.eligible,
                })

        # Shared candidate-selection loop — replaces the three ad-hoc branches
        has_cluster_policy = cluster_rule != "none"
        for var in candidates:
            if not has_cluster_policy and len(selected) >= max_variables:
                rejected.append({"variable": var, "reason": f"Reached max_variables limit ({max_variables})"})
                continue
            if var in manual_excludes:
                continue
            if var in manual_includes and var not in [s["variable"] for s in selected]:
                selected.append({"variable": var, "reason": manual_includes[var]})
                continue
            cid = cluster_map.get(var)
            if has_cluster_policy and cid and cid in seen_clusters:
                continue
            if var in [s["variable"] for s in selected]:
                continue
            if var in [r["variable"] for r in rejected]:
                continue
            iv_info_val = iv_map.get(var, 0.0)
            if iv_info_val < min_iv:
                rejected.append({"variable": var, "reason": f"IV {iv_info_val:.4f} below threshold {min_iv}"})
                continue
            if len(selected) >= max_variables:
                rejected.append({"variable": var, "reason": f"Reached max_variables limit ({max_variables})"})
                continue
            selected.append({"variable": var, "reason": f"IV {iv_info_val:.4f} above threshold {min_iv}"})
            if has_cluster_policy and cid and cid not in seen_clusters:
                seen_clusters.add(cid)

        # Post-loop truncation for clustered modes: preselected cluster
        # representatives may have pushed selected past max_variables.
        if has_cluster_policy and len(selected) > max_variables:
            extra_vars = selected[max_variables:]
            selected = selected[:max_variables]
            for ev in extra_vars:
                rejected.append({"variable": ev["variable"], "reason": f"Reached max_variables limit ({max_variables})"})

        selection = {
            "schema_version": SCHEMA_SELECTION_DEFINITION,
            "min_iv": min_iv,
            "max_variables": max_variables,
            "cluster_representative_rule": cluster_rule if cluster_rule != "none" else None,
            "selected": selected,
            "rejected": rejected,
        }
        if cluster_decisions:
            selection["cluster_decisions"] = cluster_decisions

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"variable-selection-{context.step_spec.step_id}",
            payload=selection,
            metadata={
                "selected_count": len(selected),
                "rejected_count": len(rejected),
                "schema_version": SCHEMA_SELECTION_DEFINITION,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)},
        )
