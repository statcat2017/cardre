"""Tests for binning, WOE/IV, WOE transform, and WOE application."""

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
from cardre.evidence import AmbiguousEvidenceError
from cardre.nodes import (
    ApplyWoeMappingNode,
    CalculateWoeIvNode,
    FineClassingNode,
    ManualBinningNode,
    WoeTransformTrainNode,
)
from cardre.store import ProjectStore

from tests.helpers import (
    _make_json_artifact,
    _make_parquet_report,
    _make_train_artifact,
    make_store,
)


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
            step_id="fine-classing", node_type="cardre.fine_classing",
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
        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("variables", payload)
        self.assertGreater(len(payload["variables"]), 0)

    def test_numeric_bin_boundaries_non_overlapping(self) -> None:
        """Verify that adjacent numeric bins do not overlap at breakpoints.

        With a value exactly at a qcut breakpoint (e.g. score=4.0 in
        [1,2,3,4,5,6] with max_bins=6), it must belong to exactly one bin.
        Lower_inclusive must be False for bins after the first.
        """
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
            step_id="fine-classing", node_type="cardre.fine_classing",
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
        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        score_bins = [v for v in payload["variables"] if v["variable"] == "score"][0]["bins"]

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
            step_id="fc", node_type="cardre.fine_classing",
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
# WOE/IV Calculation
# ======================================================================

class CalculateWoeIvTests(unittest.TestCase):

    def test_woe_iv_computes_deterministic_values(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
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

        # Create a minimal bin definition
        bin_def = {
            "variables": [
                {
                    "variable": "var1",
                    "kind": "numeric",
                    "bins": [
                        {
                            "bin_id": "v1_bin_001",
                            "label": "Low",
                            "lower": 0, "upper": 3,
                            "lower_inclusive": False, "upper_inclusive": True,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 2, "bad_count": 1,
                        },
                        {
                            "bin_id": "v1_bin_002",
                            "label": "High",
                            "lower": 3, "upper": None,
                            "lower_inclusive": False, "upper_inclusive": True,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 1, "bad_count": 2,
                        },
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

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
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
            "zero_cell_policy": "block",
            "smoothing": None,
            "purpose": "initial",
        }
        step_spec = StepSpec(
            step_id="woe-iv", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["fine-classing"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 4)

        woe_art = output.artifacts[0]
        iv_art = output.artifacts[1]
        summary_art = output.artifacts[2]
        evidence_art = output.artifacts[3]
        woe_df = pl.read_parquet(store.artifact_path(woe_art))
        iv_df = pl.read_parquet(store.artifact_path(iv_art))

        # Verify evidence v1 schema
        evidence = json.loads(store.artifact_path(evidence_art).read_text())
        self.assertEqual(evidence["schema_version"], "cardre.woe_iv_evidence.v1")
        self.assertIn("variables", evidence)
        self.assertIn("config", evidence)

        self.assertIn("woe", woe_df.columns)
        self.assertIn("iv_component", woe_df.columns)
        self.assertIn("iv", iv_df.columns)
        self.assertIn("variable", iv_df.columns)

    def test_deterministic_output(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "target": ["good", "bad", "good", "bad", "good"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        bin_def = {
            "variables": [
                {
                    "variable": "var1",
                    "kind": "numeric",
                    "bins": [
                        {"bin_id": "v1_b1", "label": "Low", "lower": 0, "upper": 3,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 3, "good_count": 2, "bad_count": 1},
                        {"bin_id": "v1_b2", "label": "High", "lower": 3, "upper": None,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 2, "good_count": 1, "bad_count": 1},
                    ],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(bin_artifact)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta2.json"
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

        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        out1 = node.run(ctx)

        ctx2 = ExecutionContext(
            store=store, run_id="r2", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        out2 = node.run(ctx2)

        self.assertEqual(
            out1.artifacts[0].logical_hash,
            out2.artifacts[0].logical_hash,
            "WOE/IV should be deterministic",
        )

    def test_woe_iv_rejects_ambiguous_definition_artifacts(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "target": ["good", "bad", "good", "bad", "good"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        bin_def = {
            "variables": [
                {
                    "variable": "var1", "kind": "numeric",
                    "bins": [{"bin_id": "v1_b1", "label": "All", "lower": 0, "upper": None,
                              "lower_inclusive": True, "upper_inclusive": True,
                              "categories": None, "is_missing_bin": False,
                              "row_count": 5, "good_count": 3, "bad_count": 2}],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)

        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        # Add a second spurious bin artifact - should be rejected
        bin_def2 = {"variables": [{"variable": "other", "kind": "numeric", "bins": []}], "warnings": []}
        bin_path2 = store.root / "artifacts" / "test-bins2.json"
        bin_path2.write_text(json.dumps(bin_def2, sort_keys=True))
        bin_artifact2 = ArtifactRef(
            artifact_id="bin2", artifact_type="definition", role="definition",
            path=relative_path(bin_path2, store.root),
            physical_hash=physical_hash(bin_path2),
            logical_hash=json_logical_hash(bin_def2),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact2)

        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[train_artifact, bin_artifact, meta_artifact, bin_artifact2],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        with self.assertRaises(AmbiguousEvidenceError):
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
            parent_step_ids=["fine-classing"], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[bin_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ManualBinningNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        merged_vars = payload["variables"]
        self.assertEqual(len(merged_vars), 1)
        merged_bins = merged_vars[0]["bins"]
        self.assertEqual(len(merged_bins), 2)


# ======================================================================
# Blocker Verification (PR #4 review findings)
# ======================================================================

def test_final_woe_zero_cell_block_fails_without_smoothing() -> None:
    store, tmp = make_store()
    store.initialize()
    df = pl.DataFrame({
        "var1": [1.0, 2.0, 3.0],
        "target": ["good", "good", "bad"],
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

    bin_def = {
        "variables": [{
            "variable": "var1", "kind": "numeric",
            "bins": [
                {"bin_id": "v1_b1", "label": "A", "lower": 0, "upper": 2,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 2, "good_count": 2, "bad_count": 0},
                {"bin_id": "v1_b2", "label": "B", "lower": 2, "upper": None,
                 "lower_inclusive": False, "upper_inclusive": True,
                 "categories": None, "is_missing_bin": False,
                 "row_count": 1, "good_count": 0, "bad_count": 1},
            ],
        }],
        "warnings": [],
    }
    bin_path = store.root / "artifacts" / "bins.json"
    bin_path.write_text(json.dumps(bin_def, sort_keys=True))
    bin_art = ArtifactRef(
        artifact_id="b1", artifact_type="definition", role="definition",
        path=relative_path(bin_path, store.root),
        physical_hash=physical_hash(bin_path),
        logical_hash=json_logical_hash(bin_def),
        media_type="application/json", metadata={},
    )
    store.register_artifact(bin_art)

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

    params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "final"}
    spec = StepSpec(
        step_id="woe", node_type="cardre.calculate_woe_iv",
        node_version="1", category="selection",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[train, bin_art, meta_art],
        validated_params=params, runtime_metadata={},
    )
    node = CalculateWoeIvNode()
    with pytest.raises(ValueError):
        node.run(ctx)


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
        "max_bins": 20, "min_bin_fraction": 0.01,
        "missing_policy": "separate_bin",
        "max_categorical_levels": 10,
        "exclude_columns": [],
    }
    spec = StepSpec(
        step_id="fc", node_type="cardre.fine_classing",
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

    payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
    cat_var = next(v for v in payload["variables"] if v["variable"] == "cat_var")
    bin_labels = [b["label"] for b in cat_var["bins"]]
    assert "Other" in bin_labels, "High-cardinality categorical should create an 'Other' bin"


# ======================================================================
# WOE Transform Train
# ======================================================================

class WoeTransformTrainTests(unittest.TestCase):

    def test_woe_transform_maps_bins_to_woe(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 15.0, 25.0],
            "target": ["good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df)

        bin_def = {
            "variables": [{
                "variable": "var1", "kind": "numeric",
                "bins": [
                    {"bin_id": "v1_b1", "label": "Low", "lower": 0, "upper": 10,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "v1_b2", "label": "High", "lower": 10, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins")

        woe_df = pl.DataFrame({
            "variable": ["var1", "var1"],
            "bin_id": ["v1_b1", "v1_b2"],
            "label": ["Low", "High"],
            "row_count": [2, 2],
            "good_count": [1, 1],
            "bad_count": [1, 1],
            "good_distribution": [0.5, 0.5],
            "bad_distribution": [0.5, 0.5],
            "woe": [0.5, -0.5],
            "iv_component": [0.0, 0.25],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe")

        params = {}
        spec = StepSpec(
            step_id="woe-tf", node_type="cardre.woe_transform_train",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = WoeTransformTrainNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        transformed = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertIn("var1_woe", transformed.columns)
        self.assertEqual(transformed.height, 4)

    def test_woe_transform_deterministic(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "x": [1.0, 2.0, 3.0],
            "target": ["g", "b", "g"],
        })
        train_art = _make_train_artifact(store, df)
        bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 2,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "x_b2", "label": "High", "lower": 2, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins2")

        woe_df = pl.DataFrame({
            "variable": ["x", "x"],
            "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"],
            "row_count": [2, 1], "good_count": [1, 1], "bad_count": [1, 0],
            "good_distribution": [0.5, 0.5], "bad_distribution": [1.0, 0.0],
            "woe": [0.2, -0.3], "iv_component": [0.1, 0.15],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe2")

        params = {}
        spec = StepSpec(
            step_id="wt", node_type="cardre.woe_transform_train",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx1 = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        ctx2 = ExecutionContext(
            store=store, run_id="r2", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params=params, runtime_metadata={},
        )
        node = WoeTransformTrainNode()
        out1 = node.run(ctx1)
        out2 = node.run(ctx2)
        self.assertEqual(
            out1.artifacts[0].logical_hash,
            out2.artifacts[0].logical_hash,
        )


# ======================================================================
# Apply WOE Mapping
# ======================================================================

class ApplyWoeMappingTests(unittest.TestCase):

    def setUp(self):
        self.store, self.tmp = make_store()
        self.store.initialize()
        self.df_train = pl.DataFrame({"x": [1.0, 2.0, 3.0], "target": ["g", "b", "g"]})
        self.df_test = pl.DataFrame({"x": [4.0, 5.0], "target": ["b", "g"]})
        self.train_art = _make_train_artifact(self.store, self.df_train, role="train")
        self.test_art = _make_train_artifact(self.store, self.df_test, role="test")
        self.bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 3,
                     "lower_inclusive": True, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "x_b2", "label": "High", "lower": 3, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
            "warnings": [],
        }
        self.bin_art = _make_json_artifact(self.store, self.bin_def, stem="bins")
        self.woe_df = pl.DataFrame({
            "variable": ["x", "x"], "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"], "row_count": [2, 1],
            "good_count": [1, 1], "bad_count": [1, 0],
            "good_distribution": [0.5, 0.5], "bad_distribution": [1.0, 0.0],
            "woe": [0.5, -0.3], "iv_component": [0.25, 0.15],
        })
        self.woe_art = _make_parquet_report(self.store, self.woe_df, stem="woe")

    def test_applies_woe_to_all_roles(self):
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, self.test_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        data_arts = [a for a in out.artifacts if a.role != "report"]
        report_arts = [a for a in out.artifacts if a.role == "report"]
        self.assertEqual(len(data_arts), 2)
        self.assertEqual(len(report_arts), 1)
        for art in data_arts:
            df = pl.read_parquet(self.store.artifact_path(art))
            self.assertIn("x_woe", df.columns)

    def test_unmatched_rows_fail_policy_raises(self):
        df_oot = pl.DataFrame({"x": [-1.0, -2.0], "target": ["g", "b"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "fail"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("did not match any bin", str(cm.exception))

    def test_unmatched_rows_invalid_policy_fails_validation(self):
        params = {"woe_unmatched_policy": "invalid"}
        self.assertIn("woe_unmatched_policy", ApplyWoeMappingNode().validate_params(params)[0])

    def test_unmatched_rows_warn_policy_fills_zero(self):
        df_oot = pl.DataFrame({"x": [-1.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[1]))
        self.assertEqual(df["x_woe"][0], 0.0)

    def test_unseen_category_in_oot_fails_with_fail_policy(self):
        store, tmp = make_store()
        store.initialize()
        df_train = pl.DataFrame({"cat": ["a", "b", "c"], "target": ["g", "b", "g"]})
        df_oot = pl.DataFrame({"cat": ["z"], "target": ["g"]})
        train_art = _make_train_artifact(store, df_train, role="train")
        oot_art = _make_train_artifact(store, df_oot, role="oot")
        bin_def = {
            "variables": [{
                "variable": "cat", "kind": "categorical",
                "bins": [
                    {"bin_id": "cat_b1", "label": "a", "categories": ["a"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 1, "bad_count": 0},
                    {"bin_id": "cat_b2", "label": "b", "categories": ["b"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 0, "bad_count": 1},
                    {"bin_id": "cat_b3", "label": "c", "categories": ["c"],
                     "is_missing_bin": False, "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="cat_bins")
        woe_df = pl.DataFrame({
            "variable": ["cat", "cat", "cat"],
            "bin_id": ["cat_b1", "cat_b2", "cat_b3"],
            "label": ["a", "b", "c"],
            "row_count": [1, 1, 1], "good_count": [1, 0, 1], "bad_count": [0, 1, 0],
            "good_distribution": [0.5, 0.0, 0.5], "bad_distribution": [0.0, 1.0, 0.0],
            "woe": [0.5, -0.5, 0.5], "iv_component": [0.25, 0.5, 0.25],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="cat_woe")
        params = {"woe_unmatched_policy": "fail"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[train_art, oot_art, bin_art, woe_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("did not match any bin", str(cm.exception))

    def test_below_min_numeric_value_fills_zero_by_default(self):
        df_oot = pl.DataFrame({"x": [-5.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[], input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[1]))
        self.assertEqual(df["x_woe"][0], 0.0)
