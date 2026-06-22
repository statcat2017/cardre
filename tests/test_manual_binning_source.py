"""Tests for generalised binning source detection in ManualBinningService.

Verifies that the service can resolve both ``"binning"`` and ``"fine-classing"``
canonical step IDs as upstream binning sources.
"""

from __future__ import annotations

import pytest

from cardre.audit import RunStepRecord, StepSpec
from cardre.evidence import BinDefinition, BinVariable, EvidenceKind, SelectionDefinition, SelectedVariable
import cardre.services.manual_binning_service as manual_binning_service
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


class TestManualBinningServiceEvidenceReads:
    def test_resolve_upstream_defs_uses_typed_evidence(self, monkeypatch):
        reader_calls: list[tuple[str, EvidenceKind]] = []

        class FakeStore:
            def get_latest_successful_run_step_for_step(self, plan_version_id, step_id, branch_id=None):
                return None

            def get_latest_successful_run_id(self, plan_version_id):
                return "run-1"

            def get_latest_successful_run_id_for_plan(self, plan_id):
                return "run-1"

            def get_run_steps(self, run_id):
                return [
                    RunStepRecord(
                        run_step_id="rs-bin",
                        run_id=run_id,
                        step_id="binning",
                        plan_version_id="pv-1",
                        status="succeeded",
                        started_at="2024-01-01T00:00:00+00:00",
                        finished_at="2024-01-01T00:00:01+00:00",
                        input_artifact_ids=[],
                        output_artifact_ids=["art-bin"],
                        execution_fingerprint={},
                        warnings=[],
                        errors=[],
                    ),
                    RunStepRecord(
                        run_step_id="rs-sel",
                        run_id=run_id,
                        step_id="variable-selection",
                        plan_version_id="pv-1",
                        status="succeeded",
                        started_at="2024-01-01T00:00:00+00:00",
                        finished_at="2024-01-01T00:00:01+00:00",
                        input_artifact_ids=[],
                        output_artifact_ids=["art-sel"],
                        execution_fingerprint={},
                        warnings=[],
                        errors=[],
                    ),
                ]

            def get_artifact(self, artifact_id):
                raise AssertionError("service should not read artifacts directly")

            def artifact_path(self, artifact):
                raise AssertionError("service should not use artifact_path directly")

        class FakeArtifactEvidenceReader:
            def __init__(self, store):
                self.store = store

            def read(self, artifact_id, kind):
                reader_calls.append((artifact_id, kind))
                if artifact_id == "art-bin":
                    assert kind is EvidenceKind.BIN_DEFINITION
                    return BinDefinition(
                        variables=[
                            BinVariable(
                                variable="income",
                                dtype="float",
                                kind="numeric",
                                bins=[{"label": "low"}],
                            )
                        ],
                        source_artifact_id=artifact_id,
                    )
                if artifact_id == "art-sel":
                    assert kind is EvidenceKind.SELECTION_DEFINITION
                    return SelectionDefinition(
                        selected=[SelectedVariable(variable="income", reason="kept")],
                        method="correlation",
                        source_artifact_id=artifact_id,
                    )
                raise AssertionError(f"unexpected artifact read: {artifact_id}")

        monkeypatch.setattr(manual_binning_service, "ArtifactEvidenceReader", FakeArtifactEvidenceReader)

        service = manual_binning_service.ManualBinningService(FakeStore())
        (bin_def, sel_def, bin_artifact_id, sel_artifact_id), err = service._resolve_upstream_defs(
            plan_version_id="pv-1",
            plan_id="plan-1",
        )

        assert err is None
        assert bin_artifact_id == "art-bin"
        assert sel_artifact_id == "art-sel"
        assert bin_def == {"variables": [{"variable": "income", "dtype": "float", "kind": "numeric", "bins": [{"label": "low"}]}]}
        assert sel_def == {"selected": [{"variable": "income", "reason": "kept"}], "method": "correlation"}
        assert reader_calls == [
            ("art-bin", EvidenceKind.BIN_DEFINITION),
            ("art-sel", EvidenceKind.SELECTION_DEFINITION),
        ]
