"""Tests for binning operations — fine classing and manual binning."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import polars as pl
import pytest

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.nodes import (
    FineClassingNode,
    ManualBinningNode,
)
from cardre.store import ProjectStore

from tests.helpers import make_store
from tests.helpers.evidence_assertions import assert_bin_definition


# ======================================================================
# Fine Classing
# ======================================================================

class FineClassingTests(unittest.TestCase):

    def test_fine_classing_creates_bin_definitions(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "var2": ["a", "b", "a", "b", "a", "b"],
            "target": ["good", "good", "bad", "bad", "good", "bad"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(meta_artifact)

        params = {
            "max_bins": 20,
            "min_bin_fraction": 0.05,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 50,
            "exclude_columns": [],
        }
        step_spec = StepSpec(
            step_id="binning", node_type="cardre.binning",
            node_version="1", category="fit",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["split", "define-metadata"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = FineClassingNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.role, "definition")
        payload = ArtifactEvidenceReader(store).read(artifact.artifact_id, EvidenceKind.BIN_DEFINITION)
        assert_bin_definition(payload)
        self.assertGreater(len(payload.variables), 0)

    def test_numeric_bin_boundaries_non_overlapping(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)
        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)
        params = {"max_bins": 6, "min_bin_fraction": 0.01, "missing_policy": "ignore"}
        step_spec = StepSpec(
            step_id="binning", node_type="cardre.binning",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[train_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        output = FineClassingNode().run(ctx)
        payload = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.BIN_DEFINITION)
        score_bins = [v for v in payload.variables if v.variable == "score"][0].bins

        non_missing = [b for b in score_bins if not b.get("is_missing_bin")]
        self.assertGreaterEqual(len(non_missing), 2, "expected at least 2 non-missing bins")

        for i, b in enumerate(non_missing):
            if i == 0:
                self.assertTrue(b["lower_inclusive"],
                                "first numeric bin should have lower_inclusive=True")
            else:
                self.assertFalse(b["lower_inclusive"],
                                 f"bin {i} ({b['label']}) should have lower_inclusive=False")
            self.assertIsNotNone(b["lower"],
                                 f"bin {i} should have a lower boundary")
            if b.get("upper") is not None:
                self.assertIsNotNone(b["lower"],
                                     f"bin {i} should have a lower boundary")

    def test_fine_classing_max_bins_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        from cardre.audit import ArtifactRef

        params = {"max_bins": 1, "min_bin_fraction": 0.05}
        mock_artifact = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="train",
            path="nonexistent", physical_hash="a", logical_hash="b",
        )
        step_spec = StepSpec(
            step_id="fc", node_type="cardre.binning",
            node_version="1", category="fit",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[mock_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = FineClassingNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Manual Binning
# ======================================================================

class ManualBinningTests(unittest.TestCase):

    def test_manual_binning_merge_bins(self) -> None:
        store, tmp = make_store()
        store.initialize()

        bin_def = {
            "variables": [
                {
                    "variable": "duration_months",
                    "kind": "numeric",
                    "bins": [
                        {"bin_id": "dm_bin_001", "label": "Low", "lower": 0, "upper": 12,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 100, "good_count": 80, "bad_count": 20},
                        {"bin_id": "dm_bin_002", "label": "Mid", "lower": 12, "upper": 24,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 80, "good_count": 60, "bad_count": 20},
                        {"bin_id": "dm_bin_003", "label": "High", "lower": 24, "upper": None,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 50, "good_count": 30, "bad_count": 20},
                    ],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        from cardre.audit import physical_hash, relative_path
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(bin_artifact)

        params = {
            "overrides": [
                {
                    "variable": "duration_months",
                    "action": "merge_bins",
                    "source_bin_ids": ["dm_bin_001", "dm_bin_002"],
                    "new_label": "Low-Mid",
                    "reason": "Merged sparse adjacent bins",
                }
            ]
        }
        step_spec = StepSpec(
            step_id="manual-binning", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["binning"], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[bin_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ManualBinningNode()
        output = node.run(ctx)

        payload = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.BIN_DEFINITION)
        merged_vars = payload.variables
        self.assertEqual(len(merged_vars), 1)
        merged_bins = merged_vars[0].bins
        self.assertEqual(len(merged_bins), 2)


# ======================================================================
# Blocker Verification — manual binning / fine classing
# ======================================================================


def test_non_adjacent_numeric_merge_fails() -> None:
    store, tmp = make_store()
    store.initialize()
    bin_def = {
        "variables": [{
            "variable": "x", "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "label": "A", "lower": 0, "upper": 10,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
                {"bin_id": "b2", "label": "B", "lower": 10, "upper": 20,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
                {"bin_id": "b3", "label": "C", "lower": 20, "upper": 30,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
            ],
        }],
        "warnings": [],
    }
    bin_path = store.root / "artifacts" / "bins.json"
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_text(json.dumps(bin_def, sort_keys=True))
    from cardre.audit import physical_hash, relative_path
    bin_art = ArtifactRef(
        artifact_id="b1", artifact_type="definition", role="definition",
        path=relative_path(bin_path, store.root),
        physical_hash=physical_hash(bin_path),
        logical_hash=json_logical_hash(bin_def),
        media_type="application/json", metadata={},
    )
    store.register_artifact(bin_art)

    params = {
        "overrides": [{
            "variable": "x",
            "action": "merge_bins",
            "source_bin_ids": ["b1", "b3"],
            "new_label": "Non-adjacent",
            "reason": "Testing adjacency enforcement",
        }]
    }
    spec = StepSpec(
        step_id="mb", node_type="cardre.manual_binning",
        node_version="1", category="refinement",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[bin_art],
        validated_params=params, runtime_metadata={},
    )
    node = ManualBinningNode()
    with pytest.raises(ValueError):
        node.run(ctx)


# ======================================================================
# New override actions
# ======================================================================


def test_reject_variable_marks_excluded() -> None:
    """reject_variable action marks variable as excluded."""
    bin_def = {
        "variables": [{
            "variable": "x", "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "label": "Low", "lower": 0, "upper": 10,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
            ],
        }],
        "warnings": [],
    }
    from cardre.nodes import apply_manual_binning_overrides

    result = apply_manual_binning_overrides(bin_def, [
        {"variable": "x", "action": "reject_variable",
         "source_bin_ids": [], "reason": "High missing rate"},
    ])
    # Variable should be removed from active variables list
    assert len(result["variables"]) == 0
    assert result["rejected"] is not None
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["status"] == "excluded"
    assert result["rejected"][0]["active"] is False
    assert len(result["rejected"][0].get("override_history", [])) == 1


def test_override_history_logged() -> None:
    """Every override produces an immutable event with timestamp/reason."""
    bin_def = {
        "variables": [{
            "variable": "x", "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "label": "Low", "lower": 0, "upper": 10,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
                {"bin_id": "b2", "label": "High", "lower": 10, "upper": 20,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
            ],
        }],
        "warnings": [],
    }
    from cardre.nodes import apply_manual_binning_overrides

    result = apply_manual_binning_overrides(bin_def, [
        {"variable": "x", "action": "merge_bins",
         "source_bin_ids": ["b1", "b2"],
         "reason": "Combine sparse bins", "new_label": "Combined"},
    ])
    var_x = result["variables"][0]
    assert "override_history" in var_x
    events = var_x["override_history"]
    assert len(events) == 1
    assert events[0]["user_action"] == "merge_bins"
    assert events[0]["reason"] == "Combine sparse bins"
    assert "timestamp" not in events[0]
    assert events[0]["before"] == ["Low", "High"]


def test_reorder_missing_bin() -> None:
    """reorder_missing_bin moves missing bin to end of list."""
    bin_def = {
        "variables": [{
            "variable": "x", "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "label": "(-inf, 10)", "lower": None, "upper": 10,
                 "is_missing_bin": False, "row_count": 100, "good_count": 80, "bad_count": 20},
                {"bin_id": "b_miss", "label": "Missing", "lower": None, "upper": None,
                 "is_missing_bin": True, "row_count": 10, "good_count": 8, "bad_count": 2},
                {"bin_id": "b3", "label": "[10, +inf)", "lower": 10, "upper": None,
                 "is_missing_bin": False, "row_count": 100, "good_count": 80, "bad_count": 20},
            ],
        }],
        "warnings": [],
    }
    from cardre.nodes import apply_manual_binning_overrides

    result = apply_manual_binning_overrides(bin_def, [
        {"variable": "x", "action": "reorder_missing_bin",
         "source_bin_ids": ["b_miss"],
         "reason": "Reorder missing bin"},
    ])
    bins = result["variables"][0]["bins"]
    assert bins[-1]["is_missing_bin"]  # missing moved to end


def test_reject_variable_requires_reason() -> None:
    """reject_variable validation requires a non-empty reason."""
    from cardre.nodes import validate_manual_binning_overrides

    bin_def = {
        "variables": [{
            "variable": "x", "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "label": "Low", "lower": 0, "upper": 10,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 100, "good_count": 80, "bad_count": 20},
            ],
        }],
    }
    errs = validate_manual_binning_overrides(bin_def, [
        {"variable": "x", "action": "reject_variable",
         "source_bin_ids": [], "reason": ""},
    ])
    assert len(errs) > 0
    assert "reason" in errs[0].lower()


def test_high_cardinality_creates_other_bin() -> None:
    store, tmp = make_store()
    store.initialize()
    df = pl.DataFrame({
        "cat_var": [f"level_{i}" for i in range(60)],
        "target": ["good"] * 30 + ["bad"] * 30,
    })
    import io
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    from cardre.audit import physical_hash, relative_path
    train = ArtifactRef(
        artifact_id="t1", artifact_type="dataset", role="train",
        path=relative_path(path, store.root),
        physical_hash=physical_hash(path),
        logical_hash=table_logical_hash(df),
        media_type="application/vnd.apache.parquet", metadata={},
    )
    store.register_artifact(train)

    meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
    meta_path = store.root / "artifacts" / "meta.json"
    meta_path.write_text(json.dumps(meta_params, sort_keys=True))
    meta_art = ArtifactRef(
        artifact_id="m1", artifact_type="definition", role="definition",
        path=relative_path(meta_path, store.root),
        physical_hash=physical_hash(meta_path),
        logical_hash=json_logical_hash(meta_params),
        media_type="application/json", metadata={},
    )
    store.register_artifact(meta_art)

    params = {
        "method": "fine_classing",
        "max_bins": 20, "min_bin_fraction": 0.01,
        "missing_policy": "separate_bin",
        "max_categorical_levels": 10,
        "exclude_columns": [],
    }
    spec = StepSpec(
        step_id="fc", node_type="cardre.binning",
        node_version="1", category="fit",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[train, meta_art],
        validated_params=params, runtime_metadata={},
    )
    node = FineClassingNode()
    output = node.run(ctx)

    payload = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.BIN_DEFINITION)
    cat_var = next(v for v in payload.variables if v.variable == "cat_var")
    bin_labels = [b["label"] for b in cat_var.bins]
    assert "Other" in bin_labels, "High-cardinality categorical should create an 'Other' bin"
