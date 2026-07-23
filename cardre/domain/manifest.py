"""Canonical run manifest — domain model and hashing.

Single source of truth for the manifest schema, version, serialization,
and self-referential hash. Both the publisher (writer) and the verifier
(reader) must use these functions so the hash can never drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.diagnostics import JsonDict

MANIFEST_VERSION = "cardre.run_manifest.v1"


@dataclass(frozen=True)
class RunManifestStep:
    step_id: str
    canonical_step_id: str = ""
    branch_id: str | None = None
    node_type: str = ""
    node_version: str = ""
    category: str = ""
    status: str = ""
    action: str = ""
    is_carried_forward: bool = False
    started_at: str = ""
    finished_at: str | None = None
    params: JsonDict = field(default_factory=dict)
    params_hash: str = ""
    parent_step_ids: list[str] = field(default_factory=list)
    input_artifact_ids: list[str] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    errors: list[JsonDict] = field(default_factory=list)
    execution_fingerprint: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "canonical_step_id": self.canonical_step_id,
            "branch_id": self.branch_id,
            "node_type": self.node_type,
            "node_version": self.node_version,
            "category": self.category,
            "status": self.status,
            "action": self.action,
            "is_carried_forward": self.is_carried_forward,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "params": self.params,
            "params_hash": self.params_hash,
            "parent_step_ids": list(self.parent_step_ids),
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "execution_fingerprint": self.execution_fingerprint,
        }


@dataclass(frozen=True)
class RunManifest:
    """Canonical run manifest — the immutable execution record."""

    manifest_version: str = MANIFEST_VERSION
    manifest_hash: str = ""
    run_id: str = ""
    plan_version_id: str = ""
    plan_id: str = ""
    project_id: str = ""
    branch_id: str | None = None
    started_at: str = ""
    finished_at: str | None = None
    status: str = ""
    execution_mode: str = "unknown"
    cardre_version: str = ""
    pathway_hash: str = ""
    artifact_root: str = ""
    in_scope_step_ids: list[str] = field(default_factory=list)
    steps: list[RunManifestStep] = field(default_factory=list)
    diagnostics: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "manifest_version": self.manifest_version,
            "manifest_hash": self.manifest_hash,
            "run_id": self.run_id,
            "plan_version_id": self.plan_version_id,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "branch_id": self.branch_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "cardre_version": self.cardre_version,
            "pathway_hash": self.pathway_hash,
            "artifact_root": self.artifact_root,
            "in_scope_step_ids": list(self.in_scope_step_ids),
            "steps": [s.to_dict() for s in self.steps],
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> RunManifest:
        steps = [RunManifestStep(**s) for s in data.get("steps", [])]
        return cls(
            manifest_version=data.get("manifest_version", MANIFEST_VERSION),
            manifest_hash=data.get("manifest_hash", ""),
            run_id=data.get("run_id", ""),
            plan_version_id=data.get("plan_version_id", ""),
            plan_id=data.get("plan_id", ""),
            project_id=data.get("project_id", ""),
            branch_id=data.get("branch_id"),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at"),
            status=data.get("status", ""),
            execution_mode=data.get("execution_mode", "unknown"),
            cardre_version=data.get("cardre_version", ""),
            pathway_hash=data.get("pathway_hash", ""),
            artifact_root=data.get("artifact_root", ""),
            in_scope_step_ids=list(data.get("in_scope_step_ids", [])),
            steps=steps,
            diagnostics=list(data.get("diagnostics", [])),
        )


def compute_manifest_hash(payload: JsonDict) -> str:
    """Compute the self-referential manifest hash.

    The hash is the SHA-256 of the canonical JSON (sorted keys, compact
    separators) with ``manifest_hash`` set to an empty string. This is
    the only function that should compute or verify the manifest hash.
    """
    copy = dict(payload)
    copy["manifest_hash"] = ""
    return json_logical_hash(copy)


def compute_pathway_hash(steps: list[JsonDict]) -> str:
    """Compute the pathway hash from a list of step dicts.

    The pathway hash is the SHA-256 of the canonical JSON of the
    ordered list of step identity + fingerprint fields. This binds
    the manifest to the exact execution pathway.
    """
    pathway_entries = [
        {
            "step_id": s.get("step_id", ""),
            "canonical_step_id": s.get("canonical_step_id", ""),
            "node_type": s.get("node_type", ""),
            "node_version": s.get("node_version", ""),
            "params_hash": s.get("params_hash", ""),
            "status": s.get("status", ""),
        }
        for s in steps
    ]
    return json_logical_hash({"steps": pathway_entries})


def serialize_manifest(payload: JsonDict) -> str:
    """Serialize a manifest dict to canonical JSON text."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def deserialize_manifest(text: str) -> JsonDict:
    """Deserialize canonical manifest JSON text to a dict."""
    return json.loads(text)


__all__ = [
    "MANIFEST_VERSION",
    "RunManifest",
    "RunManifestStep",
    "compute_manifest_hash",
    "compute_pathway_hash",
    "deserialize_manifest",
    "serialize_manifest",
]
