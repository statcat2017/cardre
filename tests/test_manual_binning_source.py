"""Tests for generalised binning source detection in ManualBinningService.

Verifies that the service can resolve both ``"binning"`` and ``"fine-classing"``
canonical step IDs as upstream binning sources.
"""

from __future__ import annotations

import pytest

from cardre.audit import StepSpec
from cardre.services.step_topology import (
    BINNING_SOURCE_CANONICAL_IDS,
    AmbiguousBranchAncestorError,
    find_nearest_binning_source,
)
from cardre.services.manual_binning_service import ManualBinningService


class TestFindNearestBinningSource:
    """Unit tests for the generalised binning source lookup."""

    def test_matches_binning_canonical(self):
        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={}, params_hash="a",
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="binning", node_type="cardre.binning",
                node_version="1", category="fit",
                params={"method": "fine_classing"},
                params_hash="b",
                parent_step_ids=["import"], branch_label="", position=1,
                canonical_step_id="binning",
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="c",
                parent_step_ids=["binning"], branch_label="", position=2,
                canonical_step_id="manual-binning",
            ),
        ]
        branch_map = [{"step_id": s.step_id} for s in steps]
        result = find_nearest_binning_source(steps, "manual-binning", branch_map)
        assert result is not None
        assert result.canonical_step_id == "binning"
        assert result.step_id == "binning"

    def test_matches_fine_classing_as_fallback(self):
        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={}, params_hash="a",
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="fine-classing", node_type="cardre.fine_classing",
                node_version="1", category="fit",
                params={"max_bins": 20},
                params_hash="b",
                parent_step_ids=["import"], branch_label="", position=1,
                canonical_step_id="fine-classing",
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="c",
                parent_step_ids=["fine-classing"], branch_label="", position=2,
                canonical_step_id="manual-binning",
            ),
        ]
        branch_map = [{"step_id": s.step_id} for s in steps]
        result = find_nearest_binning_source(steps, "manual-binning", branch_map)
        assert result is not None
        assert result.canonical_step_id == "fine-classing"
        assert result.step_id == "fine-classing"

    def test_returns_none_when_no_binning_source(self):
        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={}, params_hash="a",
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="2", category="transform",
                params={}, params_hash="b",
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="c",
                parent_step_ids=["split"], branch_label="", position=2,
                canonical_step_id="manual-binning",
            ),
        ]
        branch_map = [{"step_id": s.step_id} for s in steps]
        result = find_nearest_binning_source(steps, "manual-binning", branch_map)
        assert result is None

    def test_constant_has_expected_ids(self):
        assert "binning" in BINNING_SOURCE_CANONICAL_IDS
        assert "fine-classing" in BINNING_SOURCE_CANONICAL_IDS

    def test_ambiguous_ancestor_propagates_error(self):
        """AmbiguousBranchAncestorError is not swallowed by find_nearest_binning_source.
        Two binning steps at same depth and position from target = ambiguous."""
        steps = [
            StepSpec(
                step_id="branch-1-binning", node_type="cardre.binning",
                node_version="1", category="fit",
                params={"method": "fine_classing"}, params_hash="a",
                parent_step_ids=["import"], branch_label="", position=1,
                canonical_step_id="binning",
            ),
            StepSpec(
                step_id="branch-2-binning", node_type="cardre.binning",
                node_version="1", category="fit",
                params={"method": "optbinning"}, params_hash="b",
                parent_step_ids=["import"], branch_label="", position=1,
                canonical_step_id="binning",
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="c",
                parent_step_ids=["branch-1-binning", "branch-2-binning"],
                branch_label="", position=2,
                canonical_step_id="manual-binning",
            ),
        ]
        branch_map = [{"step_id": s.step_id} for s in steps]
        with pytest.raises(AmbiguousBranchAncestorError):
            find_nearest_binning_source(steps, "manual-binning", branch_map)


class TestManualBinningSourceInfoConstruction:
    """The ManualBinningSourceInfo DTO uses new field names."""

    def test_construct_with_binning_fields(self):
        from cardre.services.plan_dto import ManualBinningSourceInfo
        info = ManualBinningSourceInfo(
            binning_step_id="binning",
            binning_artifact_id="art_001",
            binning_method="optbinning",
            variable_selection_step_id="variable-selection",
            variable_selection_artifact_id="art_002",
        )
        assert info.binning_step_id == "binning"
        assert info.binning_artifact_id == "art_001"
        assert info.binning_method == "optbinning"
        assert info.variable_selection_step_id == "variable-selection"
        assert info.variable_selection_artifact_id == "art_002"

    def test_construct_with_fine_classing_method(self):
        from cardre.services.plan_dto import ManualBinningSourceInfo
        info = ManualBinningSourceInfo(
            binning_step_id="binning",
            binning_artifact_id="art_001",
            binning_method="fine_classing",
            variable_selection_step_id="variable-selection",
            variable_selection_artifact_id="art_002",
        )
        assert info.binning_method == "fine_classing"
