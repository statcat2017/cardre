"""Unit tests for cardre/execution/fingerprints.py — no PlanExecutor needed."""
from __future__ import annotations

import sys

from cardre.audit import ArtifactRef, RunStepRecord, StepSpec, json_logical_hash
from cardre.execution.fingerprints import (
    build_execution_fingerprint,
    build_parent_output_hashes,
    output_logical_hashes,
)


def _spec(step_id="s1", node_type="nt", node_version="1"):
    return StepSpec(step_id=step_id, node_type=node_type, node_version=node_version,
                    category="transform", params={},
                    params_hash=json_logical_hash({}),
                    parent_step_ids=[], branch_label="", position=0)


def _art(role="train", aid="a1", logical_hash="lh1"):
    return ArtifactRef(artifact_id=aid, artifact_type="dataset", role=role,
                       path="p", physical_hash="ph", logical_hash=logical_hash)


def _rs(step_id="p1", output_hashes=None):
    fp = {"output_artifact_logical_hashes": output_hashes or []}
    return RunStepRecord(run_step_id="r1", run_id="run", step_id=step_id,
                         plan_version_id="pv", status="succeeded",
                         started_at="", finished_at="",
                         input_artifact_ids=[], output_artifact_ids=[],
                         execution_fingerprint=fp, warnings=[], errors=[])


class TestBuildExecutionFingerprint:
    def test_contains_all_required_keys(self):
        spec = _spec(step_id="child")
        fp = build_execution_fingerprint("pv1", spec, [], [], [])
        for k in ["plan_version_id", "step_id", "node_type", "node_version",
                   "params_hash", "parent_run_step_ids",
                   "input_artifact_logical_hashes",
                   "output_artifact_logical_hashes",
                   "parent_output_logical_hashes_by_step",
                   "python_version", "cardre_version"]:
            assert k in fp, f"Missing key: {k}"

    def test_plan_version_id_and_step_id(self):
        fp = build_execution_fingerprint("pv1", _spec(), [], [], [])
        assert fp["plan_version_id"] == "pv1"
        assert fp["step_id"] == "s1"

    def test_node_type_and_version(self):
        spec = _spec(node_type="my.node", node_version="2")
        fp = build_execution_fingerprint("pv", spec, [], [], [])
        assert fp["node_type"] == "my.node"
        assert fp["node_version"] == "2"

    def test_params_hash(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["params_hash"] == json_logical_hash({})

    def test_parent_run_step_ids_with_parents(self):
        parent_rs = _rs(step_id="p1")
        fp = build_execution_fingerprint("pv", _spec(), [parent_rs], [], [])
        assert fp["parent_run_step_ids"] == ["r1"]

    def test_input_artifact_logical_hashes(self):
        arts = [_art(logical_hash="lh_in")]
        fp = build_execution_fingerprint("pv", _spec(), [], arts, [])
        assert fp["input_artifact_logical_hashes"] == ["lh_in"]

    def test_output_artifact_logical_hashes(self):
        arts = [_art(logical_hash="lh_out")]
        fp = build_execution_fingerprint("pv", _spec(), [], [], arts)
        assert fp["output_artifact_logical_hashes"] == ["lh_out"]

    def test_parent_output_logical_hashes_by_step(self):
        parent_rs = _rs(step_id="p1", output_hashes=["h1", "h2"])
        fp = build_execution_fingerprint("pv", _spec(), [parent_rs], [], [])
        assert fp["parent_output_logical_hashes_by_step"] == {"p1": ["h1", "h2"]}

    def test_python_version(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["python_version"] == sys.version.split()[0]

    def test_cardre_version(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["cardre_version"] == "0.1.0"

    def test_empty_parent_lists(self):
        fp = build_execution_fingerprint("pv", _spec(), [], [], [])
        assert fp["parent_run_step_ids"] == []
        assert fp["parent_output_logical_hashes_by_step"] == {}


class TestOutputLogicalHashes:
    def test_returns_list_from_fingerprint(self):
        rs = _rs(output_hashes=["h1", "h2"])
        assert output_logical_hashes(rs) == ["h1", "h2"]

    def test_returns_empty_list_when_missing(self):
        rs = RunStepRecord(run_step_id="r1", run_id="run", step_id="s1",
                           plan_version_id="pv", status="succeeded",
                           started_at="", finished_at="",
                           input_artifact_ids=[], output_artifact_ids=[],
                           execution_fingerprint={}, warnings=[], errors=[])
        assert output_logical_hashes(rs) == []


class TestBuildParentOutputHashes:
    def test_maps_step_id_to_hashes(self):
        rs1 = _rs(step_id="p1", output_hashes=["h1"])
        rs2 = _rs(step_id="p2", output_hashes=["h2", "h3"])
        result = build_parent_output_hashes([rs1, rs2])
        assert result == {"p1": ["h1"], "p2": ["h2", "h3"]}

    def test_empty_input_returns_empty_dict(self):
        assert build_parent_output_hashes([]) == {}
