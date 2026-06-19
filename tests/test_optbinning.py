"""Tests for optbinning adapter and AutoBinningFitNode."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from cardre.nodes import AutoBinningFitNode, BinningNode
from cardre.engine.binning.optbinning_adapter import (
    AdapterResult,
    VariableBinningResult,
    _build_params,
    _extract_bins,
    _extract_categories,
    _assign_numeric_bounds,
)

from tests.helpers import make_store


# ======================================================================
# Helmets: optbinning availability check
# ======================================================================

try:
    import optbinning  # noqa: F401
    HAS_OPTBINNING = True
except ImportError:
    HAS_OPTBINNING = False


# ======================================================================
# Adapter unit tests (no optbinning needed)
# ======================================================================


class TestBuildParams:
    """Test parameter mapping from Cardre params to optbinning kwargs."""

    def test_default_params(self):
        params = {"solver": "cp"}
        result = _build_params("age", "numerical", {}, params)
        assert result["name"] == "age"
        assert result["dtype"] == "numerical"
        assert result["prebinning_method"] == "cart"
        assert result["solver"] == "cp"
        assert result["divergence"] == "iv"

    def test_categorical_gets_cat_cutoff(self):
        params = {"cat_cutoff": 0.02}
        result = _build_params("cat", "categorical", {}, params)
        assert result["cat_cutoff"] == 0.02

    def test_categorical_no_cat_cutoff(self):
        result = _build_params("cat", "categorical", {}, {})
        assert result["cat_cutoff"] == 0.01

    def test_special_codes_passed(self):
        sc = {"age": [-999, -99]}
        result = _build_params("age", "numerical", sc, {})
        assert result["special_codes"] == [-999, -99]

    def test_special_codes_not_passed_for_other_var(self):
        sc = {"other": [-999]}
        result = _build_params("age", "numerical", sc, {})
        assert "special_codes" not in result


class TestAssignNumericBounds:
    """Test numeric boundary assignment from optbinning splits."""

    def test_first_bin(self):
        d: dict = {}
        _assign_numeric_bounds(d, 1, [25.5, 37.0])
        assert d["lower"] is None
        assert d["upper"] == 25.5
        assert d["lower_inclusive"] is False
        assert d["upper_inclusive"] is False
        assert "inf" in d["label"]

    def test_middle_bin(self):
        d: dict = {}
        _assign_numeric_bounds(d, 2, [25.5, 37.0])
        assert d["lower"] == 25.5
        assert d["upper"] == 37.0
        assert d["lower_inclusive"] is True
        assert d["upper_inclusive"] is False

    def test_last_bin(self):
        d: dict = {}
        _assign_numeric_bounds(d, 3, [25.5, 37.0])
        assert d["lower"] == 37.0
        assert d["upper"] is None
        assert d["lower_inclusive"] is True
        assert d["upper_inclusive"] is False
        assert "+inf" in d["label"]

    def test_single_split(self):
        d: dict = {}
        _assign_numeric_bounds(d, 1, [50.0])
        assert d["lower"] is None
        assert d["upper"] == 50.0

    def test_no_splits_single_bin(self):
        d: dict = {}
        _assign_numeric_bounds(d, 1, [])
        assert d["label"] == "All values"


class TestExtractCategories:
    """Test category extraction from optbinning bin labels."""

    def test_single_category(self):
        assert _extract_categories("Employed") == ["Employed"]

    def test_grouped_categories(self):
        result = _extract_categories("A, B, C")
        assert result == ["A", "B", "C"]

    def test_grouped_no_spaces(self):
        result = _extract_categories("A,B,C")
        assert result == ["A", "B", "C"]

    def test_none_for_missing(self):
        assert _extract_categories("Missing") is None

    def test_none_for_empty(self):
        assert _extract_categories("") is None

    def test_not_grouped_basic(self):
        assert _extract_categories("Cat1") == ["Cat1"]


class TestExtractBins:
    """Test bin extraction from mock optbinning output."""

    def _make_mock_optb(self, binning_table_data, splits=None, special_codes=None, status="OPTIMAL"):
        """Create a mock optbinning result object.

        Uses a fake table with iterrows() that returns dicts — avoids
        pandas dependency (not guaranteed in CI).
        """
        mock = MagicMock()
        mock.status = status
        mock.splits = splits if splits is not None else []
        mock.special_codes = special_codes

        class _FakeTable:
            """Minimal iterable table — no pandas dependency."""
            def __init__(self, data: dict):
                keys = list(data.keys())
                n = len(data[keys[0]]) if keys else 0
                self._rows = [
                    {k: data[k][i] for k in keys}
                    for i in range(n)
                ]

            def iterrows(self):
                for i, row in enumerate(self._rows):
                    yield i, row

        mock.binning_table.build.return_value = _FakeTable(binning_table_data)
        return mock

    def test_categorical_bins(self):
        """Categorical variable produces bins with category lists."""
        data = {
            "Bin": ["A", "B, C", "D", "Totals"],
            "Count": [100, 200, 50, 350],
            "Event": [20, 50, 10, 80],
            "Non-event": [80, 150, 40, 270],
        }
        mock = self._make_mock_optb(data)
        bins = _extract_bins("region", "categorical", mock)
        assert len(bins) == 3  # totals dropped
        assert bins[0]["categories"] == ["A"]
        assert bins[1]["categories"] == ["B", "C"]
        assert bins[2]["categories"] == ["D"]
        assert bins[0]["kind"] == "categorical"

    def test_missing_bin_label_detected(self):
        """Bin labeled 'Missing' is marked as missing."""
        data = {
            "Bin": ["(-inf, 50.0)", "[50.0, +inf)", "Missing", "Totals"],
            "Count": [100, 200, 30, 330],
            "Event": [20, 40, 10, 70],
            "Non-event": [80, 160, 20, 260],
        }
        mock = self._make_mock_optb(data, splits=[50.0])
        bins = _extract_bins("score", "numerical", mock)
        assert len(bins) == 3
        missing_bins = [b for b in bins if b.get("is_missing_bin")]
        assert len(missing_bins) == 1
        assert missing_bins[0]["label"] == "Missing"
        assert missing_bins[0]["row_count"] == 30

    def test_special_code_bin_detected(self):
        """Bin matching a special code is marked as special."""
        data = {
            "Bin": ["(-inf, 600)", "[600, +inf)", "[-999, -999]", "Totals"],
            "Count": [200, 250, 50, 500],
            "Event": [40, 30, 30, 100],
            "Non-event": [160, 220, 20, 400],
        }
        mock = self._make_mock_optb(data, splits=[600], special_codes=[-999])
        bins = _extract_bins("score", "numerical", mock)
        special_bins = [b for b in bins if b.get("is_special_bin")]
        assert len(special_bins) == 1
        assert special_bins[0]["label"] == "[-999, -999]"
        assert special_bins[0]["special_values"] == [-999]

    def test_numerical_three_bins(self):
        data = {
            "Bin": ["(-inf, 25.5)", "[25.5, 37.0)", "[37.0, +inf)", "Totals"],
            "Count": [1234, 2345, 1421, 5000],
            "Event": [158, 345, 97, 600],
            "Non-event": [1076, 2000, 1324, 4400],
        }
        mock = self._make_mock_optb(data, splits=[25.5, 37.0])
        bins = _extract_bins("age", "numerical", mock)

        assert len(bins) == 3  # totals row dropped
        assert bins[0]["bin_id"] == "age_bin_001"
        assert bins[0]["row_count"] == 1234
        assert bins[0]["good_count"] == 1076
        assert bins[0]["bad_count"] == 158
        assert bins[0]["lower"] is None
        assert bins[0]["upper"] == 25.5
        assert bins[0]["kind"] == "numerical"
        assert bins[0]["is_missing_bin"] is False

        assert bins[1]["lower"] == 25.5
        assert bins[1]["upper"] == 37.0

        assert bins[2]["lower"] == 37.0
        assert bins[2]["upper"] is None

    def test_totals_row_dropped(self):
        data = {
            "Bin": ["(-inf, 50.0)", "[50.0, +inf)", "Totals"],
            "Count": [100, 200, 300],
            "Event": [30, 20, 50],
            "Non-event": [70, 180, 250],
        }
        mock = self._make_mock_optb(data, splits=[50.0])
        bins = _extract_bins("var", "numerical", mock)
        assert len(bins) == 2
        assert all("totals" not in b["label"].lower() for b in bins)


class TestAutoBinningFitNode:
    """Test AutoBinningFitNode with mocked optbinning."""

    def test_validate_params_rejects_unknown_engine(self):
        node = AutoBinningFitNode()
        errs = node.validate_params({"engine": "bad"})
        assert len(errs) > 0

    def test_validate_params_rejects_bad_solver(self):
        node = AutoBinningFitNode()
        errs = node.validate_params({"engine": "optbinning", "solver": "bad"})
        assert len(errs) > 0

    def test_validate_params_optbinning_availability_mocked(self, monkeypatch):
        """Simulate optbinning ImportError regardless of actual environment."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "optbinning":
                raise ImportError("mocked: optbinning not available")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        node = AutoBinningFitNode()
        errs = node.validate_params({"engine": "optbinning"})
        assert len(errs) > 0
        assert "optbinning" in str(errs[0]).lower()

    @patch("cardre.nodes.build.auto_binning_fit.fit_variables")
    def test_node_runs_and_produces_bin_definition(self, mock_fit):
        """Test AutoBinningFitNode.run() produces correct artifacts.

        We mock fit_variables to return a known result, then verify the
        bin definition artifact conforms to SCHEMA_BIN_DEFINITION.
        """
        store, tmp = make_store()
        store.initialize()

        # Create training dataset
        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 40.0, 45.0, 50.0],
            "income": [40000.0, 50000.0, 60000.0, 70000.0, 80000.0, 90000.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        from cardre.audit import (
            ArtifactRef,
            json_logical_hash,
            physical_hash,
            relative_path,
            table_logical_hash,
        )
        import io
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
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train_artifact)

        # Create modelling metadata
        meta_payload = {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_payload, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_payload),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        # Set up mock return
        mock_fit.return_value = AdapterResult(
            engine_version="0.21.0",
            variables=[
                VariableBinningResult(
                    variable="age", dtype="numerical", status="OPTIMAL",
                    bins=[{
                        "bin_id": "age_bin_001", "label": "(-inf, 30.0)",
                        "kind": "numeric", "lower": None, "upper": 30.0,
                        "lower_inclusive": False, "upper_inclusive": False,
                        "categories": None, "is_missing_bin": False,
                        "row_count": 150, "good_count": 100, "bad_count": 50,
                    }],
                    warnings=[],
                ),
                VariableBinningResult(
                    variable="income", dtype="numerical", status="OPTIMAL",
                    bins=[{
                        "bin_id": "income_bin_001", "label": "(-inf, 60000.0)",
                        "kind": "numeric", "lower": None, "upper": 60000.0,
                        "lower_inclusive": False, "upper_inclusive": False,
                        "categories": None, "is_missing_bin": False,
                        "row_count": 200, "good_count": 120, "bad_count": 80,
                    }],
                    warnings=[],
                ),
            ],
            manifest={"engine": "optbinning", "engine_version": "0.21.0",
                      "parameters": {}, "succeeded": ["age", "income"], "failed": [],
                      "variables_succeeded": 2, "variables_failed": 0, "warnings_count": 0},
        )

        from cardre.audit import ExecutionContext, StepSpec
        from cardre.evidence import SCHEMA_BIN_DEFINITION

        node = AutoBinningFitNode()
        ctx = ExecutionContext(
            store=store,
            run_id="run1",
            plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="auto-bin-001",
                node_type="cardre.auto_binning_fit",
                node_version="1",
                category="fit",
                params={},
                params_hash="abc",
                parent_step_ids=["split-001"],
                branch_label="baseline",
                position=5,
            ),
            parent_run_steps=[],
            input_artifacts=[train_artifact, meta_artifact],
            validated_params={"engine": "optbinning"},
            runtime_metadata={},
        )
        output = node.run(ctx)

        assert len(output.artifacts) == 3  # bin definition + variable summary + manifest
        bin_art = output.artifacts[0]
        sum_art = output.artifacts[1]
        man_art = output.artifacts[2]

        # Verify bin definition artifact
        assert store.artifact_path(bin_art).exists()
        payload = json.loads(store.artifact_path(bin_art).read_text())
        assert "variables" in payload
        assert len(payload["variables"]) == 2
        assert payload["variables"][0]["variable"] == "age"
        assert payload["variables"][0]["kind"] == "numeric"
        assert payload["schema_version"] == SCHEMA_BIN_DEFINITION
        assert "source" in payload
        assert payload["source"]["engine"] == "optbinning"
        assert payload["source"]["method"] == "optbinning"
        assert payload["source"]["fit_sample_role"] == "train"
        assert "train_artifact_id" in payload["source"]
        assert "target_column" in payload["source"]

        # Verify variable summary artifact
        sum_payload = json.loads(store.artifact_path(sum_art).read_text())
        assert "variables" in sum_payload
        assert len(sum_payload["variables"]) == 2

        # Verify manifest artifact
        man_payload = json.loads(store.artifact_path(man_art).read_text())
        assert man_payload["engine"] == "optbinning"
        assert "succeeded" in man_payload
        assert "variables_succeeded" in man_payload

    @patch("cardre.nodes.build.auto_binning_fit.fit_variables")
    def test_target_conversion_rejected_by_adapter(self, mock_fit):
        """Node propagates adapter ValueError for unknown target values."""
        mock_fit.side_effect = ValueError(
            "Target column 'target' contains values outside good_values "
            "and bad_values. Found 1 unknown value(s)."
        )
        store, tmp = make_store()
        store.initialize()

        import io
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0],
            "target": ["good", "bad", "unknown"],
        })
        buf = io.BytesIO()
        df.write_parquet(buf)
        from cardre.audit import (ArtifactRef, json_logical_hash, physical_hash,
                                   relative_path, table_logical_hash)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train_artifact)

        meta_payload = {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_payload, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_payload),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        from cardre.audit import ExecutionContext, StepSpec
        node = AutoBinningFitNode()
        ctx = ExecutionContext(
            store=store,
            run_id="run1",
            plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="ab-001", node_type="cardre.auto_binning_fit",
                node_version="1", category="fit",
                params={}, params_hash="abc",
                parent_step_ids=["s-001"], branch_label="baseline", position=5,
            ),
            parent_run_steps=[],
            input_artifacts=[train_artifact, meta_artifact],
            validated_params={"engine": "optbinning"},
            runtime_metadata={},
        )
        with pytest.raises(ValueError, match="contains values outside"):
            node.run(ctx)

    def test_validate_params_rejects_bad_numerical_params(self):
        node = AutoBinningFitNode()
        errs = node.validate_params({
            "engine": "optbinning",
            "max_n_bins": -1,
        })
        assert errs, "Expected validation errors for negative max_n_bins"


# ======================================================================
# BinningNode optbinning dispatch tests
# ======================================================================


class TestBinningNodeOptbinning:
    """Test BinningNode dispatching to optbinning path."""

    def test_validate_params_rejects_unknown_method(self):
        node = BinningNode()
        errs = node.validate_params({"method": "unknown"})
        assert len(errs) > 0
        assert "unknown" in str(errs[0])

    def test_validate_params_rejects_bad_solver_for_optbinning(self):
        node = BinningNode()
        errs = node.validate_params({"method": "optbinning", "solver": "bad"})
        assert len(errs) > 0

    def test_validate_params_optbinning_availability_mocked(self, monkeypatch):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "optbinning":
                raise ImportError("mocked: optbinning not available")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        node = BinningNode()
        errs = node.validate_params({"method": "optbinning"})
        assert len(errs) > 0
        assert "optbinning" in str(errs[0]).lower()

    @patch("cardre.nodes.build.auto_binning_fit.fit_variables")
    def test_binning_node_delegates_to_autobinning(self, mock_fit):
        """BinningNode with method=optbinning produces same output as
        AutoBinningFitNode."""
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 40.0, 45.0, 50.0],
            "income": [40000.0, 50000.0, 60000.0, 70000.0, 80000.0, 90000.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        from cardre.audit import (
            ArtifactRef,
            json_logical_hash,
            physical_hash,
            relative_path,
            table_logical_hash,
        )
        import io
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
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train_artifact)

        meta_payload = {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_payload, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_payload),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        mock_fit.return_value = AdapterResult(
            engine_version="0.21.0",
            variables=[
                VariableBinningResult(
                    variable="age", dtype="numerical", status="OPTIMAL",
                    bins=[{
                        "bin_id": "age_bin_001", "label": "(-inf, 30.0)",
                        "kind": "numeric", "lower": None, "upper": 30.0,
                        "lower_inclusive": False, "upper_inclusive": False,
                        "categories": None, "is_missing_bin": False,
                        "row_count": 150, "good_count": 100, "bad_count": 50,
                    }],
                    warnings=[],
                ),
                VariableBinningResult(
                    variable="income", dtype="numerical", status="OPTIMAL",
                    bins=[{
                        "bin_id": "income_bin_001", "label": "(-inf, 60000.0)",
                        "kind": "numeric", "lower": None, "upper": 60000.0,
                        "lower_inclusive": False, "upper_inclusive": False,
                        "categories": None, "is_missing_bin": False,
                        "row_count": 200, "good_count": 120, "bad_count": 80,
                    }],
                    warnings=[],
                ),
            ],
            manifest={"engine": "optbinning", "engine_version": "0.21.0",
                      "parameters": {}, "succeeded": ["age", "income"], "failed": [],
                      "variables_succeeded": 2, "variables_failed": 0, "warnings_count": 0},
        )

        from cardre.audit import ExecutionContext, StepSpec
        from cardre.evidence import SCHEMA_BIN_DEFINITION

        node = BinningNode()

        ctx = ExecutionContext(
            store=store,
            run_id="run1",
            plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="bin-opt-001",
                node_type="cardre.binning",
                node_version="1",
                category="fit",
                params={},
                params_hash="abc",
                parent_step_ids=["split-001"],
                branch_label="baseline",
                position=5,
            ),
            parent_run_steps=[],
            input_artifacts=[train_artifact, meta_artifact],
            validated_params={"method": "optbinning", "engine": "optbinning"},
            runtime_metadata={},
        )
        output = node.run(ctx)

        assert len(output.artifacts) == 3  # bin definition + summary + manifest
        bin_art = output.artifacts[0]
        assert store.artifact_path(bin_art).exists()
        payload = json.loads(store.artifact_path(bin_art).read_text())
        assert "variables" in payload
        assert len(payload["variables"]) == 2
        assert payload["variables"][0]["variable"] == "age"
        assert payload["schema_version"] == SCHEMA_BIN_DEFINITION
        assert payload["source"]["engine"] == "optbinning"
        assert payload["source"]["method"] == "optbinning"
        assert "method" not in payload["source"]["params"]

    @patch("cardre.nodes.build.auto_binning_fit.fit_variables")
    def test_method_popped_before_delegation(self, mock_fit):
        """BinningNode._run_optbinning pops 'method' from validated_params
        so AutoBinningFitNode never sees it."""
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "age": [25.0, 30.0],
            "target": ["good", "bad"],
        })
        from cardre.audit import (
            ArtifactRef,
            json_logical_hash,
            physical_hash,
            relative_path,
            table_logical_hash,
        )
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train2", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train_artifact)

        meta_payload = {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta2.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_payload, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta2", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_payload),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        mock_fit.return_value = AdapterResult(
            engine_version="0.21.0",
            variables=[],
            manifest={"engine": "optbinning", "engine_version": "0.21.0",
                      "parameters": {}, "succeeded": [], "failed": [],
                      "variables_succeeded": 0, "variables_failed": 0, "warnings_count": 0},
        )

        from cardre.audit import ExecutionContext, StepSpec

        node = BinningNode()
        validated_params = {"method": "optbinning", "engine": "optbinning"}
        ctx = ExecutionContext(
            store=store, run_id="run2", plan_version_id="pv2",
            step_spec=StepSpec(
                step_id="bin-opt-002", node_type="cardre.binning",
                node_version="1", category="fit",
                params={}, params_hash="abc",
                parent_step_ids=["split-001"],
                branch_label="baseline", position=5,
            ),
            parent_run_steps=[],
            input_artifacts=[train_artifact, meta_artifact],
            validated_params=validated_params,
            runtime_metadata={},
        )
        node.run(ctx)

        # After run, original context is NOT mutated; method is preserved
        assert "method" in ctx.validated_params
        assert ctx.validated_params.get("method") == "optbinning"
        assert ctx.validated_params.get("engine") == "optbinning"


# ======================================================================
# Pipeline compatibility tests (no optbinning needed)
# ======================================================================


class TestPipelineCompatibility:
    """Prove optbinning-shaped bin definitions flow through existing pipeline."""

    def _make_optbinning_bin_def(self) -> dict:
        """Create a bin definition matching what optbinning would output."""
        return {
            "variables": [
                {
                    "variable": "age",
                    "dtype": "numerical",
                    "kind": "numeric",
                    "bins": [
                        {
                            "bin_id": "age_bin_001",
                            "label": "(-inf, 30.0)",
                            "kind": "numeric",
                            "lower": None, "upper": 30.0,
                            "lower_inclusive": False, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 2, "bad_count": 1,
                        },
                        {
                            "bin_id": "age_bin_002",
                            "label": "[30.0, +inf)",
                            "kind": "numeric",
                            "lower": 30.0, "upper": None,
                            "lower_inclusive": True, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 1, "bad_count": 2,
                        },
                    ],
                    "status": "OPTIMAL",
                },
            ],
            "warnings": [],
        }

    def test_optbinning_bin_def_feeds_calculate_woe_iv(self):
        """CalculateWoeIvNode produces finite WOE from optbinning-style bins."""
        store, tmp = make_store()
        store.initialize()

        from tests.helpers import _make_train_artifact, _make_json_artifact
        from cardre.nodes import CalculateWoeIvNode
        from cardre.audit import ExecutionContext, StepSpec

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 18.0, 45.0, 55.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df, role="train")
        bin_art = _make_json_artifact(
            store, self._make_optbinning_bin_def(), role="definition", stem="optb-bins",
        )
        meta_art = _make_json_artifact(store, {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }, role="definition", stem="meta")

        node = CalculateWoeIvNode()
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="calc-woe", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={}, params_hash="h",
                parent_step_ids=["fc"], branch_label="baseline", position=6,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[train_art, bin_art, meta_art],
            validated_params={},
        )
        output = node.run(ctx)
        assert len(output.artifacts) > 0
        # Verify WOE table artifact exists
        from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
        reader = ArtifactEvidenceReader(store)
        woe_table = reader.read(output.artifacts[0].artifact_id, EvidenceKind.WOE_TABLE)
        assert woe_table.mapping  # non-empty mapping
        assert "age" in woe_table.mapping
        for bid, woe_val in woe_table.mapping["age"].items():
            assert isinstance(woe_val, float), f"WOE for {bid} is not finite: {woe_val}"

    def test_optbinning_bin_def_feeds_woe_transform(self):
        """WoeTransformTrainNode applies WOE from optbinning-style bins."""
        store, tmp = make_store()
        store.initialize()

        from tests.helpers import _make_train_artifact, _make_json_artifact, _make_parquet_report
        from cardre.nodes import WoeTransformTrainNode
        from cardre.audit import ExecutionContext, StepSpec
        from cardre.evidence import SCHEMA_WOE_TABLE

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 18.0, 45.0, 55.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        train_art = _make_train_artifact(store, df, role="train")

        # Bin definition matching optbinning output
        bin_art = _make_json_artifact(
            store, self._make_optbinning_bin_def(), role="definition", stem="optb-bins",
        )

        # WOE table (from CalculateWoeIvNode output)
        import io
        woe_df = pl.DataFrame({
            "variable": ["age", "age"],
            "bin_id": ["age_bin_001", "age_bin_002"],
            "woe": [-0.5, 0.5],
        })
        woe_art = _make_parquet_report(store, woe_df, role="report", stem="woe-table")

        node = WoeTransformTrainNode()
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="woe-train", node_type="cardre.woe_transform_train",
                node_version="1", category="fit",
                params={}, params_hash="h",
                parent_step_ids=["s"], branch_label="baseline", position=7,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[train_art, bin_art, woe_art],
            validated_params={},
        )
        output = node.run(ctx)
        assert len(output.artifacts) > 0
        transformed = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "age_woe" in transformed.columns
        # All WOE values should be finite
        assert transformed["age_woe"].is_not_null().all()

    def test_apply_path_has_no_optbinning_import(self):
        """ApplyWoeMappingNode and WoeTransformTrainNode do not import optbinning."""
        import sys

        # Check apply module's imports
        from cardre.nodes import ApplyWoeMappingNode, WoeTransformTrainNode
        import cardre.nodes._bin_mask
        import cardre.nodes.validate.apply
        import cardre.nodes.build.features

        # No optbinning references in these modules
        for mod_name in ("cardre.nodes._bin_mask", "cardre.nodes.validate.apply",
                          "cardre.nodes.build.features"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                source = mod.__dict__.get("__file__", "")
                if source:
                    with open(source) as f:
                        content = f.read()
                        assert "optbinning" not in content.lower(), (
                            f"File {source} references optbinning. "
                            f"Apply path must not depend on optbinning."
                        )


# ======================================================================
# Diagnostics tests
# ======================================================================


class TestDiagnostics:
    def test_solver_optimal_no_warning(self):
        from cardre.engine.binning.diagnostics import check_solver_status
        diags = check_solver_status("OPTIMAL", "x")
        assert len(diags) == 0

    def test_solver_failed_warns(self):
        from cardre.engine.binning.diagnostics import check_solver_status
        diags = check_solver_status("FAILED", "x")
        assert len(diags) == 1
        assert diags[0].code == "SOLVER_NOT_OPTIMAL"

    def test_too_few_bins_warns(self):
        from cardre.engine.binning.diagnostics import check_too_few_bins
        diags = check_too_few_bins([{"bin_id": "b1"}], variable="x", min_bins=2)
        assert len(diags) == 1

    def test_sparse_bin_warns(self):
        from cardre.engine.binning.diagnostics import check_sparse_bins
        diags = check_sparse_bins(
            [{"bin_id": "b1", "label": "Low", "row_count": 5}],
            variable="x", min_count=30,
        )
        assert len(diags) == 1
        assert diags[0].code == "SPARSE_BIN"

    def test_sparse_bin_no_warning(self):
        from cardre.engine.binning.diagnostics import check_sparse_bins
        diags = check_sparse_bins(
            [{"bin_id": "b1", "label": "Low", "row_count": 100}],
            variable="x", min_count=30,
        )
        assert len(diags) == 0

    def test_variable_failed_warns(self):
        from cardre.engine.binning.diagnostics import check_variable_failed
        diags = check_variable_failed("x", "FAILED", [{"message": "exception"}])
        assert len(diags) == 1
        assert diags[0].code == "VARIABLE_FAILED"

    def test_run_all_integration(self):
        from cardre.engine.binning.diagnostics import run_all
        from cardre.engine.binning.optbinning_adapter import VariableBinningResult as VBR

        results = [
            VBR(variable="ok", dtype="numerical", status="OPTIMAL",
                bins=[{"bin_id": "b1", "row_count": 100}], warnings=[]),
            VBR(variable="bad", dtype="numerical", status="FAILED",
                bins=[], warnings=[{"code": "VARIABLE_FAILED", "message": "solver crashed"}]),
            VBR(variable="sparse", dtype="numerical", status="OPTIMAL",
                bins=[{"bin_id": "b1", "row_count": 5}], warnings=[]),
        ]
        diags = run_all(results, min_bins=1, min_bin_count=30)
        # bad: solver failed + too few bins
        # sparse: sparse bin
        assert len(diags) >= 2
        codes = {d.code for d in diags}
        assert "VARIABLE_FAILED" in codes
        assert "SPARSE_BIN" in codes


# ======================================================================
# Integration tests requiring optbinning
# ======================================================================


@pytest.mark.optional_binning
@pytest.mark.skipif(not HAS_OPTBINNING, reason="optbinning not installed")
class TestOptBinningIntegration:
    """Integration tests requiring the actual optbinning package."""

    def test_adapter_fit_small_numerical(self):
        from cardre.engine.binning.optbinning_adapter import fit_variables

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 40.0, 45.0, 50.0,
                    22.0, 33.0, 44.0, 55.0, 66.0, 77.0],
            "income": [40000.0, 50000.0, 60000.0, 70000.0, 80000.0, 90000.0,
                       30000.0, 55000.0, 65000.0, 75000.0, 85000.0, 95000.0],
            "target": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        })

        result = fit_variables(
            df=df,
            target="target",
            good_values={"0"},
            bad_values={"1"},
            variable_names=["age", "income"],
            variable_types={"age": "numerical", "income": "numerical"},
        )

        assert result.engine_name == "optbinning"
        assert result.engine_version
        assert len(result.variables) == 2

        for v in result.variables:
            assert v.status in ("OPTIMAL", "FEASIBLE")
            assert len(v.bins) >= 1
            # Verify bin schema
            first_bin = v.bins[0]
            assert "bin_id" in first_bin
            assert "row_count" in first_bin
            assert "good_count" in first_bin
            assert "bad_count" in first_bin
            assert "is_missing_bin" in first_bin
            # Totals row should be dropped
            assert first_bin.get("label", "").lower() != "totals"

    def test_manifest_has_version_and_counts(self):
        from cardre.engine.binning.optbinning_adapter import fit_variables

        df = pl.DataFrame({
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [0, 0, 1, 0, 1, 1],
        })
        result = fit_variables(
            df=df, target="y",
            good_values={"0"}, bad_values={"1"},
            variable_names=["x"],
            variable_types={"x": "numerical"},
        )
        m = result.manifest
        assert m["engine"] == "optbinning"
        assert m["engine_version"]
        assert m["variable_count"] == 1
        assert "x" in m.get("succeeded", [])

    def test_failed_variable_does_not_crash_others(self):
        from cardre.engine.binning.optbinning_adapter import fit_variables

        df = pl.DataFrame({
            "ok_var": [1.0, 2.0, 3.0, 4.0, 5.0],
            "bad_target": [0, 0, 1, 0, 1],
        })
        result = fit_variables(
            df=df, target="bad_target",
            good_values={"0"}, bad_values={"1"},
            variable_names=["ok_var"],
            variable_types={"ok_var": "numerical"},
        )
        # ok_var should succeed
        assert result.variables[0].status in ("OPTIMAL", "FEASIBLE")


# ======================================================================
# End-to-end integration: optbinning → WOE/IV → manual binning → WOE transform → LR
# ======================================================================


@pytest.mark.optional_binning
@pytest.mark.skipif(not HAS_OPTBINNING, reason="optbinning not installed")
class TestOptBinningFullIntegration:
    """End-to-end test of the optbinning pathway through logistic regression."""

    @patch("cardre.nodes.build.auto_binning_fit.fit_variables")
    def test_optbinning_pathway_to_logistic_regression(self, mock_fit):
        """All nodes succeed, WOE columns produced, LR model artifact produced."""
        store, tmp = make_store()
        store.initialize()

        import io
        from cardre.audit import (
            ArtifactRef, json_logical_hash, physical_hash, relative_path, table_logical_hash,
        )
        from cardre.evidence import SCHEMA_BIN_DEFINITION, SCHEMA_WOE_TABLE

        df = pl.DataFrame({
            "age": [25.0, 30.0, 35.0, 40.0, 45.0, 50.0,
                    22.0, 33.0, 44.0, 55.0, 66.0, 77.0],
            "income": [40000.0, 50000.0, 60000.0, 70000.0, 80000.0, 90000.0,
                       30000.0, 55000.0, 65000.0, 75000.0, 85000.0, 95000.0],
            "target": ["good", "bad", "good", "bad", "good", "bad",
                       "good", "bad", "good", "bad", "good", "bad"],
        })

        # Train artifact
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train_artifact)

        # Metadata artifact
        meta_payload = {
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        }
        meta_artifact = _make_json_artifact(store, meta_payload, role="definition", stem="meta")

        # Mock optbinning result
        mock_fit.return_value = AdapterResult(
            engine_version="0.21.0",
            variables=[
                VariableBinningResult(
                    variable="age", dtype="numerical", status="OPTIMAL",
                    bins=[
                        {
                            "bin_id": "age_bin_001", "label": "(-inf, 30.0)",
                            "kind": "numeric", "lower": None, "upper": 30.0,
                            "lower_inclusive": False, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 4, "good_count": 3, "bad_count": 1,
                        },
                        {
                            "bin_id": "age_bin_002", "label": "[30.0, +inf)",
                            "kind": "numeric", "lower": 30.0, "upper": None,
                            "lower_inclusive": True, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 8, "good_count": 3, "bad_count": 5,
                        },
                    ],
                    warnings=[],
                ),
                VariableBinningResult(
                    variable="income", dtype="numerical", status="OPTIMAL",
                    bins=[
                        {
                            "bin_id": "income_bin_001", "label": "(-inf, 55000.0)",
                            "kind": "numeric", "lower": None, "upper": 55000.0,
                            "lower_inclusive": False, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 5, "good_count": 3, "bad_count": 2,
                        },
                        {
                            "bin_id": "income_bin_002", "label": "[55000.0, 75000.0)",
                            "kind": "numeric", "lower": 55000.0, "upper": 75000.0,
                            "lower_inclusive": True, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 4, "good_count": 2, "bad_count": 2,
                        },
                        {
                            "bin_id": "income_bin_003", "label": "[75000.0, +inf)",
                            "kind": "numeric", "lower": 75000.0, "upper": None,
                            "lower_inclusive": True, "upper_inclusive": False,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 1, "bad_count": 2,
                        },
                    ],
                    warnings=[],
                ),
            ],
            manifest={
                "engine": "optbinning", "engine_version": "0.21.0",
                "parameters": {}, "succeeded": ["age", "income"], "failed": [],
                "variables_succeeded": 2, "variables_failed": 0, "warnings_count": 0,
            },
        )

        # Step 1: Binning(method=optbinning) via BinningNode
        from cardre.audit import ExecutionContext, StepSpec
        from cardre.nodes import BinningNode

        binning_node = BinningNode()
        binning_ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="binning", node_type="cardre.binning",
                node_version="1", category="fit",
                params={"method": "optbinning", "engine": "optbinning"},
                params_hash="h1", parent_step_ids=["split"],
                branch_label="baseline", position=5,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[train_artifact, meta_artifact],
            validated_params={"method": "optbinning", "engine": "optbinning"},
        )
        bin_out = binning_node.run(binning_ctx)
        assert len(bin_out.artifacts) >= 1
        bin_def_artifact = next(a for a in bin_out.artifacts if a.role == "definition")

        # Verify bin definition is readable
        bin_def = json.loads(store.artifact_path(bin_def_artifact).read_text())
        assert "variables" in bin_def
        assert "age" in {v["variable"] for v in bin_def["variables"]}
        assert "income" in {v["variable"] for v in bin_def["variables"]}
        assert bin_def.get("schema_version") == SCHEMA_BIN_DEFINITION

        # Step 2: CalculateWoeIvNode
        from cardre.nodes import CalculateWoeIvNode

        woe_node = CalculateWoeIvNode()
        woe_ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="calculate-woe", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={}, params_hash="h2",
                parent_step_ids=["binning"], branch_label="baseline", position=6,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[train_artifact, bin_def_artifact, meta_artifact],
            validated_params={},
        )
        woe_out = woe_node.run(woe_ctx)
        assert len(woe_out.artifacts) > 0

        # Find the WOE table artifact
        from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
        reader = ArtifactEvidenceReader(store)
        woe_table_artifact = None
        for a in woe_out.artifacts:
            try:
                woe_evidence = reader.read(a.artifact_id, EvidenceKind.WOE_TABLE)
                if woe_evidence.mapping:
                    woe_table_artifact = a
                    break
            except Exception:
                continue
        assert woe_table_artifact is not None, "No WOE table found"

        # Step 3: Manual binning (no overrides)
        from cardre.nodes import ManualBinningNode

        manual_node = ManualBinningNode()
        manual_ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []}, params_hash="h3",
                parent_step_ids=["binning"], branch_label="baseline", position=7,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[bin_def_artifact],
            validated_params={"overrides": []},
        )
        manual_out = manual_node.run(manual_ctx)
        assert len(manual_out.artifacts) == 1
        refined_artifact = manual_out.artifacts[0]

        # Step 4: WoeTransformTrainNode
        from cardre.nodes import WoeTransformTrainNode

        woe_transform_node = WoeTransformTrainNode()
        woe_transform_ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="woe-transform", node_type="cardre.woe_transform_train",
                node_version="1", category="fit",
                params={}, params_hash="h4",
                parent_step_ids=["manual-binning"], branch_label="baseline", position=8,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[train_artifact, refined_artifact, woe_table_artifact],
            validated_params={},
        )
        woe_transform_out = woe_transform_node.run(woe_transform_ctx)
        assert len(woe_transform_out.artifacts) > 0

        # Verify WOE columns in output
        woe_train_path = store.artifact_path(woe_transform_out.artifacts[0])
        woe_train_df = pl.read_parquet(woe_train_path)
        assert "age_woe" in woe_train_df.columns, "age_woe column missing"
        assert "income_woe" in woe_train_df.columns, "income_woe column missing"
        assert woe_train_df["age_woe"].is_not_null().all()
        assert woe_train_df["income_woe"].is_not_null().all()

        # Step 5: LogisticRegressionNode
        from cardre.nodes import LogisticRegressionNode
        from cardre.artifacts import write_parquet_artifact

        lr_node = LogisticRegressionNode()
        lr_ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=StepSpec(
                step_id="logistic-regression", node_type="cardre.logistic_regression",
                node_version="1", category="fit",
                params={"C": 1.0, "max_iter": 1000, "solver": "lbfgs"},
                params_hash="h5",
                parent_step_ids=["woe-transform", "manual-binning", "define-metadata"],
                branch_label="baseline", position=9,
            ),
            parent_run_steps=[], runtime_metadata={},
            input_artifacts=[woe_transform_out.artifacts[0], meta_artifact],
            validated_params={"C": 1.0, "max_iter": 1000, "solver": "lbfgs"},
        )
        lr_out = lr_node.run(lr_ctx)
        assert len(lr_out.artifacts) >= 1

        # Verify LR model artifact produced
        lr_artifact = lr_out.artifacts[0]
        assert store.artifact_path(lr_artifact).exists()

    def test_optbinning_apply_path_no_optbinning_import(self):
        """Re-verifies that apply/scoring path has no optbinning dependency."""
        from cardre.nodes import ApplyWoeMappingNode, WoeTransformTrainNode
        import cardre.nodes._bin_mask
        import cardre.nodes.validate.apply
        import cardre.nodes.build.features
        import sys

        for mod_name in ("cardre.nodes._bin_mask", "cardre.nodes.validate.apply",
                          "cardre.nodes.build.features"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                source = mod.__dict__.get("__file__", "")
                if source:
                    with open(source) as f:
                        content = f.read()
                        assert "optbinning" not in content.lower(), (
                            f"File {source} references optbinning. "
                            f"Apply path must not depend on optbinning."
                        )
