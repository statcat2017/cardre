"""Tests for cardre.import_dataset — the generic tabular import node.

German Credit is NOT referenced anywhere in this file.
Each test asserts that numeric columns remain numeric after import.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes import ImportTabularDatasetNode
from cardre.registry import NodeRegistry
from tests.helpers import (
    make_store,
    make_synthetic_csv,
    make_synthetic_tsv,
    make_synthetic_no_header_csv,
    make_synthetic_with_nulls_csv,
)


def _run_import(source_path: Path, **overrides) -> tuple:
    """Helper: create store, run ImportTabularDatasetNode, return (store, output)."""
    store, tmp = make_store()
    store.create_project("test")
    params = {"source_path": str(source_path)}
    params.update(overrides)
    spec = StepSpec(
        step_id="import", node_type="cardre.import_dataset",
        node_version="1", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[], validated_params=params,
        runtime_metadata={},
    )
    node = ImportTabularDatasetNode()
    output = node.run(ctx)
    return store, output


# ======================================================================
# Generic Import Tests
# ======================================================================


class GenericImportTests(unittest.TestCase):

    def test_csv_with_header_creates_parquet(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_csv(tmp)
        store, output = _run_import(source)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "dataset")
        self.assertEqual(artifact.role, "input")
        self.assertTrue(store.artifact_path(artifact).exists())

        df = pl.read_parquet(store.artifact_path(artifact))
        self.assertEqual(df.height, 50)
        self.assertIn("default_flag", df.columns)
        self.assertIn("customer_id", df.columns)
        self.assertIn("age", df.columns)
        self.assertIn("income", df.columns)
        self.assertTrue(df.schema["age"].is_numeric(), "age should be numeric")
        self.assertTrue(df.schema["income"].is_numeric(), "income should be numeric")
        self.assertTrue(df.schema["credit_score"].is_numeric(), "credit_score should be numeric")
        self.assertTrue(df.schema["loan_amount"].is_numeric(), "loan_amount should be numeric")

    def test_csv_metadata_has_no_target_semantics(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_csv(tmp)
        store, output = _run_import(source)

        md = output.artifacts[0].metadata
        self.assertIn("source_file", md)
        self.assertIn("format", md)
        self.assertIn("columns", md)
        self.assertIn("row_count", md)
        self.assertNotIn("target_column", md)
        self.assertNotIn("target_mapping", md)
        self.assertNotIn("source_dataset_id", md)

    def test_csv_auto_format_detection(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_csv(tmp, filename="data.csv")
        store, output = _run_import(source)

        md = output.artifacts[0].metadata
        self.assertEqual(md["format"], "csv")

    def test_tsv_auto_format_detection(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_tsv(tmp)
        store, output = _run_import(source)

        md = output.artifacts[0].metadata
        self.assertEqual(md["format"], "tsv")

        df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertEqual(df.height, 50)

    def test_tsv_explicit_format(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_tsv(tmp, filename="data.txt")
        store, output = _run_import(source, format="tsv")

        md = output.artifacts[0].metadata
        self.assertEqual(md["format"], "tsv")

    def test_csv_without_header_uses_column_names(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_no_header_csv(tmp)
        store, output = _run_import(source, has_header=False)

        df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertEqual(df.width, 4)
        # Polars assigns column_1, column_2, ... when no header
        cols = df.columns
        self.assertTrue(all(c.startswith("column_") for c in cols))

    def test_parquet_passthrough(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_csv(tmp, filename="data.csv")
        df_orig = pl.read_csv(source)
        parquet_path = tmp / "data.parquet"
        df_orig.write_parquet(parquet_path)

        store, output = _run_import(parquet_path)
        df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertEqual(df.height, df_orig.height)
        self.assertEqual(df.columns, df_orig.columns)

    def test_null_values_handling(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_with_nulls_csv(tmp)
        store, output = _run_import(source, null_values=[""])

        df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        null_score = df["score"].null_count()
        self.assertEqual(null_score, 2)

    def test_unsupported_format_rejected(self) -> None:
        store, tmp = make_store()
        source = tmp / "data.xlsx"
        source.write_text("dummy")

        node = ImportTabularDatasetNode()
        errors = node.validate_params({"source_path": str(source)})
        self.assertTrue(any("Unsupported format" in e for e in errors))

    def test_missing_source_path_fails_validation(self) -> None:
        node = ImportTabularDatasetNode()
        errors = node.validate_params({})
        self.assertTrue(any("source_path" in e for e in errors))

    def test_nonexistent_file_fails_validation(self) -> None:
        node = ImportTabularDatasetNode()
        errors = node.validate_params({"source_path": "/nonexistent/file.csv"})
        self.assertTrue(any("does not exist" in e for e in errors))

    def test_registry_resolves_generic_node(self) -> None:
        reg = NodeRegistry.with_defaults()
        cls = reg.resolve("cardre.import_dataset")
        self.assertIs(cls, ImportTabularDatasetNode)

    def test_schema_overrides_control_types(self) -> None:
        store, tmp = make_store()
        source = make_synthetic_csv(tmp)
        store, output = _run_import(source, schema_overrides={
            "customer_id": "str",
            "age": "int",
            "income": "float",
            "default_flag": "str",
        })
        df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        self.assertEqual(df.schema["customer_id"], pl.Utf8)
        self.assertEqual(df.schema["age"], pl.Int64)
        self.assertEqual(df.schema["income"], pl.Float64)
        self.assertEqual(df.schema["default_flag"], pl.Utf8)

    def test_schema_overrides_invalid_dtype_rejected(self) -> None:
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        source = tmp / "dummy.csv"
        source.write_text("a,b\n1,2")
        node = ImportTabularDatasetNode()
        errors = node.validate_params({
            "source_path": str(source),
            "schema_overrides": {"a": "list"},
        })
        self.assertTrue(any("list" in e for e in errors))

    def test_logical_hash_stable_for_same_data(self) -> None:
        store1, tmp1 = make_store()
        store2, tmp2 = make_store()
        s1 = make_synthetic_csv(tmp1)
        s2 = make_synthetic_csv(tmp2, filename="copy.csv")

        _, o1 = _run_import(s1)
        _, o2 = _run_import(s2)
        self.assertEqual(
            o1.artifacts[0].logical_hash,
            o2.artifacts[0].logical_hash,
        )
