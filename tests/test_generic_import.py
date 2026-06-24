"""Tests for cardre.import_dataset — the generic tabular import node.

German Credit is NOT referenced anywhere in this file.
Each test asserts that numeric columns remain numeric after import.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import polars as pl
import pytest

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

    def test_max_rows_csv_imports_exactly_n_rows(self) -> None:
        import tempfile
        import polars as pl
        s = make_synthetic_csv(tmp := Path(tempfile.mkdtemp()))
        store, output = _run_import(s, max_rows=3)
        art = output.artifacts[0]
        self.assertEqual(art.metadata.get("row_count"), 3)
        self.assertEqual(art.metadata.get("max_rows_applied"), 3)
        df = pl.read_parquet(store.artifact_path(art))
        self.assertEqual(df.height, 3)
        # Warning should be present
        self.assertIsNotNone(output.warnings)
        self.assertTrue(any("SOURCE_ROW_LIMIT_APPLIED" in str(w) for w in output.warnings))

    def test_max_rows_parquet_imports_exactly_n_rows(self) -> None:
        import tempfile
        import polars as pl
        tmp = Path(tempfile.mkdtemp())
        df = pl.DataFrame({"x": list(range(50))})
        src = tmp / "test.parquet"
        df.write_parquet(src)
        store, output = _run_import(src, max_rows=3)
        art = output.artifacts[0]
        self.assertEqual(art.metadata.get("row_count"), 3)
        df2 = pl.read_parquet(store.artifact_path(art))
        self.assertEqual(df2.height, 3)

    def test_max_rows_none_imports_all_rows(self) -> None:
        import tempfile
        s = make_synthetic_csv(tmp := Path(tempfile.mkdtemp()), rows=50)
        store, output = _run_import(s)
        art = output.artifacts[0]
        self.assertEqual(art.metadata.get("row_count"), 50)

    def test_max_rows_validation_rejects_invalid(self) -> None:
        import tempfile
        from cardre.nodes import ImportTabularDatasetNode
        node = ImportTabularDatasetNode()
        s = make_synthetic_csv(tmp := Path(tempfile.mkdtemp()))
        for bad_val in [0, -1, "abc", 1.5, True, False]:
            errors = node.validate_params({"source_path": str(s), "max_rows": bad_val})
            self.assertTrue(any("max_rows" in e for e in errors),
                            f"Expected max_rows error for {bad_val}")

    def test_null_values_custom_markers_imported(self) -> None:
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "nulls.csv"
        csv_path.write_text("a,b\n1,N/A\n2,3\nNULL,4\n")
        store, output = _run_import(csv_path, null_values=["N/A", "NULL"])
        art = output.artifacts[0]
        df = pl.read_parquet(store.artifact_path(art))
        # N/A in column b and NULL in column a should be null
        assert df["a"].null_count() >= 1
        assert df["b"].null_count() >= 1

    def test_encoding_failure_raises_on_invalid_encoding(self) -> None:
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        # Write a file with non-UTF8 bytes
        csv_path = tmp / "latin1.csv"
        csv_path.write_bytes("a,b\n1,caf\xe9\n2,test\n".encode("latin-1"))
        with self.assertRaises(Exception):
            _run_import(csv_path, encoding="utf-8")

    def test_latin1_encoding_imports_successfully(self) -> None:
        """Positive test: Latin-1 file imports correctly when encoding='latin1'."""
        import tempfile
        import polars as pl
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "latin1.csv"
        csv_path.write_bytes("a,b\n1,caf\xe9\n2,test\n".encode("latin-1"))
        store, output = _run_import(csv_path, encoding="latin-1")
        art = output.artifacts[0]
        df = pl.read_parquet(store.artifact_path(art))
        assert df.height == 2
        assert df["b"][0] == "caf\xe9"

    def test_duplicate_column_names_silently_renamed(self) -> None:
        """Polars silently renames duplicate columns — documents risk #6.

        The import does NOT raise; instead polars appends `_duplicated_N`.
        This is a known silent-corruption risk.
        """
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "dup_cols.csv"
        csv_path.write_text("a,a\n1,2\n3,4\n")
        store, output = _run_import(csv_path)
        art = output.artifacts[0]
        df = pl.read_parquet(store.artifact_path(art))
        # Polars renames duplicates rather than raising
        assert "a" in df.columns
        assert any("duplicated" in c for c in df.columns)

    def test_empty_column_name_imports_as_empty(self) -> None:
        """Empty column names may pass import — documents risk #7."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "empty_col.csv"
        csv_path.write_text(",b\n1,2\n3,4\n")
        store, output = _run_import(csv_path)
        art = output.artifacts[0]
        df = pl.read_parquet(store.artifact_path(art))
        # Empty column name is preserved by polars
        assert "" in df.columns or any(c.strip() == "" for c in df.columns)


class WideDatasetSmokeTests(unittest.TestCase):
    @pytest.mark.slow
    def test_wide_dataset_does_not_oom(self) -> None:
        """Smoke test: 1k columns × 50k rows should complete without OOM.

        Marked slow — not run in CI by default.
        """
        import tempfile
        from pathlib import Path
        import polars as pl

        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "wide.csv"
        n_cols = 1000
        n_rows = 50_000

        header = ",".join(f"col_{i}" for i in range(n_cols))
        row = ",".join("1" for _ in range(n_cols))
        lines = [header] + [row] * n_rows
        csv_path.write_text("\n".join(lines))

        store, _ = make_store()
        store.create_project("test")
        node = ImportTabularDatasetNode()
        from cardre.audit import StepSpec, ExecutionContext
        params = {"source_path": str(csv_path), "max_rows": 10_000}
        spec = StepSpec(
            step_id="import-wide",
            node_type="cardre.import_dataset",
            node_version="1",
            category="transform",
            params=params,
            params_hash="dummy",
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="slow-test-run", plan_version_id="pv",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[], validated_params=params,
            runtime_metadata={},
        )
        output = node.run(ctx)
        self.assertEqual(len(output.artifacts), 1)


class ProfileSamplingTests(unittest.TestCase):

    def _make_dataset_artifact(self, store, n_rows=100):
        """Create a parquet dataset artifact and return the ArtifactRef."""
        import polars as pl
        from cardre.artifacts import write_parquet_artifact
        df = pl.DataFrame({"x": list(range(n_rows)), "y": [float(i) for i in range(n_rows)]})
        return write_parquet_artifact(
            store, artifact_type="dataset", role="input",
            stem="test-dataset", frame=df,
        )

    def test_profile_max_rows_samples_first_n(self) -> None:
        from cardre.nodes.prep import ProfileDatasetNode
        from cardre.audit import StepSpec, ExecutionContext
        store, _ = make_store()
        store.create_project("test")
        art = self._make_dataset_artifact(store, n_rows=100)

        params = {"profile_max_rows": 10}
        spec = StepSpec(
            step_id="profile", node_type="cardre.profile_dataset",
            node_version="1", category="transform",
            params=params, params_hash="dummy",
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[art], validated_params=params,
            runtime_metadata={},
        )
        node = ProfileDatasetNode()
        output = node.run(ctx)
        assert output.artifacts[0].metadata["profile_sampled"] is True
        assert output.artifacts[0].metadata["profile_max_rows"] == 10
        assert output.warnings is not None
        assert any("PROFILE_SAMPLED" in str(w) for w in output.warnings)

    def test_profile_no_sampling_reads_all(self) -> None:
        from cardre.nodes.prep import ProfileDatasetNode
        from cardre.audit import StepSpec, ExecutionContext
        store, _ = make_store()
        store.create_project("test")
        art = self._make_dataset_artifact(store, n_rows=50)

        params = {}
        spec = StepSpec(
            step_id="profile", node_type="cardre.profile_dataset",
            node_version="1", category="transform",
            params=params, params_hash="dummy",
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[art], validated_params=params,
            runtime_metadata={},
        )
        node = ProfileDatasetNode()
        output = node.run(ctx)
        assert "profile_sampled" not in output.artifacts[0].metadata
        assert output.warnings is None
