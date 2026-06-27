"""Tests for WOE/IV calculation, WOE transform, and WOE application."""

from __future__ import annotations

import io
import json
import unittest

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
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_WOE_APPLICATION_EVIDENCE,
)
from cardre.artifacts import write_json_artifact
from cardre.nodes import (
    ApplyWoeMappingNode,
    CalculateWoeIvNode,
    WoeTransformTrainNode,
)

from tests.helpers import (
    _make_json_artifact,
    _make_parquet_report,
    _make_train_artifact,
    make_store,
)

from tests.helpers.evidence_assertions import assert_woe_iv_evidence


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
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
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
            parent_step_ids=["binning"], branch_label="", position=1,
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
        evidence_art = output.artifacts[3]
        woe_df = pl.read_parquet(store.artifact_path(woe_art))
        iv_df = pl.read_parquet(store.artifact_path(iv_art))

        evidence = ArtifactEvidenceReader(store).read(evidence_art.artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
        assert_woe_iv_evidence(evidence)

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
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
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
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
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

    def test_non_monotonic_variable_rejected_when_enforced(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
            "target": ["bad", "good", "bad", "good", "bad", "good", "bad", "good", "bad"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
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
                    {"bin_id": "v1_b1", "label": "A", "lower": 0, "upper": 3,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 1, "bad_count": 2},
                    {"bin_id": "v1_b2", "label": "B", "lower": 3, "upper": 6,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 2, "bad_count": 1},
                    {"bin_id": "v1_b3", "label": "C", "lower": 6, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 1, "bad_count": 2},
                ],
            }],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)
        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)
        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "final", "enforce_monotonic_woe": True}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[train, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)
        reader = ArtifactEvidenceReader(store)
        evidence_art = next(a for a in output.artifacts
                           if a.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1")
        evidence = reader.read(evidence_art.artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
        var1 = next(v for v in evidence.variables if v.variable_name == "var1")
        assert var1.status == "REJECTED", f"Expected REJECTED status, got {var1.status}"
        assert any("non_monotonic" in str(w).lower() for w in var1.warnings), (
            f"Expected non-monotonic warning, got {var1.warnings}"
        )

    def test_non_monotonic_passthrough_when_not_enforced(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
            "target": ["bad", "good", "bad", "good", "bad", "good", "bad", "good", "bad"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
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
                    {"bin_id": "v1_b1", "label": "A", "lower": 0, "upper": 3,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 1, "bad_count": 2},
                    {"bin_id": "v1_b2", "label": "B", "lower": 3, "upper": 6,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 2, "bad_count": 1},
                    {"bin_id": "v1_b3", "label": "C", "lower": 6, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 3, "good_count": 1, "bad_count": 2},
                ],
            }],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)
        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)
        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "final", "enforce_monotonic_woe": False}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[train, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)
        reader = ArtifactEvidenceReader(store)
        evidence_art = next(a for a in output.artifacts
                           if a.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1")
        evidence = reader.read(evidence_art.artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
        var1 = next(v for v in evidence.variables if v.variable_name == "var1")
        assert var1.status == "included", f"Expected included status, got {var1.status}"

    def test_pure_bin_diagnostic_emitted(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0],
            "target": ["good", "good", "bad"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
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
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)
        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)
        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[train, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)
        import json as _json
        summary_art = output.artifacts[2]
        data = _json.loads(store.artifact_path(summary_art).read_text())
        pure_warnings = [w for w in data.get("warnings", []) if w.get("code") == "PURE_BIN"]
        assert len(pure_warnings) > 0, "Expected PURE_BIN diagnostic"

    def test_pure_bin_partial_goods_detected(self) -> None:
        """A pure bin with only some of the total goods/bads must still be flagged."""
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "target": ["good", "good", "good", "bad", "bad", "bad"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
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
                    {"bin_id": "v1_b2", "label": "B", "lower": 2, "upper": 4,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "v1_b3", "label": "C", "lower": 4, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 0, "bad_count": 2},
                ],
            }],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)
        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)
        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec, parent_run_steps=[],
            input_artifacts=[train, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)
        import json as _json
        summary_art = output.artifacts[2]
        data = _json.loads(store.artifact_path(summary_art).read_text())
        pure_warnings = [w for w in data.get("warnings", []) if w.get("code") == "PURE_BIN"]
        bin_ids_flagged = {w.get("bin_id") for w in pure_warnings}
        assert "v1_b1" in bin_ids_flagged, "Pure-good bin (2 good, 0 bad) should be flagged"
        assert "v1_b3" in bin_ids_flagged, "Pure-bad bin (0 good, 2 bad) should be flagged"
        assert "v1_b2" not in bin_ids_flagged, "Mixed bin should not be flagged"


# ======================================================================
# Blocker verification — WOE/IV zero cell
# ======================================================================


def test_final_woe_zero_cell_block_fails_without_smoothing() -> None:
    store, tmp = make_store()
    store.initialize()
    df = pl.DataFrame({
        "var1": [1.0, 2.0, 3.0],
        "target": ["good", "good", "bad"],
    })
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
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


def test_initial_iv_zero_cell_matches_final_iv_when_smoothed() -> None:
    store, tmp = make_store()
    store.initialize()
    df = pl.DataFrame({
        "var1": [1.0, 2.0, 3.0],
        "target": ["good", "good", "bad"],
    })
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
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
    smoothing = {"method": "additive", "alpha": 0.5, "rationale": "test smoothing"}
    for purpose in ("initial", "final"):
        params = {"zero_cell_policy": "block", "smoothing": smoothing, "purpose": purpose}
        spec = StepSpec(
            step_id=f"woe-{purpose}", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id=f"r-{purpose}", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train, bin_art, meta_art],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        node.run(ctx)
    # Both initial and final should succeed without error and produce a WOE table
    # The key assertion is that both complete successfully (no ValueError raised)


def test_initial_iv_zero_cell_warns_when_unsmoothed() -> None:
    store, tmp = make_store()
    store.initialize()
    df = pl.DataFrame({
        "var1": [1.0, 2.0, 3.0],
        "target": ["good", "good", "bad"],
    })
    buf = io.BytesIO()
    df.write_parquet(buf)
    path = store.root / "datasets" / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
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
    params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
    spec = StepSpec(
        step_id="woe-init", node_type="cardre.calculate_woe_iv",
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
    output = node.run(ctx)
    found_warning = False
    for art in output.artifacts:
        if art.artifact_type == "report" and art.role == "report":
            try:
                data = json.loads(store.artifact_path(art).read_text())
                if "warnings" in data:
                    for w in data["warnings"]:
                        if w.get("code") == "ZERO_CELL_INITIAL_IV_DEFLATED":
                            found_warning = True
            except Exception:
                pass
    assert found_warning, "Expected ZERO_CELL_INITIAL_IV_DEFLATED warning in summary"


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

    def test_default_woe_unmatched_policy_is_fail(self):
        store, tmp = make_store()
        store.initialize()
        df_oot = pl.DataFrame({"cat": ["z"], "target": ["g"]})
        oot_art = _make_train_artifact(store, df_oot, role="oot")
        df_train = pl.DataFrame({"cat": ["a", "b", "c"], "target": ["g", "b", "g"]})
        train_art = _make_train_artifact(store, df_train, role="train")
        bin_def = {
            "variables": [{
                "variable": "cat", "kind": "categorical",
                "bins": [
                    {"bin_id": "cat_b1", "label": "A", "lower": None, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": False,
                     "categories": ["a", "b"], "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                    {"bin_id": "cat_b2", "label": "C", "lower": None, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": False,
                     "categories": ["c"], "is_missing_bin": False,
                     "row_count": 1, "good_count": 1, "bad_count": 0},
                ],
            }],
            "warnings": [],
        }
        bin_art = _make_json_artifact(store, bin_def, stem="bins")
        woe_df = pl.DataFrame({
            "variable": ["cat", "cat"], "bin_id": ["cat_b1", "cat_b2"],
            "label": ["A", "C"], "row_count": [2, 1],
            "good_count": [1, 1], "bad_count": [1, 0],
            "good_distribution": [0.5, 0.5], "bad_distribution": [1.0, 0.0],
            "woe": [0.5, -0.3], "iv_component": [0.25, 0.15],
        })
        woe_art = _make_parquet_report(store, woe_df, stem="woe")
        params = {}
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


# ======================================================================
# Apply WOE Mapping — Evidence Artifact
# ======================================================================

class ApplyWoeMappingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.tmp = make_store()
        self.store.initialize()
        self.df_train = pl.DataFrame({"x": [1.0, 2.0], "target": ["g", "b"]})
        self.train_art = _make_train_artifact(self.store, self.df_train, role="train")
        self.bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 3,
                     "lower_inclusive": True, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 1, "bad_count": 1},
                ],
            }],
            "warnings": [],
        }
        self.bin_art = _make_json_artifact(self.store, self.bin_def, stem="bins")
        self.woe_df = pl.DataFrame({
            "variable": ["x"], "bin_id": ["x_b1"], "label": ["Low"],
            "row_count": [2], "good_count": [1], "bad_count": [1],
            "good_distribution": [0.5], "bad_distribution": [0.5],
            "woe": [0.5], "iv_component": [0.25],
        })
        self.woe_art = _make_parquet_report(self.store, self.woe_df, stem="woe")

    def test_evidence_artifact_present(self):
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        evidence_arts = [a for a in out.artifacts if a.role == "report"]
        self.assertEqual(len(evidence_arts), 1)
        evidence = ArtifactEvidenceReader(self.store).read(evidence_arts[0].artifact_id, EvidenceKind.WOE_APPLICATION_EVIDENCE)
        self.assertEqual(evidence.schema_version, SCHEMA_WOE_APPLICATION_EVIDENCE)
        self.assertTrue(evidence.roles)
        self.assertEqual(evidence.policy["woe_unmatched_policy"], "warn")

    def test_evidence_records_source_artifact_id(self):
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        evidence_arts = [a for a in out.artifacts if a.role == "report"]
        evidence = ArtifactEvidenceReader(self.store).read(evidence_arts[0].artifact_id, EvidenceKind.WOE_APPLICATION_EVIDENCE)
        role_entry = evidence.roles["train"]
        self.assertIsNotNone(role_entry)
        self.assertEqual(role_entry["source_artifact_id"], self.train_art.artifact_id)
        self.assertIn("output_artifact_id", role_entry)
        self.assertIn("source_physical_hash", role_entry)
        self.assertIn("source_logical_hash", role_entry)
        self.assertIn("variables_applied", role_entry)
        self.assertIn("woe_columns_created", role_entry)
        self.assertIn("unmatched_by_variable", role_entry)
        self.assertIn("unmatched_row_count", role_entry)

    def test_evidence_records_bin_and_woe_artifact_ids(self):
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, self.bin_art, self.woe_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        evidence_arts = [a for a in out.artifacts if a.role == "report"]
        evidence = ArtifactEvidenceReader(self.store).read(evidence_arts[0].artifact_id, EvidenceKind.WOE_APPLICATION_EVIDENCE)
        self.assertTrue(evidence.bin_definition_artifact_id)
        self.assertTrue(evidence.woe_table_artifact_id)

    def test_bundle_driven_fail_policy(self):
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        bundle_payload = {
            "schema_version": "cardre.frozen_scorecard_bundle.v1",
            "bundle_type": "scorecard_application",
            "components": {},
            "feature_contract": {"features": []},
            "score_scaling": {},
            "warnings": [],
        }
        bundle_art = write_json_artifact(
            self.store, artifact_type="scorecard", role="scorecard",
            stem="bundle",
            payload=bundle_payload,
            metadata={
                "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
                "bin_definition_artifact_id": "bins_1",
                "woe_table_artifact_id": "woe_1",
            },
        )
        df_oot = pl.DataFrame({"x": [-1.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art, bundle_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("did not match any bin", str(cm.exception))

    def test_bundle_present_with_explicit_warn_policy_respected(self):
        params = {"woe_unmatched_policy": "warn"}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        bundle_payload = {
            "schema_version": "cardre.frozen_scorecard_bundle.v1",
            "bundle_type": "scorecard_application",
            "components": {},
            "feature_contract": {"features": []},
            "score_scaling": {},
            "warnings": [],
        }
        bundle_art = write_json_artifact(
            self.store, artifact_type="scorecard", role="scorecard",
            stem="bundle",
            payload=bundle_payload,
            metadata={
                "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
                "bin_definition_artifact_id": "bins_1",
                "woe_table_artifact_id": "woe_1",
            },
        )
        df_oot = pl.DataFrame({"x": [-1.0], "target": ["g"]})
        oot_art = _make_train_artifact(self.store, df_oot, role="oot")
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, oot_art, self.bin_art, self.woe_art, bundle_art],
                               validated_params=params, runtime_metadata={})
        out = ApplyWoeMappingNode().run(ctx)
        df = pl.read_parquet(self.store.artifact_path(out.artifacts[1]))
        self.assertEqual(df["x_woe"][0], 0.0)

    def test_bundle_requires_selection_artifact_when_bundle_has_one(self):
        """When frozen bundle has selection_artifact_id, selection must be present."""
        params = {}
        spec = StepSpec(step_id="aw", node_type="cardre.apply_woe_mapping", node_version="1", category="apply",
                        params=params, params_hash=json_logical_hash(params),
                        parent_step_ids=[], branch_label="", position=0)
        bundle_payload = {
            "schema_version": "cardre.frozen_scorecard_bundle.v1",
            "bundle_type": "scorecard_application",
            "components": {},
            "feature_contract": {"features": []},
            "score_scaling": {},
            "warnings": [],
        }
        bundle_art = write_json_artifact(
            self.store, artifact_type="scorecard", role="scorecard",
            stem="bundle",
            payload=bundle_payload,
            metadata={
                "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
                "bin_definition_artifact_id": "bins_1",
                "woe_table_artifact_id": "woe_1",
                "selection_artifact_id": "sel_1",
            },
        )
        ctx = ExecutionContext(store=self.store, run_id="r1", plan_version_id="pv1", step_spec=spec,
                               parent_run_steps=[],
                               input_artifacts=[self.train_art, self.bin_art, self.woe_art, bundle_art],
                               validated_params=params, runtime_metadata={})
        with self.assertRaises(ValueError) as cm:
            ApplyWoeMappingNode().run(ctx)
        self.assertIn("selection artifact", str(cm.exception))
