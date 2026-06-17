"""Tests for cardre.audit — hashing, StepSpec, artifact references."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    StepSpec,
    json_logical_hash,
    params_hash,
    physical_hash,
    replace_step_params,
    table_logical_hash,
)


class HashingTests(unittest.TestCase):

    def test_json_logical_hash_key_order_independent(self) -> None:
        h1 = json_logical_hash({"z": 1, "a": 2})
        h2 = json_logical_hash({"a": 2, "z": 1})
        self.assertEqual(h1, h2)

    def test_json_logical_hash_different_content(self) -> None:
        h1 = json_logical_hash({"a": 1})
        h2 = json_logical_hash({"a": 2})
        self.assertNotEqual(h1, h2)

    def test_params_hash_uses_json_logical(self) -> None:
        h1 = params_hash({"b": 1, "a": 2})
        h2 = params_hash({"a": 2, "b": 1})
        self.assertEqual(h1, h2)

    def test_table_logical_hash_same_table_equal(self) -> None:
        df1 = pl.DataFrame({"b": [3, 4], "a": [1, 2]})
        df2 = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
        self.assertEqual(table_logical_hash(df1), table_logical_hash(df2))

    def test_table_logical_hash_different_data(self) -> None:
        df1 = pl.DataFrame({"a": [1, 2]})
        df2 = pl.DataFrame({"a": [1, 3]})
        self.assertNotEqual(table_logical_hash(df1), table_logical_hash(df2))

    def test_physical_hash_file_bytes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin") as f:
            f.write(b"hello")
            f.flush()
            h = physical_hash(Path(f.name))
        import hashlib
        expected = hashlib.sha256(b"hello").hexdigest()
        self.assertEqual(h, expected)

    def test_artifact_ref_physical_and_logical(self) -> None:
        ref = ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            role="input",
            path="datasets/test.parquet",
            physical_hash="p123",
            logical_hash="l456",
        )
        self.assertEqual(ref.physical_hash, "p123")
        self.assertEqual(ref.logical_hash, "l456")

    def test_artifact_ref_roundtrip_to_dict(self) -> None:
        ref = ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            role="input",
            path="datasets/test.parquet",
            physical_hash="p123",
            logical_hash="l456",
            media_type="application/vnd.apache.parquet",
            metadata={"k": "v"},
        )
        d = ref.to_dict()
        ref2 = ArtifactRef.from_dict(d)
        self.assertEqual(ref, ref2)


class StepSpecBranchExtensionTests(unittest.TestCase):

    def test_legacy_construction_backfills_canonical_step_id(self) -> None:
        spec = StepSpec(
            step_id="manual-binning",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertIsNone(spec.branch_id)

    def test_branch_step_preserves_canonical_step_id(self) -> None:
        spec = StepSpec(
            step_id="manual-binning__br_a81f3c",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="Coarser bins",
            position=0,
            canonical_step_id="manual-binning",
            branch_id="br_a81f3c",
        )
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertEqual(spec.branch_id, "br_a81f3c")

    def test_to_dict_includes_branch_fields(self) -> None:
        spec = StepSpec(
            step_id="manual-binning__br_a81f3c",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="",
            position=0,
            canonical_step_id="manual-binning",
            branch_id="br_a81f3c",
        )
        d = spec.to_dict()
        self.assertEqual(d["canonical_step_id"], "manual-binning")
        self.assertEqual(d["branch_id"], "br_a81f3c")

    def test_from_dict_tolerates_legacy_missing_fields(self) -> None:
        data = {
            "step_id": "manual-binning",
            "node_type": "cardre.manual_binning",
            "node_version": "1",
            "category": "refinement",
            "params": {},
            "params_hash": "abc",
            "parent_step_ids": [],
            "branch_label": "",
            "position": 0,
        }
        spec = StepSpec.from_dict(data)
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertIsNone(spec.branch_id)

    def test_from_dict_reads_branch_fields_when_present(self) -> None:
        data = {
            "step_id": "manual-binning__br_a81f3c",
            "node_type": "cardre.manual_binning",
            "node_version": "1",
            "category": "refinement",
            "params": {},
            "params_hash": "abc",
            "parent_step_ids": [],
            "branch_label": "",
            "position": 0,
            "canonical_step_id": "manual-binning",
            "branch_id": "br_a81f3c",
        }
        spec = StepSpec.from_dict(data)
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertEqual(spec.branch_id, "br_a81f3c")

    def test_replace_step_params_preserves_branch_fields(self) -> None:
        steps = [
            StepSpec(
                step_id="manual-binning__br_a81f3c",
                node_type="cardre.manual_binning",
                node_version="1",
                category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["fine-classing", "variable-selection"],
                branch_label="Coarser bins",
                position=5,
                canonical_step_id="manual-binning",
                branch_id="br_a81f3c",
            ),
        ]
        new_steps = replace_step_params(steps, "manual-binning__br_a81f3c", {"overrides": [{"variable": "x", "merge": [1, 2]}]})
        self.assertEqual(new_steps[0].canonical_step_id, "manual-binning")
        self.assertEqual(new_steps[0].branch_id, "br_a81f3c")

    def test_replace_step_params_preserves_branch_fields_on_unchanged_step(self) -> None:
        steps = [
            StepSpec(
                step_id="import",
                node_type="cardre.import_dataset",
                node_version="1",
                category="transform",
                params={"source": "data.csv"},
                params_hash=json_logical_hash({"source": "data.csv"}),
                parent_step_ids=[],
                branch_label="",
                position=0,
            ),
            StepSpec(
                step_id="manual-binning__br_a81f3c",
                node_type="cardre.manual_binning",
                node_version="1",
                category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["fine-classing", "variable-selection"],
                branch_label="Coarser bins",
                position=5,
                canonical_step_id="manual-binning",
                branch_id="br_a81f3c",
            ),
        ]
        new_steps = replace_step_params(steps, "import", {"source": "new_data.csv"})
        self.assertEqual(new_steps[0].canonical_step_id, "import")
        self.assertIsNone(new_steps[0].branch_id)
        self.assertEqual(new_steps[1].canonical_step_id, "manual-binning")
        self.assertEqual(new_steps[1].branch_id, "br_a81f3c")
