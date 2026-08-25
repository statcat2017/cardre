"""Clustering evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class ClusterMember:
    variable: str
    iv: float | None = None
    missing_rate: float | None = None


@dataclass(frozen=True)
class VariableCluster:
    cluster_id: str
    variables: list[ClusterMember] = field(default_factory=list)
    representative_suggestion: str | None = None
    representative_reason: str = ""
    max_pairwise_abs_corr: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VariableClusteringEvidence:
    method: str
    input_representation: str = ""
    similarity_metric: str = ""
    threshold: float | None = None
    absolute_correlation: bool = True
    missing_handling: str = "pairwise"
    candidate_limit: int = 50
    minimum_pair_count: int = 30
    representative_rule: str = "highest_iv"
    clusters: list[VariableCluster] = field(default_factory=list)
    singleton_variables: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> VariableClusteringEvidence:
        from cardre.domain.evidence.schemas import SCHEMA_VARIABLE_CLUSTERING_EVIDENCE
        raw_clusters = data.get("clusters", [])
        clusters = []
        for rc in raw_clusters:
            raw_vars = rc.get("variables", [])
            members = []
            for v in raw_vars:
                if isinstance(v, dict):
                    members.append(ClusterMember(
                        variable=v["variable"],
                        iv=v.get("iv"),
                        missing_rate=v.get("missing_rate"),
                    ))
                else:
                    members.append(ClusterMember(variable=str(v)))
            clusters.append(VariableCluster(
                cluster_id=rc.get("cluster_id", ""),
                variables=members,
                representative_suggestion=rc.get("representative_suggestion"),
                representative_reason=rc.get("representative_reason", ""),
                max_pairwise_abs_corr=rc.get("max_pairwise_abs_corr"),
                notes=list(rc.get("notes", [])),
            ))
        return cls(
            method=data.get("method", ""),
            input_representation=data.get("input_representation", ""),
            similarity_metric=data.get("similarity_metric", ""),
            threshold=data.get("threshold"),
            absolute_correlation=data.get("absolute_correlation", True),
            missing_handling=data.get("missing_handling", "pairwise"),
            candidate_limit=data.get("candidate_limit", 50),
            representative_rule=data.get("representative_rule", "highest_iv"),
            minimum_pair_count=data.get("minimum_pair_count", 30),
            clusters=clusters,
            singleton_variables=list(data.get("singleton_variables", [])),
            warnings=list(data.get("warnings", [])),
            schema_version=data.get("schema_version", SCHEMA_VARIABLE_CLUSTERING_EVIDENCE),
            source_artifact_id=artifact_id,
        )
