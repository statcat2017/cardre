from __future__ import annotations

from pathlib import Path

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.step_runner import StepRunner
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class _RequiredInputNode(NodeType):
    node_type = "test.required_input"
    version = "1"
    category = "test"
    description = "Declares a required train input that callers may omit"

    __definition__ = NodeDefinition(
        node_type="test.required_input",
        version="1",
        category="test",
        description=description,
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("train", required=True),
                ArtifactRoleSpec("test", required=False),
            ),
        ),
        output_contract=ArtifactContract(roles=()),
    )

    ran = False

    def run(self, context: NodeContext) -> NodeResult:
        type(self).ran = True
        return context.outputs.build_result()


class _Catalogue:
    def availability(self, node_type: str):
        from cardre.bootstrap.node_catalogue import NodeAvailability

        return NodeAvailability(available=True, tier="launch")

    def instantiate(self, node_type: str) -> NodeType:
        _RequiredInputNode.ran = False
        return _RequiredInputNode()


def _runner(tmp_path: Path) -> StepRunner:
    return StepRunner(
        _Catalogue(),
        lambda: FsArtifactStore(tmp_path),
        lambda: (object(), None),
    )


def _spec(step_id: str = "s1") -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="test.required_input",
        node_version="1",
        category="test",
        params={},
        params_hash="params-hash",
        parent_step_ids=[],
        canonical_step_id=step_id,
    )


def test_required_input_missing_fails_step_before_node_run(tmp_path: Path):
    """A node declaring a required input role must not execute when the
    artifact is absent — the framework enforces the contract, not the node."""
    from cardre.domain.run import RunStepStatus

    result = _runner(tmp_path).run_step(
        "plan-1", "run-1", _spec(), {}, {},
    )

    assert result.status == RunStepStatus.FAILED, "step must fail on missing required input"
    assert _RequiredInputNode.ran is False, "node.run() must not be called"
    assert result.errors, "failed step must carry an error entry"
    joined = " ".join(str(e) for e in result.errors)
    assert "required" in joined.lower()
    assert "train" in joined


def test_required_input_present_runs_node(tmp_path: Path):
    """Providing the required artifact lets the node execute."""
    from cardre.domain.artifacts import ArtifactRef

    art = ArtifactRef(
        artifact_id="train-artifact",
        artifact_type="dataset",
        role="train",
        path="objects/x",
        physical_hash="phys",
        logical_hash="log",
        media_type="application/vnd.apache.parquet",
    )
    _runner(tmp_path).run_step(
        "plan-1", "run-1", _spec(), {"s1": [art]}, {},
    )
    assert _RequiredInputNode.ran is True
