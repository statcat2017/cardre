"""Execution fingerprint construction for RunStepRecord.

Pure data construction from StepSpec, RunStepRecord, and ArtifactRef.
No ProjectStore, no orchestration.
"""
from __future__ import annotations

import sys
from typing import Any

from cardre.audit import ArtifactRef, RunStepRecord, StepSpec

CARDRE_VERSION = "0.1.0"


def output_logical_hashes(rs: RunStepRecord) -> list[str]:
    return rs.execution_fingerprint.get("output_artifact_logical_hashes", [])


def build_parent_output_hashes(
    parent_run_steps: list[RunStepRecord],
) -> dict[str, list[str]]:
    return {rs.step_id: output_logical_hashes(rs) for rs in parent_run_steps}


def build_execution_fingerprint(
    plan_version_id: str,
    spec: StepSpec,
    parent_run_steps: list[RunStepRecord],
    input_artifacts: list[ArtifactRef],
    output_artifacts: list[ArtifactRef],
) -> dict[str, Any]:
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
