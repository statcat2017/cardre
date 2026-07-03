"""Execution fingerprint construction for RunStep.

Pure data construction from StepSpec, RunStep, and ArtifactRef.
No ProjectStore, no orchestration.
"""

from __future__ import annotations

import sys
from typing import Any

from cardre._version import __version__ as CARDRE_VERSION
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.run import RunStep
from cardre.domain.step import StepSpec


def output_logical_hashes(rs: RunStep) -> list[str]:
    """Extract output logical hashes from a run step's execution fingerprint."""
    return rs.execution_fingerprint.get("output_artifact_logical_hashes", [])


def build_parent_output_hashes(
    parent_run_steps: list[RunStep],
) -> dict[str, list[str]]:
    """Build a mapping of step_id -> output logical hashes for parent steps."""
    return {rs.step_id: output_logical_hashes(rs) for rs in parent_run_steps}


def build_execution_fingerprint(
    plan_version_id: str,
    spec: StepSpec,
    parent_run_steps: list[RunStep],
    input_artifacts: list[ArtifactRef],
    output_artifacts: list[ArtifactRef],
) -> dict[str, Any]:
    """Construct the execution fingerprint dict for a run step.

    This is execution metadata only — node_type, node_version, params_hash,
    code_version, library_versions. Staleness and lineage read from
    ``evidence_edges`` + ``evidence_artifacts`` + params hashes, not this
    column.
    """
    return {
        "plan_version_id": plan_version_id,
        "step_id": spec.step_id,
        "node_type": spec.node_type,
        "node_version": spec.node_version,
        "params_hash": spec.params_hash,
        "parent_run_step_ids": [rs.run_step_id for rs in parent_run_steps],
        "input_artifact_logical_hashes": [a.logical_hash for a in input_artifacts],
        "output_artifact_logical_hashes": [a.logical_hash for a in output_artifacts],
        "parent_output_logical_hashes_by_step": build_parent_output_hashes(parent_run_steps),
        "python_version": sys.version.split()[0],
        "cardre_version": CARDRE_VERSION,
    }


__all__ = [
    "build_execution_fingerprint",
    "build_parent_output_hashes",
    "output_logical_hashes",
]
