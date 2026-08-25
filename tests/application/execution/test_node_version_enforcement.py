"""Node-version enforcement tests — persisted node_version must match the running implementation."""

from __future__ import annotations

from cardre.application.execution.step_runner import StepRunner
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import NodeVersionMismatchError
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec


def _spec(step_id: str, node_type: str, version: str) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version=version,
        category="transform",
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=[],
        canonical_step_id=step_id,
    )


class TestNodeVersionEnforcement:
    def test_import_dataset_node_is_version_1(self):
        cat = build_default_catalogue()
        assert cat.resolve("cardre.import_dataset").node_definition().version == "1"

    def test_mismatched_version_fails_step_before_execution(self):
        cat = build_default_catalogue()
        runner = StepRunner(cat, lambda: None, lambda: (None, None))
        bad_spec = _spec("s1", "cardre.import_dataset", "99")
        result = runner.run_step("pv-1", "run-1", bad_spec, {}, {})

        assert result.status == RunStepStatus.FAILED, "mismatched version must fail the step"
        assert result.errors, "failed step must carry an error entry"
        assert result.errors[0]["code"] == "NODE_VERSION_MISMATCH"
        assert "99" in result.errors[0]["message"]
        assert "1" in result.errors[0]["message"]

    def test_mismatch_error_class_surfaces_version_context(self):
        err = NodeVersionMismatchError(
            step_id="s1", node_type="cardre.import_dataset", persisted="99", current="1",
        )
        assert err.code == "NODE_VERSION_MISMATCH"
        assert err.persisted_version == "99"
        assert err.current_version == "1"
        assert err.context["step_id"] == "s1"
        assert err.context["persisted_version"] == "99"
        assert err.context["current_version"] == "1"

    def test_from_mismatches_builds_error(self):
        err = NodeVersionMismatchError.from_mismatches([
            {"step_id": "s1", "node_type": "cardre.import_dataset",
             "persisted_version": "99", "current_version": "1"},
            {"step_id": "s2", "node_type": "cardre.import_dataset",
             "persisted_version": "2", "current_version": "1"},
        ])
        assert err.code == "NODE_VERSION_MISMATCH"
        assert err.step_id == "s1"
        assert err.persisted_version == "99"
        assert err.current_version == "1"
        assert "s2" in err.message
        assert "s2" in str(err)
        assert err.context["mismatches"][1]["step_id"] == "s2"
