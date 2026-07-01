"""Unit tests for cardre/execution/validation.py — no PlanExecutor needed."""
from __future__ import annotations

import polars as pl
import pytest

from cardre.audit import ArtifactRef, ExecutionContext, NodeOutput, NodeType, StepSpec
from cardre.errors import ArtifactReadError
from cardre.execution.validation import (
    LEAKAGE_SENSITIVE_CATEGORIES,
    LeakageProtectionError,
    RoleAccessError,
    filter_inputs_by_role,
    validate_input_artifact_files,
    validate_leakage_rules,
    validate_node_input_roles,
    validate_role_access,
)
from tests.helpers import make_store, _make_train_artifact


class _TestNode(NodeType):
    node_type = "test.node"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["out"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        return NodeOutput(artifacts=[], metrics={})


class _TrainNode(_TestNode):
    node_type = "test.train_node"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["train"]


class _NoRolesNode(_TestNode):
    node_type = "test.no_roles"
    input_roles: list[str] = []


class _FitNode(_TestNode):
    node_type = "test.fit"
    category = "fit"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["prediction"]


class _ApplyNode(_TestNode):
    node_type = "test.apply"
    category = "apply"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["prediction"]


class _SelectionNode(_TestNode):
    node_type = "test.selection"
    category = "selection"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["prediction"]


class TestFilterInputsByRole:
    def test_no_roles_returns_all(self):
        arts = [
            ArtifactRef("a1", "dataset", "train", "p", "ph", "lh"),
            ArtifactRef("a2", "dataset", "test", "p", "ph", "lh"),
        ]
        result = filter_inputs_by_role(_NoRolesNode(), arts)
        assert len(result) == 2

    def test_returns_only_permitted(self):
        arts = [
            ArtifactRef("a1", "dataset", "train", "p", "ph", "lh"),
            ArtifactRef("a2", "dataset", "test", "p", "ph", "lh"),
        ]
        result = filter_inputs_by_role(_TrainNode(), arts)
        assert len(result) == 1
        assert result[0].role == "train"

    def test_empty_list(self):
        result = filter_inputs_by_role(_TrainNode(), [])
        assert result == []


class TestValidateRoleAccess:
    def test_no_roles_passes(self):
        spec = StepSpec("s", "nt", "1", "t", {}, "h", [], "", 0)
        validate_role_access(_NoRolesNode(), spec, [], [])  # no raise

    def test_raises_when_parents_exist_but_no_matching(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        raw = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError):
            validate_role_access(node, spec, [], raw)

    def test_raises_when_artifact_has_unpermitted_role(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        filtered = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        raw = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError, match="cannot consume"):
            validate_role_access(node, spec, filtered, raw)

    def test_passes_when_role_matches(self):
        node = _TrainNode()
        spec = StepSpec("s", "nt", "1", "t", {}, "h", ["parent"], "", 0)
        filtered = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        raw = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_role_access(node, spec, filtered, raw)  # no raise


class TestValidateNodeInputRoles:
    def test_raises_on_empty_when_roles_declared(self):
        with pytest.raises(RoleAccessError, match="no artifacts"):
            validate_node_input_roles(_TrainNode(), [])

    def test_raises_on_no_matching_role(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(RoleAccessError, match="No permitted role"):
            validate_node_input_roles(_TrainNode(), arts)

    def test_passes_when_any_role_matches(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_node_input_roles(_TrainNode(), arts)  # no raise

    def test_no_roles_declared_passes(self):
        validate_node_input_roles(_NoRolesNode(), [])  # no raise


class TestValidateLeakageRules:
    def test_blocks_test_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(LeakageProtectionError):
            validate_leakage_rules(_FitNode(), arts)

    def test_blocks_oot_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "oot", "p", "ph", "lh")]
        with pytest.raises(LeakageProtectionError):
            validate_leakage_rules(_FitNode(), arts)

    def test_allows_train_dataset_for_fit(self):
        arts = [ArtifactRef("a1", "dataset", "train", "p", "ph", "lh")]
        validate_leakage_rules(_FitNode(), arts)  # no raise

    def test_skips_non_sensitive_category(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        validate_leakage_rules(_ApplyNode(), arts)  # no raise

    def test_blocks_test_dataset_for_selection(self):
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        with pytest.raises(LeakageProtectionError):
            validate_leakage_rules(_SelectionNode(), arts)

    def test_allows_explicitly_allowed_artifact(self):
        class _CalibNode(_FitNode):
            def allows_leakage_artifact(self, art):
                return True
        arts = [ArtifactRef("a1", "dataset", "test", "p", "ph", "lh")]
        validate_leakage_rules(_CalibNode(), arts)  # no raise


class TestValidateInputArtifactFiles:
    def test_raises_on_missing_file(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        store.artifact_path(art).unlink()
        with pytest.raises(ArtifactReadError):
            validate_input_artifact_files(store, [art])

    def test_raises_on_hash_mismatch(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        store.artifact_path(art).write_text("tampered data")
        with pytest.raises(ArtifactReadError):
            validate_input_artifact_files(store, [art])

    def test_passes_when_file_ok(self):
        store, _ = make_store()
        art = _make_train_artifact(store, pl.DataFrame({"x": [1.0]}), role="train")
        validate_input_artifact_files(store, [art])  # no raise

    def test_empty_artifacts_passes(self):
        store, _ = make_store()
        validate_input_artifact_files(store, [])  # no raise


class TestConstants:
    def test_leakage_sensitive_categories(self):
        assert "fit" in LEAKAGE_SENSITIVE_CATEGORIES
        assert "selection" in LEAKAGE_SENSITIVE_CATEGORIES
        assert "refinement" in LEAKAGE_SENSITIVE_CATEGORIES
        assert "apply" not in LEAKAGE_SENSITIVE_CATEGORIES
        assert "transform" not in LEAKAGE_SENSITIVE_CATEGORIES
